"""Public-only OKX, Bybit, and Deribit contracts, normalizers, and sequence rules."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from importlib.util import find_spec
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast
from urllib.parse import urlsplit

import httpx
from pydantic import Field, JsonValue, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.data.market import (
    CanonicalAsset,
    CanonicalExposure,
    CanonicalPair,
    ContractForm,
    ImpliedVolatilitySource,
    InstrumentType,
    MarketObservation,
    OptionType,
    UnifiedInstrument,
    Venue,
)
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ProviderId
from aegisquant.domain.time import UtcDateTime, ensure_utc

FORBIDDEN_PARAMETER_NAMES: Final = frozenset(
    {
        "api_key",
        "apikey",
        "api-secret",
        "api_secret",
        "authorization",
        "cookie",
        "passphrase",
        "secret",
        "sign",
        "signature",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class PublicEndpoint:
    capability: str
    base_url: str
    path: str
    allowed_parameters: frozenset[str]
    required_parameters: frozenset[str] = frozenset()
    maximum_limit: int | None = None

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.path}"


@dataclass(frozen=True, slots=True)
class ExchangeContract:
    provider_id: ProviderId
    venue: Venue
    rest: Mapping[str, PublicEndpoint]
    websocket_urls: Mapping[str, str]
    status_url: str
    changelog_url: str
    rate_limits: Mapping[str, int]


def _endpoint(
    capability: str,
    base: str,
    path: str,
    allowed: set[str],
    required: set[str] | None = None,
    maximum_limit: int | None = None,
) -> PublicEndpoint:
    return PublicEndpoint(
        capability=capability,
        base_url=base,
        path=path,
        allowed_parameters=frozenset(allowed),
        required_parameters=frozenset(required or set()),
        maximum_limit=maximum_limit,
    )


EXCHANGE_CONTRACTS: Final = MappingProxyType(
    {
        Venue.OKX: ExchangeContract(
            provider_id=ProviderId("okx_public"),
            venue=Venue.OKX,
            rest=MappingProxyType(
                {
                    "instruments": _endpoint(
                        "instruments",
                        "https://www.okx.com",
                        "/api/v5/public/instruments",
                        {"instType", "uly", "instFamily", "instId"},
                        {"instType"},
                    ),
                    "orderbook": _endpoint(
                        "orderbook",
                        "https://www.okx.com",
                        "/api/v5/market/books",
                        {"instId", "sz"},
                        {"instId"},
                        400,
                    ),
                    "ticker": _endpoint(
                        "ticker",
                        "https://www.okx.com",
                        "/api/v5/market/ticker",
                        {"instId"},
                        {"instId"},
                    ),
                    "funding": _endpoint(
                        "funding",
                        "https://www.okx.com",
                        "/api/v5/public/funding-rate-history",
                        {"instId", "before", "after", "limit"},
                        {"instId"},
                        400,
                    ),
                    "open_interest": _endpoint(
                        "open_interest",
                        "https://www.okx.com",
                        "/api/v5/public/open-interest",
                        {"instType", "uly", "instFamily", "instId"},
                        {"instType"},
                    ),
                    "time": _endpoint("time", "https://www.okx.com", "/api/v5/public/time", set()),
                }
            ),
            websocket_urls=MappingProxyType({"public": "wss://ws.okx.com:8443/ws/v5/public"}),
            status_url="https://www.okx.com/status",
            changelog_url="https://www.okx.com/docs-v5/log_en/",
            rate_limits=MappingProxyType({"rest_requests_per_two_seconds": 20}),
        ),
        Venue.BYBIT: ExchangeContract(
            provider_id=ProviderId("bybit_public"),
            venue=Venue.BYBIT,
            rest=MappingProxyType(
                {
                    "instruments": _endpoint(
                        "instruments",
                        "https://api.bybit.com",
                        "/v5/market/instruments-info",
                        {"category", "symbol", "baseCoin", "limit", "cursor", "status"},
                        {"category"},
                        1000,
                    ),
                    "orderbook": _endpoint(
                        "orderbook",
                        "https://api.bybit.com",
                        "/v5/market/orderbook",
                        {"category", "symbol", "limit"},
                        {"category", "symbol"},
                        1000,
                    ),
                    "ticker": _endpoint(
                        "ticker",
                        "https://api.bybit.com",
                        "/v5/market/tickers",
                        {"category", "symbol", "baseCoin", "expDate"},
                        {"category"},
                    ),
                    "funding": _endpoint(
                        "funding",
                        "https://api.bybit.com",
                        "/v5/market/funding/history",
                        {"category", "symbol", "startTime", "endTime", "limit"},
                        {"category", "symbol"},
                        200,
                    ),
                    "open_interest": _endpoint(
                        "open_interest",
                        "https://api.bybit.com",
                        "/v5/market/open-interest",
                        {
                            "category",
                            "symbol",
                            "intervalTime",
                            "startTime",
                            "endTime",
                            "limit",
                            "cursor",
                        },
                        {"category", "symbol", "intervalTime"},
                        200,
                    ),
                    "time": _endpoint("time", "https://api.bybit.com", "/v5/market/time", set()),
                }
            ),
            websocket_urls=MappingProxyType(
                {
                    "spot": "wss://stream.bybit.com/v5/public/spot",
                    "linear": "wss://stream.bybit.com/v5/public/linear",
                    "inverse": "wss://stream.bybit.com/v5/public/inverse",
                    "option": "wss://stream.bybit.com/v5/public/option",
                }
            ),
            status_url="https://status.bybit.com/",
            changelog_url="https://bybit-exchange.github.io/docs/changelog/v5",
            rate_limits=MappingProxyType({"default_http_requests_per_second": 10}),
        ),
        Venue.DERIBIT: ExchangeContract(
            provider_id=ProviderId("deribit_public"),
            venue=Venue.DERIBIT,
            rest=MappingProxyType(
                {
                    "instruments": _endpoint(
                        "instruments",
                        "https://www.deribit.com",
                        "/api/v2/public/get_instruments",
                        {"currency", "kind", "expired"},
                        {"currency"},
                    ),
                    "orderbook": _endpoint(
                        "orderbook",
                        "https://www.deribit.com",
                        "/api/v2/public/get_order_book",
                        {"instrument_name", "depth"},
                        {"instrument_name"},
                        10000,
                    ),
                    "ticker": _endpoint(
                        "ticker",
                        "https://www.deribit.com",
                        "/api/v2/public/ticker",
                        {"instrument_name"},
                        {"instrument_name"},
                    ),
                    "funding": _endpoint(
                        "funding",
                        "https://www.deribit.com",
                        "/api/v2/public/get_funding_rate_history",
                        {"instrument_name", "start_timestamp", "end_timestamp"},
                        {"instrument_name", "start_timestamp", "end_timestamp"},
                    ),
                    "open_interest": _endpoint(
                        "open_interest",
                        "https://www.deribit.com",
                        "/api/v2/public/get_book_summary_by_instrument",
                        {"instrument_name"},
                        {"instrument_name"},
                    ),
                    "time": _endpoint(
                        "time", "https://www.deribit.com", "/api/v2/public/get_time", set()
                    ),
                }
            ),
            websocket_urls=MappingProxyType({"public": "wss://www.deribit.com/ws/api/v2"}),
            status_url="https://status.deribit.com/",
            changelog_url="https://docs.deribit.com/",
            rate_limits=MappingProxyType({"default_credits_per_second": 20}),
        ),
    }
)


class PublicRequest(DomainModel):
    provider_id: ProviderId
    venue: Venue
    capability: str
    method: str = "GET"
    url: str
    parameters: dict[str, str | int | bool]
    authentication_used: bool = False
    request_hash: str


class WsSubscription(DomainModel):
    provider_id: ProviderId
    venue: Venue
    url: str
    channel: str
    payload: dict[str, JsonValue]
    snapshot_required: bool = True
    authentication_used: bool = False


def assert_public_url(venue: Venue, url: str, *, websocket: bool = False) -> None:
    contract = EXCHANGE_CONTRACTS[venue]
    parsed = urlsplit(url)
    allowed_hosts = {urlsplit(endpoint.url).hostname for endpoint in contract.rest.values()} | {
        urlsplit(item).hostname for item in contract.websocket_urls.values()
    }
    expected_scheme = "wss" if websocket else "https"
    if (
        parsed.scheme != expected_scheme
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"AQ-{venue.value}-PUBLIC-URL-DENIED")
    folded = f"{parsed.path}?{parsed.query}".casefold()
    if any(
        token in folded
        for token in ("/private/", "private_", "/order", "/account", "api_key", "signature")
    ):
        raise ValueError(f"AQ-{venue.value}-PRIVATE-ROUTE")


def build_public_request(
    venue: Venue, capability: str, parameters: Mapping[str, str | int | bool] | None = None
) -> PublicRequest:
    contract = EXCHANGE_CONTRACTS[venue]
    endpoint = contract.rest.get(capability)
    if endpoint is None:
        raise ValueError(f"AQ-{venue.value}-CAPABILITY-NOT-ALLOWLISTED")
    normalized = dict(parameters or {})
    folded = {key.casefold() for key in normalized}
    if folded & FORBIDDEN_PARAMETER_NAMES:
        raise ValueError(f"AQ-{venue.value}-PRIVATE-PARAMETER")
    unknown = sorted(set(normalized) - endpoint.allowed_parameters)
    missing = sorted(endpoint.required_parameters - set(normalized))
    if unknown or missing:
        raise ValueError(f"AQ-{venue.value}-PARAMETERS: unknown={unknown}, missing={missing}")
    limit = normalized.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if endpoint.maximum_limit is not None and limit > endpoint.maximum_limit:
            raise ValueError(f"limit exceeds {venue.value} {capability} maximum")
    assert_public_url(venue, endpoint.url)
    identity = canonical_sha256(
        {"method": "GET", "url": endpoint.url, "parameters": normalized, "auth": False}
    )
    return PublicRequest(
        provider_id=contract.provider_id,
        venue=venue,
        capability=capability,
        url=endpoint.url,
        parameters=normalized,
        request_hash=identity,
    )


def build_orderbook_subscription(
    venue: Venue, symbol: str, *, product: str = "public", depth: int = 50
) -> WsSubscription:
    if not symbol or depth < 1:
        raise ValueError("symbol and positive depth are required")
    contract = EXCHANGE_CONTRACTS[venue]
    if venue is Venue.OKX:
        url = contract.websocket_urls["public"]
        channel = "books"
        payload: dict[str, JsonValue] = {
            "op": "subscribe",
            "args": [{"channel": channel, "instId": symbol}],
        }
    elif venue is Venue.BYBIT:
        if product not in contract.websocket_urls:
            raise ValueError("unsupported Bybit public product channel")
        url = contract.websocket_urls[product]
        channel = f"orderbook.{depth}.{symbol}"
        payload = {"op": "subscribe", "args": [channel]}
    elif venue is Venue.DERIBIT:
        url = contract.websocket_urls["public"]
        channel = f"book.{symbol}.raw"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "public/subscribe",
            "params": {"channels": [channel]},
        }
    else:
        raise ValueError("venue has no P04 public subscription contract")
    assert_public_url(venue, url, websocket=True)
    return WsSubscription(
        provider_id=contract.provider_id,
        venue=venue,
        url=url,
        channel=channel,
        payload=payload,
    )


class SequenceDisposition(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    GAP = "GAP"


class SequenceResult(DomainModel):
    disposition: SequenceDisposition
    watermark: int | None
    recovery_required: bool
    reason_code: str


class BookUpdate(DomainModel):
    venue: Venue
    symbol: str
    action: str
    sequence: int = Field(ge=0)
    previous_sequence: int | None = None
    cross_sequence: int | None = Field(default=None, ge=0)
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

    @model_validator(mode="after")
    def validate_levels(self) -> BookUpdate:
        if any(price <= 0 or quantity < 0 for price, quantity in self.bids + self.asks):
            raise ValueError("book prices must be positive and quantities non-negative")
        return self


@dataclass(slots=True)
class PublicSequenceTracker:
    venue: Venue
    watermark: int | None = None
    recovery_required: bool = False

    def apply(
        self, *, action: str, sequence: int, previous_sequence: int | None = None
    ) -> SequenceResult:
        if sequence < 0:
            raise ValueError("sequence cannot be negative")
        normalized_action = action.casefold()
        restart = self.venue is Venue.BYBIT and sequence == 1
        if normalized_action == "snapshot" or restart:
            self.watermark = sequence
            self.recovery_required = False
            return SequenceResult(
                disposition=SequenceDisposition.SNAPSHOT,
                watermark=sequence,
                recovery_required=False,
                reason_code=f"AQ-{self.venue.value}-SEQUENCE-SNAPSHOT",
            )
        if self.watermark is None or self.recovery_required:
            self.recovery_required = True
            return self._gap("SNAPSHOT-REQUIRED")
        if sequence <= self.watermark:
            return SequenceResult(
                disposition=SequenceDisposition.DUPLICATE,
                watermark=self.watermark,
                recovery_required=False,
                reason_code=f"AQ-{self.venue.value}-SEQUENCE-DUPLICATE",
            )
        if self.venue in {Venue.OKX, Venue.DERIBIT}:
            continuous = previous_sequence == self.watermark
        elif self.venue is Venue.BYBIT:
            continuous = sequence == self.watermark + 1
        else:
            raise ValueError("venue has no P04 sequence rule")
        if not continuous:
            self.recovery_required = True
            return self._gap("GAP")
        self.watermark = sequence
        return SequenceResult(
            disposition=SequenceDisposition.APPLIED,
            watermark=sequence,
            recovery_required=False,
            reason_code=f"AQ-{self.venue.value}-SEQUENCE-APPLIED",
        )

    def _gap(self, reason: str) -> SequenceResult:
        return SequenceResult(
            disposition=SequenceDisposition.GAP,
            watermark=self.watermark,
            recovery_required=True,
            reason_code=f"AQ-{self.venue.value}-SEQUENCE-{reason}",
        )


def _empty_book_side() -> dict[Decimal, Decimal]:
    return {}


@dataclass(slots=True)
class PublicOrderBook:
    venue: Venue
    symbol: str
    sequence: PublicSequenceTracker = field(init=False)
    bids: dict[Decimal, Decimal] = field(default_factory=_empty_book_side)
    asks: dict[Decimal, Decimal] = field(default_factory=_empty_book_side)

    def __post_init__(self) -> None:
        self.sequence = PublicSequenceTracker(self.venue)

    def apply(self, update: BookUpdate) -> SequenceResult:
        if update.venue is not self.venue or update.symbol != self.symbol:
            raise ValueError("book update does not match local state")
        previous_watermark = self.sequence.watermark
        previous_bids = dict(self.bids)
        previous_asks = dict(self.asks)
        result = self.sequence.apply(
            action=update.action,
            sequence=update.sequence,
            previous_sequence=update.previous_sequence,
        )
        if result.disposition not in {SequenceDisposition.SNAPSHOT, SequenceDisposition.APPLIED}:
            return result
        if result.disposition is SequenceDisposition.SNAPSHOT:
            self.bids.clear()
            self.asks.clear()
        self._apply_levels(self.bids, update.bids)
        self._apply_levels(self.asks, update.asks)
        if self.bids and self.asks and max(self.bids) > min(self.asks):
            self.bids = previous_bids
            self.asks = previous_asks
            self.sequence.watermark = previous_watermark
            self.sequence.recovery_required = True
            return SequenceResult(
                disposition=SequenceDisposition.GAP,
                watermark=previous_watermark,
                recovery_required=True,
                reason_code=f"AQ-{self.venue.value}-ORDERBOOK-CROSSED",
            )
        return result

    def best_bid_ask(self) -> tuple[tuple[Decimal, Decimal], tuple[Decimal, Decimal]]:
        if not self.bids or not self.asks:
            raise ValueError("order book has no two-sided quote")
        bid = max(self.bids)
        ask = min(self.asks)
        return (bid, self.bids[bid]), (ask, self.asks[ask])

    @staticmethod
    def _apply_levels(
        side: dict[Decimal, Decimal], levels: tuple[tuple[Decimal, Decimal], ...]
    ) -> None:
        for price, quantity in levels:
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity


class ChangelogSnapshot(DomainModel):
    venue: Venue
    url: str
    checked_at: UtcDateTime
    content_sha256: str = Field(min_length=64, max_length=64)
    content_bytes: int = Field(ge=1)
    previous_sha256: str | None = None
    changed: bool

    @field_validator("content_sha256", "previous_sha256")
    @classmethod
    def validate_hash(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name=str(getattr(info, "field_name", "hash")))


def snapshot_changelog(
    venue: Venue, content: bytes, *, checked_at: datetime, previous_sha256: str | None = None
) -> ChangelogSnapshot:
    if not content:
        raise ValueError("changelog content cannot be empty")
    digest = hashlib.sha256(content).hexdigest()
    return ChangelogSnapshot(
        venue=venue,
        url=EXCHANGE_CONTRACTS[venue].changelog_url,
        checked_at=ensure_utc(checked_at),
        content_sha256=digest,
        content_bytes=len(content),
        previous_sha256=previous_sha256,
        changed=previous_sha256 is not None and previous_sha256 != digest,
    )


def write_changelog_snapshot(path: Path, snapshot: ChangelogSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("xb") as output:
        output.write(snapshot.model_dump_json(indent=2).encode("utf-8") + b"\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def load_changelog_snapshot(path: Path) -> ChangelogSnapshot | None:
    if not path.is_file():
        return None
    return ChangelogSnapshot.model_validate_json(path.read_bytes())


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{field_name} keys must be strings")
    return {cast(str, key): item for key, item in raw.items()}


def _items(value: object, field_name: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return tuple(_mapping(item, field_name) for item in cast(list[object], value))


def _text(value: object, field_name: str, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise ValueError(f"{field_name} must be a string")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    raise ValueError(f"{field_name} must be an integer")


def _decimal(value: object, field_name: str, *, default: str | None = None) -> Decimal:
    if value in {None, ""} and default is not None:
        value = default
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be decimal-compatible")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _milliseconds(value: object, field_name: str) -> datetime | None:
    if value in {None, "", "0", 0}:
        return None
    milliseconds = _decimal(value, field_name)
    return datetime.fromtimestamp(float(milliseconds / Decimal(1000)), tz=UTC)


def _level_rows(
    value: object, field_name: str, *, action_column: bool = False
) -> tuple[tuple[Decimal, Decimal], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    levels: list[tuple[Decimal, Decimal]] = []
    for raw in cast(list[object], value):
        if not isinstance(raw, list):
            raise ValueError(f"{field_name} level must be a list")
        row = cast(list[object], raw)
        offset = 1 if action_column else 0
        if len(row) < offset + 2:
            raise ValueError(f"{field_name} level is incomplete")
        price = _decimal(row[offset], f"{field_name}.price")
        quantity = _decimal(row[offset + 1], f"{field_name}.quantity")
        if action_column and str(row[0]).casefold() == "delete":
            quantity = Decimal(0)
        levels.append((price, quantity))
    return tuple(levels)


def parse_orderbook_update(
    venue: Venue, payload: Mapping[str, object], *, symbol: str
) -> BookUpdate:
    if venue is Venue.OKX:
        data = _first_record(payload.get("data"), "data")
        return BookUpdate(
            venue=venue,
            symbol=symbol,
            action=_text(payload.get("action"), "action"),
            sequence=_integer(data.get("seqId"), "seqId"),
            previous_sequence=_integer(data.get("prevSeqId"), "prevSeqId"),
            bids=_level_rows(data.get("bids"), "bids"),
            asks=_level_rows(data.get("asks"), "asks"),
        )
    if venue is Venue.BYBIT:
        data = _mapping(payload.get("data"), "data")
        return BookUpdate(
            venue=venue,
            symbol=symbol,
            action=_text(payload.get("type"), "type"),
            sequence=_integer(data.get("u"), "u"),
            cross_sequence=_integer(data.get("seq"), "seq"),
            bids=_level_rows(data.get("b"), "bids"),
            asks=_level_rows(data.get("a"), "asks"),
        )
    if venue is Venue.DERIBIT:
        params = _mapping(payload.get("params") or {}, "params")
        data = _mapping(params.get("data") or payload.get("result"), "data")
        action = _text(data.get("type") or "snapshot", "type")
        previous = data.get("prev_change_id")
        return BookUpdate(
            venue=venue,
            symbol=symbol,
            action=action,
            sequence=_integer(data.get("change_id"), "change_id"),
            previous_sequence=(
                _integer(previous, "prev_change_id") if previous is not None else None
            ),
            bids=_level_rows(
                data.get("bids"), "bids", action_column=action.casefold() != "snapshot"
            ),
            asks=_level_rows(
                data.get("asks"), "asks", action_column=action.casefold() != "snapshot"
            ),
        )
    raise ValueError("venue has no P04 orderbook parser")


def _first_record(value: object, field_name: str) -> dict[str, object]:
    if isinstance(value, list):
        rows = _items(cast(object, value), field_name)
        if not rows:
            raise ValueError(f"{field_name} cannot be empty")
        return rows[0]
    return _mapping(value, field_name)


def normalize_market_observation(
    venue: Venue,
    *,
    instrument: UnifiedInstrument,
    ticker_payload: Mapping[str, object],
    event_time: datetime,
    available_time: datetime,
    ingest_time: datetime,
    quality_score: Decimal,
    funding_payload: Mapping[str, object] | None = None,
    open_interest_payload: Mapping[str, object] | None = None,
    event_key: str | None = None,
) -> MarketObservation:
    if instrument.venue is not venue:
        raise ValueError("ticker venue does not match instrument")
    funding: Decimal | None = None
    open_interest: Decimal | None = None
    if venue is Venue.OKX:
        ticker = _first_record(ticker_payload.get("data"), "ticker.data")
        bid = _decimal(ticker.get("bidPx"), "bidPx")
        ask = _decimal(ticker.get("askPx"), "askPx")
        mark = _decimal(ticker.get("last"), "last")
        index = None
        bid_size = _decimal(ticker.get("bidSz"), "bidSz", default="0")
        ask_size = _decimal(ticker.get("askSz"), "askSz", default="0")
        if funding_payload is not None:
            funding_record = _first_record(funding_payload.get("data"), "funding.data")
            funding = _decimal(funding_record.get("fundingRate"), "fundingRate")
        if open_interest_payload is not None:
            oi_record = _first_record(open_interest_payload.get("data"), "oi.data")
            open_interest = _decimal(oi_record.get("oiCcy") or oi_record.get("oi"), "openInterest")
    elif venue is Venue.BYBIT:
        result = _mapping(ticker_payload.get("result"), "ticker.result")
        ticker = _first_record(result.get("list"), "ticker.result.list")
        bid = _decimal(ticker.get("bid1Price"), "bid1Price")
        ask = _decimal(ticker.get("ask1Price"), "ask1Price")
        mark = _decimal(ticker.get("markPrice"), "markPrice")
        index = _decimal(ticker.get("indexPrice"), "indexPrice")
        bid_size = _decimal(ticker.get("bid1Size"), "bid1Size", default="0")
        ask_size = _decimal(ticker.get("ask1Size"), "ask1Size", default="0")
        if ticker.get("fundingRate") not in {None, ""}:
            funding = _decimal(ticker.get("fundingRate"), "fundingRate")
        if ticker.get("openInterest") not in {None, ""}:
            open_interest = _decimal(ticker.get("openInterest"), "openInterest")
    elif venue is Venue.DERIBIT:
        ticker = _mapping(ticker_payload.get("result"), "ticker.result")
        bid = _decimal(ticker.get("best_bid_price"), "best_bid_price")
        ask = _decimal(ticker.get("best_ask_price"), "best_ask_price")
        mark = _decimal(ticker.get("mark_price"), "mark_price")
        index = _decimal(ticker.get("index_price"), "index_price")
        bid_size = _decimal(ticker.get("best_bid_amount"), "best_bid_amount", default="0")
        ask_size = _decimal(ticker.get("best_ask_amount"), "best_ask_amount", default="0")
        if ticker.get("current_funding") not in {None, ""}:
            funding = _decimal(ticker.get("current_funding"), "current_funding")
        if ticker.get("open_interest") not in {None, ""}:
            open_interest = _decimal(ticker.get("open_interest"), "open_interest")
    else:
        raise ValueError("venue has no P04 ticker normalizer")
    return MarketObservation(
        provider_id=instrument.provider_id,
        venue=venue,
        instrument_id=instrument.instrument_id,
        exposure_id=instrument.exposure.exposure_id,
        quote_asset_id=instrument.quote_asset.asset_id,
        event_time=ensure_utc(event_time),
        available_time=ensure_utc(available_time),
        ingest_time=ensure_utc(ingest_time),
        bid=bid,
        ask=ask,
        mark=mark,
        index=index,
        funding_rate=funding,
        open_interest=open_interest,
        liquidity_notional=bid * bid_size + ask * ask_size,
        quality_score=quality_score,
        event_key=event_key,
    )


def _assets(
    base_symbol: str, quote_symbol: str, settlement_symbol: str
) -> tuple[CanonicalAsset, CanonicalAsset, CanonicalAsset, CanonicalPair]:
    base = CanonicalAsset.create(base_symbol)
    quote = CanonicalAsset.create(quote_symbol)
    settlement = CanonicalAsset.create(settlement_symbol)
    return base, quote, settlement, CanonicalPair.create(base, quote)


def normalize_okx_instruments(
    payload: Mapping[str, object], *, observed_time: datetime, available_time: datetime
) -> tuple[UnifiedInstrument, ...]:
    instruments: list[UnifiedInstrument] = []
    for raw in _items(payload.get("data"), "data"):
        inst_type_raw = _text(raw.get("instType"), "instType").upper()
        type_map = {
            "SPOT": InstrumentType.SPOT,
            "SWAP": InstrumentType.PERPETUAL,
            "FUTURES": InstrumentType.FUTURE,
            "OPTION": InstrumentType.OPTION,
        }
        instrument_type = type_map.get(inst_type_raw)
        if instrument_type is None:
            raise ValueError(f"unsupported OKX instrument type: {inst_type_raw}")
        symbol = _text(raw.get("instId"), "instId")
        family_parts = _text(raw.get("instFamily") or raw.get("uly") or symbol, "instFamily").split(
            "-"
        )
        base_symbol = _text(raw.get("baseCcy") or family_parts[0], "baseCcy")
        quote_symbol = _text(
            raw.get("quoteCcy") or (family_parts[1] if len(family_parts) > 1 else "USD"),
            "quoteCcy",
        )
        settlement_symbol = _text(raw.get("settleCcy") or quote_symbol, "settleCcy")
        base, quote, settlement, pair = _assets(base_symbol, quote_symbol, settlement_symbol)
        if instrument_type is InstrumentType.SPOT:
            form = ContractForm.SPOT
        else:
            form = (
                ContractForm.INVERSE
                if _text(raw.get("ctType") or "linear", "ctType").casefold() == "inverse"
                else ContractForm.LINEAR
            )
        option_type = None
        raw_option = _text(raw.get("optType") or "", "optType", allow_blank=True).upper()
        if raw_option:
            option_type = OptionType.CALL if raw_option in {"C", "CALL"} else OptionType.PUT
        expiry = _milliseconds(raw.get("expTime"), "expTime")
        strike = None
        if raw.get("stk") not in {None, ""}:
            strike = _decimal(raw.get("stk"), "stk")
        exposure = CanonicalExposure.create(
            pair,
            settlement,
            instrument_type=instrument_type,
            contract_form=form,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
        )
        instruments.append(
            UnifiedInstrument.create(
                provider_id=ProviderId("okx_public"),
                venue=Venue.OKX,
                venue_symbol=symbol,
                exposure=exposure,
                base_asset=base,
                quote_asset=quote,
                settlement_asset=settlement,
                contract_multiplier=_decimal(raw.get("ctVal"), "ctVal", default="1"),
                tick_size=_decimal(raw.get("tickSz"), "tickSz"),
                lot_size=_decimal(raw.get("lotSz"), "lotSz"),
                active=_text(raw.get("state"), "state").casefold() == "live",
                observed_time=observed_time,
                available_time=available_time,
                iv_source=(
                    ImpliedVolatilitySource.VENUE_MARK_TICKER
                    if instrument_type is InstrumentType.OPTION
                    else ImpliedVolatilitySource.NOT_APPLICABLE
                ),
            )
        )
    return tuple(instruments)


def normalize_bybit_instruments(
    payload: Mapping[str, object], *, observed_time: datetime, available_time: datetime
) -> tuple[UnifiedInstrument, ...]:
    result = _mapping(payload.get("result"), "result")
    category = _text(result.get("category"), "category").casefold()
    instruments: list[UnifiedInstrument] = []
    for raw in _items(result.get("list"), "result.list"):
        contract_type = _text(raw.get("contractType") or "Spot", "contractType")
        if category == "spot":
            instrument_type = InstrumentType.SPOT
            form = ContractForm.SPOT
        elif category == "option":
            instrument_type = InstrumentType.OPTION
            form = ContractForm.LINEAR
        elif "perpetual" in contract_type.casefold():
            instrument_type = InstrumentType.PERPETUAL
            form = ContractForm.INVERSE if category == "inverse" else ContractForm.LINEAR
        else:
            instrument_type = InstrumentType.FUTURE
            form = ContractForm.INVERSE if category == "inverse" else ContractForm.LINEAR
        base, quote, settlement, pair = _assets(
            _text(raw.get("baseCoin"), "baseCoin"),
            _text(raw.get("quoteCoin"), "quoteCoin"),
            _text(raw.get("settleCoin") or raw.get("quoteCoin"), "settleCoin"),
        )
        option_type = None
        raw_option = raw.get("optionsType")
        if raw_option:
            option_type = (
                OptionType.CALL
                if _text(raw_option, "optionsType").casefold() == "call"
                else OptionType.PUT
            )
        expiry = _milliseconds(raw.get("deliveryTime"), "deliveryTime")
        strike = None
        if raw.get("strike") not in {None, ""}:
            strike = _decimal(raw.get("strike"), "strike")
        if instrument_type is InstrumentType.OPTION and strike is None:
            symbol_parts = _text(raw.get("symbol"), "symbol").split("-")
            if len(symbol_parts) >= 4:
                strike = _decimal(symbol_parts[-2], "symbol strike")
        exposure = CanonicalExposure.create(
            pair,
            settlement,
            instrument_type=instrument_type,
            contract_form=form,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
        )
        price_filter = _mapping(raw.get("priceFilter"), "priceFilter")
        lot_filter = _mapping(raw.get("lotSizeFilter"), "lotSizeFilter")
        instruments.append(
            UnifiedInstrument.create(
                provider_id=ProviderId("bybit_public"),
                venue=Venue.BYBIT,
                venue_symbol=_text(raw.get("symbol"), "symbol"),
                exposure=exposure,
                base_asset=base,
                quote_asset=quote,
                settlement_asset=settlement,
                contract_multiplier=_decimal(raw.get("contractSize"), "contractSize", default="1"),
                tick_size=_decimal(price_filter.get("tickSize"), "tickSize"),
                lot_size=_decimal(
                    lot_filter.get("qtyStep") or lot_filter.get("minOrderQty"), "qtyStep"
                ),
                active=_text(raw.get("status"), "status").casefold() == "trading",
                observed_time=observed_time,
                available_time=available_time,
                iv_source=(
                    ImpliedVolatilitySource.VENUE_MARK_TICKER
                    if instrument_type is InstrumentType.OPTION
                    else ImpliedVolatilitySource.NOT_APPLICABLE
                ),
            )
        )
    return tuple(instruments)


def normalize_deribit_instruments(
    payload: Mapping[str, object], *, observed_time: datetime, available_time: datetime
) -> tuple[UnifiedInstrument, ...]:
    instruments: list[UnifiedInstrument] = []
    for raw in _items(payload.get("result"), "result"):
        symbol = _text(raw.get("instrument_name"), "instrument_name")
        kind = _text(raw.get("kind"), "kind").casefold()
        if kind == "option":
            instrument_type = InstrumentType.OPTION
        elif symbol.endswith("PERPETUAL"):
            instrument_type = InstrumentType.PERPETUAL
        else:
            instrument_type = InstrumentType.FUTURE
        form = (
            ContractForm.INVERSE
            if _text(raw.get("instrument_type") or "linear", "instrument_type").casefold()
            in {"reversed", "inverse"}
            else ContractForm.LINEAR
        )
        base, quote, settlement, pair = _assets(
            _text(raw.get("base_currency"), "base_currency"),
            _text(raw.get("quote_currency"), "quote_currency"),
            _text(raw.get("settlement_currency"), "settlement_currency"),
        )
        expiry = (
            None
            if instrument_type is InstrumentType.PERPETUAL
            else _milliseconds(raw.get("expiration_timestamp"), "expiration_timestamp")
        )
        option_type = None
        strike = None
        if instrument_type is InstrumentType.OPTION:
            option_type = (
                OptionType.CALL
                if _text(raw.get("option_type"), "option_type").casefold() == "call"
                else OptionType.PUT
            )
            strike = _decimal(raw.get("strike"), "strike")
        exposure = CanonicalExposure.create(
            pair,
            settlement,
            instrument_type=instrument_type,
            contract_form=form,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
        )
        instruments.append(
            UnifiedInstrument.create(
                provider_id=ProviderId("deribit_public"),
                venue=Venue.DERIBIT,
                venue_symbol=symbol,
                exposure=exposure,
                base_asset=base,
                quote_asset=quote,
                settlement_asset=settlement,
                contract_multiplier=_decimal(raw.get("contract_size"), "contract_size"),
                tick_size=_decimal(raw.get("tick_size"), "tick_size"),
                lot_size=_decimal(raw.get("min_trade_amount"), "min_trade_amount"),
                active=bool(raw.get("is_active")),
                observed_time=observed_time,
                available_time=available_time,
                iv_source=(
                    ImpliedVolatilitySource.VENUE_MARK_TICKER
                    if instrument_type is InstrumentType.OPTION
                    else ImpliedVolatilitySource.NOT_APPLICABLE
                ),
            )
        )
    return tuple(instruments)


NORMALIZERS: Final = {
    Venue.OKX: normalize_okx_instruments,
    Venue.BYBIT: normalize_bybit_instruments,
    Venue.DERIBIT: normalize_deribit_instruments,
}

NAUTILUS_ADAPTER_MODULES: Final = MappingProxyType(
    {
        Venue.OKX: "nautilus_trader.adapters.okx",
        Venue.BYBIT: "nautilus_trader.adapters.bybit",
        Venue.DERIBIT: "nautilus_trader.adapters.deribit",
    }
)


def nautilus_adapter_compatibility() -> dict[str, dict[str, str | bool]]:
    """Report optional Nautilus adapters while keeping the native path always available."""
    return {
        venue.value: {
            "module": module,
            "available": find_spec(module) is not None,
            "native_fallback": "aegisquant.data.providers.public.PublicExchangeAdapter",
        }
        for venue, module in NAUTILUS_ADAPTER_MODULES.items()
    }


@dataclass(slots=True)
class PublicExchangeAdapter:
    """A real public REST adapter with injected HTTP transport and local sequence state."""

    venue: Venue
    client: httpx.Client
    sequence: PublicSequenceTracker = field(init=False)

    def __post_init__(self) -> None:
        if self.venue not in NORMALIZERS:
            raise ValueError("P04 adapter supports OKX, Bybit, and Deribit")
        self.sequence = PublicSequenceTracker(self.venue)

    def _require_unsigned_transport(self) -> None:
        forbidden_headers = {"authorization", "cookie", "x-api-key", "ok-access-key"}
        if any(name.casefold() in forbidden_headers for name in self.client.headers):
            raise ValueError("AQ-PUBLIC-ADAPTER-CREDENTIALLED-CLIENT-DENIED")
        if len(self.client.cookies) > 0:
            raise ValueError("AQ-PUBLIC-ADAPTER-COOKIE-DENIED")

    def fetch_json(
        self, capability: str, parameters: Mapping[str, str | int | bool] | None = None
    ) -> dict[str, object]:
        self._require_unsigned_transport()
        request = build_public_request(self.venue, capability, parameters)
        response = self.client.get(request.url, params=request.parameters)
        if response.history:
            raise ValueError("AQ-PUBLIC-ADAPTER-REDIRECT-DENIED")
        response.raise_for_status()
        return _mapping(cast(object, response.json()), "response")

    def fetch_instruments(
        self,
        parameters: Mapping[str, str | int | bool],
        *,
        observed_time: datetime,
        available_time: datetime,
    ) -> tuple[UnifiedInstrument, ...]:
        payload = self.fetch_json("instruments", parameters)
        normalizer = NORMALIZERS[self.venue]
        return normalizer(
            payload,
            observed_time=ensure_utc(observed_time),
            available_time=ensure_utc(available_time),
        )
