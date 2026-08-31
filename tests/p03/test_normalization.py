"""Spot/USD-M normalization, Silver schema, time, and incomplete-Kline tests."""

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pyarrow as pa

from aegisquant.data.providers.binance.contracts import Product
from aegisquant.data.providers.binance.models import PriceBasis, QualityStatus
from aegisquant.data.providers.binance.normalization import (
    instrument_as_of,
    normalize_book_ticker,
    normalize_depth_delta,
    normalize_funding_rate,
    normalize_instruments,
    normalize_kline,
    normalize_mark_index,
    normalize_open_interest,
    normalize_trade,
    to_silver_table,
)
from tests.p03.helpers import OBSERVED, REQUEST_HASH, fixture


def test_spot_and_usdm_instruments_preserve_status_and_pit_rules(project_root: Path) -> None:
    spot_payload = fixture(project_root, "spot/exchange_info.json")
    spot = normalize_instruments(
        spot_payload,
        product=Product.SPOT,
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
    )
    usdm = normalize_instruments(
        fixture(project_root, "usdm/exchange_info.json"),
        product=Product.USD_M,
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
    )
    assert {record.status for record in spot} == {"TRADING", "CANCEL_ONLY"}
    assert spot[0].tick_size == Decimal("0.01000000")
    assert usdm[0].settlement_asset == "USDT"
    assert usdm[0].expiry_time is None
    assert usdm[0].instrument_id == "BINANCE:USD_M:BTCUSDT"

    changed_payload = copy.deepcopy(spot_payload)
    changed = cast(dict[str, object], changed_payload)
    changed_symbols = cast(list[dict[str, object]], changed["symbols"])
    changed_filters = cast(list[dict[str, object]], changed_symbols[0]["filters"])
    changed_filters[0]["tickSize"] = "0.10000000"
    later = normalize_instruments(
        changed,
        product=Product.SPOT,
        observed_at=OBSERVED + timedelta(hours=1),
        request_hash="2" * 64,
    )[0]
    early = instrument_as_of(
        (*spot, later),
        product=Product.SPOT,
        symbol="BTCUSDT",
        decision_time=OBSERVED + timedelta(minutes=30),
    )
    late = instrument_as_of(
        (*spot, later),
        product=Product.SPOT,
        symbol="BTCUSDT",
        decision_time=OBSERVED + timedelta(hours=2),
    )
    assert early.tick_size == Decimal("0.01000000")
    assert late.tick_size == Decimal("0.10000000")


def test_kline_trade_book_depth_and_silver_time_contract(project_root: Path) -> None:
    kline = normalize_kline(
        fixture(project_root, "spot/kline.json"),
        product=Product.SPOT,
        symbol="BTCUSDT",
        interval="1m",
        price_basis=PriceBasis.TRADE,
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="spot_klines",
    )
    raw_trades = cast(list[object], fixture(project_root, "spot/trades.json"))
    trades = tuple(
        normalize_trade(
            payload,
            product=Product.SPOT,
            symbol="BTCUSDT",
            aggregate=False,
            observed_at=OBSERVED,
            request_hash=REQUEST_HASH,
            source="spot_trades",
        )
        for payload in raw_trades
    )
    ticker = normalize_book_ticker(
        fixture(project_root, "spot/book_ticker.json"),
        product=Product.SPOT,
        symbol="BTCUSDT",
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="spot_book_ticker",
    )
    raw_depth = cast(list[object], fixture(project_root, "spot/depth_events.json"))[0]
    depth = normalize_depth_delta(
        raw_depth,
        product=Product.SPOT,
        symbol="BTCUSDT",
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="spot_depth",
    )
    assert kline.is_closed is True
    assert kline.trading_day_utc == kline.open_time.date().isoformat()
    assert trades[0].quote_quantity == Decimal("100.00")
    assert ticker.best_ask_price == Decimal("102.00")
    assert depth.first_update_id == 101
    for records in ((kline,), trades, (ticker,), (depth,)):
        table = to_silver_table(records)
        assert isinstance(table, pa.Table)
        assert table.num_rows == len(records)
        assert set(table.column_names) >= {
            "event_time",
            "available_time",
            "ingest_time",
            "processed_time",
            "quality_status",
            "source_request_hash",
            "raw_sha256",
        }


def test_incomplete_kline_is_explicit_and_not_silently_closed(project_root: Path) -> None:
    observed = datetime.fromtimestamp(1_700_000_030, tz=UTC)
    kline = normalize_kline(
        fixture(project_root, "spot/kline.json"),
        product=Product.SPOT,
        symbol="BTCUSDT",
        interval="1m",
        price_basis=PriceBasis.TRADE,
        observed_at=observed,
        request_hash=REQUEST_HASH,
        source="spot_klines",
    )
    assert kline.is_closed is False
    assert kline.quality_status is QualityStatus.WARNING
    assert "INCOMPLETE_KLINE" in kline.quality_codes
    assert kline.event_time == observed
    assert kline.close_time > kline.available_time


def test_usdm_mark_funding_and_open_interest_have_explicit_units(project_root: Path) -> None:
    mark = normalize_mark_index(
        fixture(project_root, "usdm/mark_index.json"),
        symbol="BTCUSDT",
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="usdm_mark_index",
    )
    funding = normalize_funding_rate(
        fixture(project_root, "usdm/funding.json"),
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="usdm_funding",
    )
    oi = normalize_open_interest(
        fixture(project_root, "usdm/open_interest.json"),
        symbol="BTCUSDT",
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="usdm_open_interest",
    )
    assert mark.index_price == Decimal("100.45")
    assert funding.is_final is True
    assert oi.unit == "BASE_ASSET"
    assert oi.open_interest_value is None
    assert all(to_silver_table((record,)).num_rows == 1 for record in (mark, funding, oi))
