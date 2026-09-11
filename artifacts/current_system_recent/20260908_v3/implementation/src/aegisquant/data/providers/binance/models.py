"""Strict Binance public-market raw, Silver, health, and provenance contracts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import ensure_sha256
from aegisquant.data.providers.binance.contracts import Product
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ProviderId
from aegisquant.domain.time import UtcDateTime

BINANCE_PROVIDER_ID = ProviderId("binance_public")


class QualityStatus(StrEnum):
    VALID = "VALID"
    WARNING = "WARNING"
    QUARANTINE = "QUARANTINE"


class PriceBasis(StrEnum):
    TRADE = "TRADE"
    MARK = "MARK"
    INDEX = "INDEX"


class Provenance(DomainModel):
    provider_id: ProviderId = BINANCE_PROVIDER_ID
    source: str
    source_request_hash: str
    raw_sha256: str
    schema_version: str = "1.0.0"

    @field_validator("source_request_hash", "raw_sha256")
    @classmethod
    def validate_hash(cls, value: str, info: object) -> str:
        return ensure_sha256(value, field_name=str(getattr(info, "field_name", "hash")))


class TimedMarketRecord(DomainModel):
    product: Product
    symbol: str
    event_time: UtcDateTime
    available_time: UtcDateTime
    ingest_time: UtcDateTime
    processed_time: UtcDateTime
    revision_time: UtcDateTime | None = None
    quality_status: QualityStatus
    quality_codes: tuple[str, ...] = ()
    provenance: Provenance

    @model_validator(mode="after")
    def validate_time_order(self) -> TimedMarketRecord:
        if not self.event_time <= self.available_time <= self.ingest_time <= self.processed_time:
            raise ValueError(
                "event_time <= available_time <= ingest_time <= processed_time is required"
            )
        if self.revision_time is not None and self.revision_time > self.processed_time:
            raise ValueError("revision_time cannot exceed processed_time")
        return self


class InstrumentSnapshot(TimedMarketRecord):
    instrument_id: str
    base_asset: str
    quote_asset: str
    settlement_asset: str | None
    contract_size: Decimal
    status: str
    tick_size: Decimal
    step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal | None
    min_notional: Decimal
    expiry_time: UtcDateTime | None
    valid_from: UtcDateTime
    valid_to: UtcDateTime | None
    source_snapshot_id: str

    @model_validator(mode="after")
    def validate_instrument(self) -> InstrumentSnapshot:
        if min(self.contract_size, self.tick_size, self.step_size) <= 0:
            raise ValueError("contract size and price/quantity increments must be positive")
        if self.min_quantity < 0 or self.min_notional < 0:
            raise ValueError("minimum order rules cannot be negative")
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError("maximum quantity cannot be below minimum quantity")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("instrument validity interval is reversed")
        return self


class KlineRecord(TimedMarketRecord):
    price_basis: PriceBasis
    interval: str
    open_time: UtcDateTime
    close_time: UtcDateTime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_volume: Decimal
    quote_volume: Decimal
    trade_count: int = Field(ge=0)
    taker_buy_base_volume: Decimal
    taker_buy_quote_volume: Decimal
    is_closed: bool
    trading_day_utc: str

    @model_validator(mode="after")
    def validate_bar(self) -> KlineRecord:
        if self.open_time >= self.close_time:
            raise ValueError("Kline interval must have positive duration")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC bounds")
        if self.low > self.high:
            raise ValueError("Kline low exceeds high")
        if (
            min(
                self.base_volume,
                self.quote_volume,
                self.taker_buy_base_volume,
                self.taker_buy_quote_volume,
            )
            < 0
        ):
            raise ValueError("Kline volumes cannot be negative")
        return self


class TradeRecord(TimedMarketRecord):
    trade_id: int = Field(ge=0)
    aggregate_trade: bool
    first_trade_id: int | None = Field(default=None, ge=0)
    last_trade_id: int | None = Field(default=None, ge=0)
    price: Decimal = Field(gt=Decimal("0"))
    quantity: Decimal = Field(gt=Decimal("0"))
    quote_quantity: Decimal = Field(ge=Decimal("0"))
    buyer_is_maker: bool


class BookTickerRecord(TimedMarketRecord):
    update_id: int | None = Field(default=None, ge=0)
    best_bid_price: Decimal = Field(gt=Decimal("0"))
    best_bid_quantity: Decimal = Field(ge=Decimal("0"))
    best_ask_price: Decimal = Field(gt=Decimal("0"))
    best_ask_quantity: Decimal = Field(ge=Decimal("0"))

    @model_validator(mode="after")
    def validate_spread(self) -> BookTickerRecord:
        if self.best_bid_price > self.best_ask_price:
            raise ValueError("crossed book ticker")
        return self


class DepthDeltaRecord(TimedMarketRecord):
    first_update_id: int = Field(ge=0)
    final_update_id: int = Field(ge=0)
    previous_final_update_id: int | None = Field(default=None, ge=0)
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

    @model_validator(mode="after")
    def validate_sequence(self) -> DepthDeltaRecord:
        if self.first_update_id > self.final_update_id:
            raise ValueError("depth update sequence is reversed")
        if any(price <= 0 or quantity < 0 for price, quantity in self.bids + self.asks):
            raise ValueError("depth prices must be positive and quantities non-negative")
        return self


class MarkIndexRecord(TimedMarketRecord):
    mark_price: Decimal = Field(gt=Decimal("0"))
    index_price: Decimal = Field(gt=Decimal("0"))
    estimated_settle_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    funding_rate: Decimal | None = None
    next_funding_time: UtcDateTime | None = None


class FundingRateRecord(TimedMarketRecord):
    funding_time: UtcDateTime
    funding_rate: Decimal
    mark_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    is_final: bool


class OpenInterestRecord(TimedMarketRecord):
    period: str | None = None
    open_interest: Decimal = Field(ge=Decimal("0"))
    open_interest_value: Decimal | None = Field(default=None, ge=Decimal("0"))
    unit: str


class RawResponseEnvelope(DomainModel):
    endpoint: str
    request_url: str
    request_hash: str
    status_code: int = Field(ge=100, le=599)
    received_at: UtcDateTime
    elapsed_ms: int = Field(ge=0)
    rate_limit_headers: dict[str, str]
    content_sha256: str
    content: bytes

    @field_validator("request_hash", "content_sha256")
    @classmethod
    def validate_response_hash(cls, value: str, info: object) -> str:
        return ensure_sha256(value, field_name=str(getattr(info, "field_name", "hash")))


class ConnectionHealth(DomainModel):
    stream_url: str
    connected_at: UtcDateTime | None
    last_message_at: UtcDateTime | None
    reconnect_count: int = Field(ge=0)
    message_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    late_count: int = Field(ge=0)
    gap_count: int = Field(ge=0)
    forced_rollover_count: int = Field(ge=0)
    status: str


class SoakStreamEvidence(DomainModel):
    product: Product
    stream_url: str
    message_count: int = Field(ge=0)
    applied_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    late_count: int = Field(ge=0)
    sequence_gap_count: int = Field(ge=0)
    recovery_count: int = Field(ge=0)
    snapshot_count: int = Field(ge=0)
    reconnect_count: int = Field(ge=0)
    forced_rollover_count: int = Field(ge=0)
    first_message_at: UtcDateTime | None
    last_message_at: UtcDateTime | None
    maximum_inter_message_ms: int = Field(ge=0)
    hash_chain_sha256: str
    witness_samples: tuple[dict[str, object], ...]

    @field_validator("hash_chain_sha256")
    @classmethod
    def validate_chain_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="hash_chain_sha256")


class SoakEvidence(DomainModel):
    schema_version: str = "1.0.0"
    phase: str = "P03"
    status: str
    qualifying_acceptance: bool
    test_mode: bool
    requested_duration_seconds: int = Field(ge=1)
    actual_monotonic_duration_seconds: float = Field(ge=0)
    actual_wall_duration_seconds: float = Field(ge=0)
    started_at_utc: UtcDateTime
    finished_at_utc: UtcDateTime
    process_id: int = Field(ge=1)
    public_market_data_only: bool = True
    authentication_used: bool = False
    account_access_performed: bool = False
    order_capability_present: bool = False
    live_trading_locked: bool = True
    host_pause_detected: bool
    manual_outage_requested: bool
    manual_outage_recovered: bool
    unexplained_sequence_gap_count: int = Field(ge=0)
    errors: tuple[str, ...]
    streams: tuple[SoakStreamEvidence, ...]

    @model_validator(mode="after")
    def validate_acceptance_claim(self) -> SoakEvidence:
        if self.qualifying_acceptance:
            required = (
                self.status == "passed",
                not self.test_mode,
                self.requested_duration_seconds >= 86_400,
                self.actual_monotonic_duration_seconds >= 86_400,
                not self.host_pause_detected,
                self.manual_outage_recovered,
                self.unexplained_sequence_gap_count == 0,
                not self.errors,
                bool(self.streams),
                all(stream.message_count > 0 for stream in self.streams),
                all(stream.forced_rollover_count > 0 for stream in self.streams),
            )
            if not all(required):
                raise ValueError("qualifying 24-hour acceptance claim is unsupported")
        return self
