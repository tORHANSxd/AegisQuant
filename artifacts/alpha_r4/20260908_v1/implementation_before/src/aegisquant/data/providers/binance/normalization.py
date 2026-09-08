"""Binance JSON normalization into strict, point-in-time Silver records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import cast

import pyarrow as pa

from aegisquant.data.hashing import canonical_json_bytes
from aegisquant.data.providers.binance.contracts import Product
from aegisquant.data.providers.binance.models import (
    BookTickerRecord,
    DepthDeltaRecord,
    FundingRateRecord,
    InstrumentSnapshot,
    KlineRecord,
    MarkIndexRecord,
    OpenInterestRecord,
    PriceBasis,
    Provenance,
    QualityStatus,
    TimedMarketRecord,
    TradeRecord,
)


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a string-keyed object")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{label} must be a string-keyed object")
    return {cast(str, key): item for key, item in raw.items()}


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be an array")
    return cast(Sequence[object], value)


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _decimal(value: object, *, label: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an exchange decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} is not a decimal") from error
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _milliseconds(value: object, *, label: str) -> datetime:
    milliseconds = _integer(value, label=label)
    if milliseconds < 0:
        raise ValueError(f"{label} cannot be negative")
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _times(event_time: datetime, observed_at: datetime) -> tuple[datetime, datetime]:
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    observed = observed_at.astimezone(UTC)
    available = max(event_time, observed)
    return available, available


def _provenance(payload: object, *, source: str, request_hash: str) -> Provenance:
    import hashlib

    return Provenance(
        source=source,
        source_request_hash=request_hash,
        raw_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    )


def _filter_map(symbol: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows = _sequence(symbol.get("filters"), label="filters")
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        item = _mapping(row, label="filter")
        result[_string(item.get("filterType"), label="filterType")] = item
    return result


def normalize_instruments(
    payload: object,
    *,
    product: Product,
    observed_at: datetime,
    request_hash: str,
    processed_at: datetime | None = None,
) -> tuple[InstrumentSnapshot, ...]:
    root = _mapping(payload, label="exchangeInfo")
    symbols = _sequence(root.get("symbols"), label="symbols")
    server_value = root.get("serverTime")
    snapshot_event_time = (
        _milliseconds(server_value, label="serverTime")
        if server_value is not None
        else observed_at.astimezone(UTC)
    )
    available, ingest = _times(snapshot_event_time, observed_at)
    processed = max(processed_at or ingest, ingest)
    provenance = _provenance(
        payload, source=f"{product.value}:exchangeInfo", request_hash=request_hash
    )
    snapshots: list[InstrumentSnapshot] = []
    for raw_symbol in symbols:
        symbol = _mapping(raw_symbol, label="symbol")
        filters = _filter_map(symbol)
        price_filter = filters.get("PRICE_FILTER", {})
        lot_filter = filters.get("LOT_SIZE", {})
        notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        symbol_name = _string(symbol.get("symbol"), label="symbol")
        contract_type = symbol.get("contractType")
        delivery_date = symbol.get("deliveryDate")
        expiry = None
        if product is Product.USD_M and contract_type != "PERPETUAL" and delivery_date is not None:
            expiry = _milliseconds(delivery_date, label="deliveryDate")
        codes: list[str] = []
        if server_value is None:
            codes.append("EXCHANGE_SNAPSHOT_TIME_ABSENT")
        status = _string(symbol.get("status"), label="status")
        known_statuses = {"TRADING", "HALT", "BREAK", "CANCEL_ONLY", "PENDING_TRADING"}
        if status not in known_statuses:
            codes.append("UNKNOWN_INSTRUMENT_STATUS_PRESERVED")
        snapshots.append(
            InstrumentSnapshot(
                product=product,
                symbol=symbol_name,
                event_time=snapshot_event_time,
                available_time=available,
                ingest_time=ingest,
                processed_time=processed,
                revision_time=None,
                quality_status=QualityStatus.WARNING if codes else QualityStatus.VALID,
                quality_codes=tuple(codes),
                provenance=provenance,
                instrument_id=f"BINANCE:{product.value}:{symbol_name}",
                base_asset=_string(symbol.get("baseAsset"), label="baseAsset"),
                quote_asset=_string(symbol.get("quoteAsset"), label="quoteAsset"),
                settlement_asset=(
                    _string(symbol.get("marginAsset"), label="marginAsset")
                    if product is Product.USD_M
                    else None
                ),
                contract_size=Decimal("1"),
                status=status,
                tick_size=_decimal(price_filter.get("tickSize"), label="tickSize"),
                step_size=_decimal(lot_filter.get("stepSize"), label="stepSize"),
                min_quantity=_decimal(lot_filter.get("minQty"), label="minQty"),
                max_quantity=_decimal(lot_filter.get("maxQty"), label="maxQty"),
                min_notional=_decimal(notional_filter.get("minNotional", "0"), label="minNotional"),
                expiry_time=expiry,
                valid_from=available,
                valid_to=None,
                source_snapshot_id=provenance.raw_sha256,
            )
        )
    return tuple(snapshots)


def normalize_kline(
    row: object,
    *,
    product: Product,
    symbol: str,
    interval: str,
    price_basis: PriceBasis,
    observed_at: datetime,
    request_hash: str,
    source: str,
    processed_at: datetime | None = None,
) -> KlineRecord:
    values = _sequence(row, label="kline")
    if len(values) < 11:
        raise ValueError("REST Kline requires at least 11 fields")
    open_time = _milliseconds(values[0], label="openTime")
    close_time = _milliseconds(values[6], label="closeTime")
    observed = observed_at.astimezone(UTC)
    is_closed = close_time < observed
    event_time = close_time if is_closed else observed
    available, ingest = _times(event_time, observed)
    processed = max(processed_at or ingest, ingest)
    codes = () if is_closed else ("INCOMPLETE_KLINE",)
    return KlineRecord(
        product=product,
        symbol=symbol,
        event_time=event_time,
        available_time=available,
        ingest_time=ingest,
        processed_time=processed,
        revision_time=None,
        quality_status=QualityStatus.VALID if is_closed else QualityStatus.WARNING,
        quality_codes=codes,
        provenance=_provenance(row, source=source, request_hash=request_hash),
        price_basis=price_basis,
        interval=interval,
        open_time=open_time,
        close_time=close_time,
        open=_decimal(values[1], label="open"),
        high=_decimal(values[2], label="high"),
        low=_decimal(values[3], label="low"),
        close=_decimal(values[4], label="close"),
        base_volume=_decimal(values[5], label="baseVolume"),
        quote_volume=_decimal(values[7], label="quoteVolume"),
        trade_count=_integer(values[8], label="tradeCount"),
        taker_buy_base_volume=_decimal(values[9], label="takerBuyBaseVolume"),
        taker_buy_quote_volume=_decimal(values[10], label="takerBuyQuoteVolume"),
        is_closed=is_closed,
        trading_day_utc=open_time.date().isoformat(),
    )


def normalize_trade(
    payload: object,
    *,
    product: Product,
    symbol: str,
    aggregate: bool,
    observed_at: datetime,
    request_hash: str,
    source: str,
    processed_at: datetime | None = None,
) -> TradeRecord:
    row = _mapping(payload, label="trade")
    if aggregate:
        trade_id = _integer(row.get("a"), label="aggregateTradeId")
        first_id = _integer(row.get("f"), label="firstTradeId")
        last_id = _integer(row.get("l"), label="lastTradeId")
        price = row.get("p")
        quantity = row.get("q")
        quote_quantity = str(_decimal(price, label="price") * _decimal(quantity, label="quantity"))
        event_value = row.get("T")
        maker = row.get("m")
    else:
        trade_id = _integer(row.get("id", row.get("t")), label="tradeId")
        first_id = None
        last_id = None
        price = row.get("price", row.get("p"))
        quantity = row.get("qty", row.get("q"))
        quote_quantity = row.get("quoteQty", row.get("Q"))
        event_value = row.get("time", row.get("T"))
        maker = row.get("isBuyerMaker", row.get("m"))
    if not isinstance(maker, bool):
        raise ValueError("buyer maker flag must be boolean")
    event_time = _milliseconds(event_value, label="tradeTime")
    available, ingest = _times(event_time, observed_at)
    processed = max(processed_at or ingest, ingest)
    return TradeRecord(
        product=product,
        symbol=symbol,
        event_time=event_time,
        available_time=available,
        ingest_time=ingest,
        processed_time=processed,
        revision_time=None,
        quality_status=QualityStatus.VALID,
        quality_codes=(),
        provenance=_provenance(payload, source=source, request_hash=request_hash),
        trade_id=trade_id,
        aggregate_trade=aggregate,
        first_trade_id=first_id,
        last_trade_id=last_id,
        price=_decimal(price, label="price"),
        quantity=_decimal(quantity, label="quantity"),
        quote_quantity=_decimal(quote_quantity, label="quoteQuantity"),
        buyer_is_maker=maker,
    )


def normalize_book_ticker(
    payload: object,
    *,
    product: Product,
    symbol: str,
    observed_at: datetime,
    request_hash: str,
    source: str,
    processed_at: datetime | None = None,
) -> BookTickerRecord:
    row = _mapping(payload, label="bookTicker")
    event_value = row.get("E", row.get("T"))
    event_time = (
        _milliseconds(event_value, label="eventTime")
        if event_value is not None
        else observed_at.astimezone(UTC)
    )
    available, ingest = _times(event_time, observed_at)
    processed = max(processed_at or ingest, ingest)
    raw_update = row.get("u")
    update_id = _integer(raw_update, label="updateId") if raw_update is not None else None
    return BookTickerRecord(
        product=product,
        symbol=symbol,
        event_time=event_time,
        available_time=available,
        ingest_time=ingest,
        processed_time=processed,
        revision_time=None,
        quality_status=QualityStatus.VALID,
        quality_codes=(),
        provenance=_provenance(payload, source=source, request_hash=request_hash),
        update_id=update_id,
        best_bid_price=_decimal(row.get("b", row.get("bidPrice")), label="bidPrice"),
        best_bid_quantity=_decimal(row.get("B", row.get("bidQty")), label="bidQty"),
        best_ask_price=_decimal(row.get("a", row.get("askPrice")), label="askPrice"),
        best_ask_quantity=_decimal(row.get("A", row.get("askQty")), label="askQty"),
    )


def _levels(value: object, *, label: str) -> tuple[tuple[Decimal, Decimal], ...]:
    result: list[tuple[Decimal, Decimal]] = []
    for raw_level in _sequence(value, label=label):
        level = _sequence(raw_level, label=f"{label} level")
        if len(level) != 2:
            raise ValueError(f"{label} level must contain price and quantity")
        result.append((_decimal(level[0], label="price"), _decimal(level[1], label="quantity")))
    return tuple(result)


def normalize_depth_delta(
    payload: object,
    *,
    product: Product,
    symbol: str,
    observed_at: datetime,
    request_hash: str,
    source: str,
    processed_at: datetime | None = None,
) -> DepthDeltaRecord:
    row = _mapping(payload, label="depthDelta")
    event_time = _milliseconds(row.get("E"), label="eventTime")
    available, ingest = _times(event_time, observed_at)
    processed = max(processed_at or ingest, ingest)
    raw_previous = row.get("pu")
    return DepthDeltaRecord(
        product=product,
        symbol=symbol,
        event_time=event_time,
        available_time=available,
        ingest_time=ingest,
        processed_time=processed,
        revision_time=None,
        quality_status=QualityStatus.VALID,
        quality_codes=(),
        provenance=_provenance(payload, source=source, request_hash=request_hash),
        first_update_id=_integer(row.get("U"), label="firstUpdateId"),
        final_update_id=_integer(row.get("u"), label="finalUpdateId"),
        previous_final_update_id=(
            _integer(raw_previous, label="previousFinalUpdateId")
            if raw_previous is not None
            else None
        ),
        bids=_levels(row.get("b"), label="bids"),
        asks=_levels(row.get("a"), label="asks"),
    )


def normalize_mark_index(
    payload: object,
    *,
    symbol: str,
    observed_at: datetime,
    request_hash: str,
    source: str,
    processed_at: datetime | None = None,
) -> MarkIndexRecord:
    row = _mapping(payload, label="markIndex")
    event_value = row.get("time", row.get("E"))
    event_time = _milliseconds(event_value, label="eventTime")
    available, ingest = _times(event_time, observed_at)
    processed = max(processed_at or ingest, ingest)
    estimated = row.get("estimatedSettlePrice", row.get("P"))
    funding = row.get("lastFundingRate", row.get("r"))
    next_funding = row.get("nextFundingTime", row.get("T"))
    return MarkIndexRecord(
        product=Product.USD_M,
        symbol=symbol,
        event_time=event_time,
        available_time=available,
        ingest_time=ingest,
        processed_time=processed,
        revision_time=None,
        quality_status=QualityStatus.VALID,
        quality_codes=(),
        provenance=_provenance(payload, source=source, request_hash=request_hash),
        mark_price=_decimal(row.get("markPrice", row.get("p")), label="markPrice"),
        index_price=_decimal(row.get("indexPrice", row.get("i")), label="indexPrice"),
        estimated_settle_price=(
            _decimal(estimated, label="estimatedSettlePrice") if estimated is not None else None
        ),
        funding_rate=_decimal(funding, label="fundingRate") if funding is not None else None,
        next_funding_time=(
            _milliseconds(next_funding, label="nextFundingTime")
            if next_funding is not None
            else None
        ),
    )


def normalize_funding_rate(
    payload: object,
    *,
    observed_at: datetime,
    request_hash: str,
    source: str,
    processed_at: datetime | None = None,
) -> FundingRateRecord:
    row = _mapping(payload, label="fundingRate")
    event_time = _milliseconds(row.get("fundingTime"), label="fundingTime")
    available, ingest = _times(event_time, observed_at)
    processed = max(processed_at or ingest, ingest)
    raw_mark = row.get("markPrice")
    return FundingRateRecord(
        product=Product.USD_M,
        symbol=_string(row.get("symbol"), label="symbol"),
        event_time=event_time,
        available_time=available,
        ingest_time=ingest,
        processed_time=processed,
        revision_time=None,
        quality_status=QualityStatus.VALID,
        quality_codes=(),
        provenance=_provenance(payload, source=source, request_hash=request_hash),
        funding_time=event_time,
        funding_rate=_decimal(row.get("fundingRate"), label="fundingRate"),
        mark_price=_decimal(raw_mark, label="markPrice") if raw_mark is not None else None,
        is_final=event_time <= observed_at.astimezone(UTC),
    )


def normalize_open_interest(
    payload: object,
    *,
    symbol: str,
    observed_at: datetime,
    request_hash: str,
    source: str,
    period: str | None = None,
    processed_at: datetime | None = None,
) -> OpenInterestRecord:
    row = _mapping(payload, label="openInterest")
    event_value = row.get("timestamp", row.get("time"))
    event_time = (
        _milliseconds(event_value, label="eventTime")
        if event_value is not None
        else observed_at.astimezone(UTC)
    )
    available, ingest = _times(event_time, observed_at)
    processed = max(processed_at or ingest, ingest)
    raw_value = row.get("sumOpenInterestValue")
    raw_interest = row.get("sumOpenInterest", row.get("openInterest"))
    return OpenInterestRecord(
        product=Product.USD_M,
        symbol=symbol,
        event_time=event_time,
        available_time=available,
        ingest_time=ingest,
        processed_time=processed,
        revision_time=None,
        quality_status=QualityStatus.VALID,
        quality_codes=(),
        provenance=_provenance(payload, source=source, request_hash=request_hash),
        period=period,
        open_interest=_decimal(raw_interest, label="openInterest"),
        open_interest_value=(
            _decimal(raw_value, label="openInterestValue") if raw_value is not None else None
        ),
        unit="BASE_ASSET" if raw_value is None else "CONTRACT_AND_QUOTE_VALUE",
    )


_DECIMAL = pa.decimal128(38, 18)
_UTC_TS = pa.timestamp("us", tz="UTC")
_LEVELS = pa.list_(pa.struct([pa.field("price", _DECIMAL), pa.field("quantity", _DECIMAL)]))
_COMMON_FIELDS = (
    pa.field("product", pa.string(), nullable=False),
    pa.field("symbol", pa.string(), nullable=False),
    pa.field("event_time", _UTC_TS, nullable=False),
    pa.field("available_time", _UTC_TS, nullable=False),
    pa.field("ingest_time", _UTC_TS, nullable=False),
    pa.field("processed_time", _UTC_TS, nullable=False),
    pa.field("revision_time", _UTC_TS),
    pa.field("quality_status", pa.string(), nullable=False),
    pa.field("quality_codes", pa.list_(pa.string()), nullable=False),
    pa.field("provider_id", pa.string(), nullable=False),
    pa.field("source", pa.string(), nullable=False),
    pa.field("source_request_hash", pa.string(), nullable=False),
    pa.field("raw_sha256", pa.string(), nullable=False),
    pa.field("schema_version", pa.string(), nullable=False),
)


def _schema_for(model_type: type[TimedMarketRecord]) -> pa.Schema:
    extra: dict[type[TimedMarketRecord], tuple[pa.Field[pa.DataType], ...]] = {
        InstrumentSnapshot: (
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("base_asset", pa.string(), nullable=False),
            pa.field("quote_asset", pa.string(), nullable=False),
            pa.field("settlement_asset", pa.string()),
            pa.field("contract_size", _DECIMAL, nullable=False),
            pa.field("status", pa.string(), nullable=False),
            pa.field("tick_size", _DECIMAL, nullable=False),
            pa.field("step_size", _DECIMAL, nullable=False),
            pa.field("min_quantity", _DECIMAL, nullable=False),
            pa.field("max_quantity", _DECIMAL),
            pa.field("min_notional", _DECIMAL, nullable=False),
            pa.field("expiry_time", _UTC_TS),
            pa.field("valid_from", _UTC_TS, nullable=False),
            pa.field("valid_to", _UTC_TS),
            pa.field("source_snapshot_id", pa.string(), nullable=False),
        ),
        KlineRecord: (
            pa.field("price_basis", pa.string(), nullable=False),
            pa.field("interval", pa.string(), nullable=False),
            pa.field("open_time", _UTC_TS, nullable=False),
            pa.field("close_time", _UTC_TS, nullable=False),
            pa.field("open", _DECIMAL, nullable=False),
            pa.field("high", _DECIMAL, nullable=False),
            pa.field("low", _DECIMAL, nullable=False),
            pa.field("close", _DECIMAL, nullable=False),
            pa.field("base_volume", _DECIMAL, nullable=False),
            pa.field("quote_volume", _DECIMAL, nullable=False),
            pa.field("trade_count", pa.int64(), nullable=False),
            pa.field("taker_buy_base_volume", _DECIMAL, nullable=False),
            pa.field("taker_buy_quote_volume", _DECIMAL, nullable=False),
            pa.field("is_closed", pa.bool_(), nullable=False),
            pa.field("trading_day_utc", pa.string(), nullable=False),
        ),
        TradeRecord: (
            pa.field("trade_id", pa.int64(), nullable=False),
            pa.field("aggregate_trade", pa.bool_(), nullable=False),
            pa.field("first_trade_id", pa.int64()),
            pa.field("last_trade_id", pa.int64()),
            pa.field("price", _DECIMAL, nullable=False),
            pa.field("quantity", _DECIMAL, nullable=False),
            pa.field("quote_quantity", _DECIMAL, nullable=False),
            pa.field("buyer_is_maker", pa.bool_(), nullable=False),
        ),
        BookTickerRecord: (
            pa.field("update_id", pa.int64()),
            pa.field("best_bid_price", _DECIMAL, nullable=False),
            pa.field("best_bid_quantity", _DECIMAL, nullable=False),
            pa.field("best_ask_price", _DECIMAL, nullable=False),
            pa.field("best_ask_quantity", _DECIMAL, nullable=False),
        ),
        DepthDeltaRecord: (
            pa.field("first_update_id", pa.int64(), nullable=False),
            pa.field("final_update_id", pa.int64(), nullable=False),
            pa.field("previous_final_update_id", pa.int64()),
            pa.field("bids", _LEVELS, nullable=False),
            pa.field("asks", _LEVELS, nullable=False),
        ),
        MarkIndexRecord: (
            pa.field("mark_price", _DECIMAL, nullable=False),
            pa.field("index_price", _DECIMAL, nullable=False),
            pa.field("estimated_settle_price", _DECIMAL),
            pa.field("funding_rate", _DECIMAL),
            pa.field("next_funding_time", _UTC_TS),
        ),
        FundingRateRecord: (
            pa.field("funding_time", _UTC_TS, nullable=False),
            pa.field("funding_rate", _DECIMAL, nullable=False),
            pa.field("mark_price", _DECIMAL),
            pa.field("is_final", pa.bool_(), nullable=False),
        ),
        OpenInterestRecord: (
            pa.field("period", pa.string()),
            pa.field("open_interest", _DECIMAL, nullable=False),
            pa.field("open_interest_value", _DECIMAL),
            pa.field("unit", pa.string(), nullable=False),
        ),
    }
    fields = extra.get(model_type)
    if fields is None:
        raise TypeError(f"unsupported Silver record type: {model_type.__name__}")
    return pa.schema(_COMMON_FIELDS + fields)


def to_silver_table(records: Sequence[TimedMarketRecord]) -> pa.Table:
    """Flatten same-type strict records into a deterministic typed Arrow Silver table."""
    if not records:
        raise ValueError("at least one record is required")
    model_type = type(records[0])
    if any(type(record) is not model_type for record in records):
        raise TypeError("one Silver table cannot mix record types")
    rows: list[dict[str, object]] = []
    for record in records:
        row = record.model_dump(mode="python")
        provenance = cast(dict[str, object], row.pop("provenance"))
        row.update(provenance)
        for key, value in tuple(row.items()):
            if isinstance(value, StrEnum):
                row[key] = value.value
        if isinstance(record, DepthDeltaRecord):
            row["bids"] = [
                {"price": price, "quantity": quantity} for price, quantity in record.bids
            ]
            row["asks"] = [
                {"price": price, "quantity": quantity} for price, quantity in record.asks
            ]
        row["provider_id"] = str(record.provenance.provider_id)
        rows.append(row)
    return pa.Table.from_pylist(rows, schema=_schema_for(model_type))


def instrument_as_of(
    snapshots: Sequence[InstrumentSnapshot],
    *,
    product: Product,
    symbol: str,
    decision_time: datetime,
) -> InstrumentSnapshot:
    """Return the newest instrument rule version actually available at decision_time."""
    if decision_time.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    cutoff = decision_time.astimezone(UTC)
    eligible = [
        snapshot
        for snapshot in snapshots
        if snapshot.product is product
        and snapshot.symbol == symbol
        and snapshot.available_time <= cutoff
        and snapshot.valid_from <= cutoff
        and (snapshot.valid_to is None or cutoff < snapshot.valid_to)
    ]
    if not eligible:
        raise LookupError("AQ-TIME-INSTRUMENT-SNAPSHOT-NOT-AVAILABLE")
    return max(
        eligible,
        key=lambda snapshot: (
            snapshot.valid_from,
            snapshot.available_time,
            snapshot.source_snapshot_id,
        ),
    )
