"""Shared P13 runtime contracts with explicit time, units, and safety modes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.data.hashing import ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import (
    ClientOrderId,
    IdempotencyKey,
    InstrumentId,
    RiskDecisionId,
    StrategyId,
    VenueId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    Money,
    NonNegativeDecimal,
    Price,
    Quantity,
    UnitInterval,
)


class RuntimeMode(StrEnum):
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    PAPER = "PAPER"
    SHADOW = "SHADOW"


class RuntimeState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    QUIESCED = "QUIESCED"
    HALTED = "HALTED"


class FaultKind(StrEnum):
    NETWORK = "NETWORK"
    DATABASE = "DATABASE"
    MODEL = "MODEL"
    DATA_SOURCE = "DATA_SOURCE"
    CLOCK = "CLOCK"
    PROCESS = "PROCESS"


class AlertSeverity(StrEnum):
    SEV0 = "SEV0"
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    INFO = "INFO"


class MarketObservation(DomainModel):
    event_id: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1, max_length=128)
    source_sha256: str
    instrument_id: InstrumentId
    venue_id: VenueId
    sequence: int = Field(ge=1)
    event_time: UtcDateTime
    available_at: UtcDateTime
    received_at: UtcDateTime
    bid_price: Price
    bid_quantity: Quantity
    ask_price: Price
    ask_quantity: Quantity
    last_price: Price

    @model_validator(mode="after")
    def validate_observation(self) -> MarketObservation:
        ensure_sha256(self.source_sha256, field_name="source_sha256")
        if not self.event_time <= self.available_at <= self.received_at:
            raise ValueError("market observation times must be monotonic")
        prices = (self.bid_price, self.ask_price, self.last_price)
        units = {(item.base_asset_id, item.quote_asset_id) for item in prices}
        if len(units) != 1:
            raise ValueError("market observation prices must share units")
        if self.bid_price.amount > self.ask_price.amount:
            raise ValueError("market observation book is crossed")
        base_asset = self.bid_price.base_asset_id
        if self.bid_quantity.asset_id != base_asset or self.ask_quantity.asset_id != base_asset:
            raise ValueError("market observation book quantities must use the base asset")
        if self.bid_quantity.amount < 0 or self.ask_quantity.amount < 0:
            raise ValueError("market observation quantities cannot be negative")
        return self


class PredictionTrace(DomainModel):
    prediction_id: str = Field(min_length=1, max_length=255)
    strategy_id: StrategyId
    model_version_id: str = Field(min_length=1, max_length=128)
    risk_decision_id: RiskDecisionId
    instrument_id: InstrumentId
    side: OrderSide
    predicted_return: FiniteDecimal
    confidence: UnitInterval
    target_quantity: Quantity
    expected_price: Price
    generated_at: UtcDateTime
    valid_until: UtcDateTime
    source_event_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_prediction(self) -> PredictionTrace:
        if self.valid_until <= self.generated_at:
            raise ValueError("prediction trace must expire after generation")
        if self.target_quantity.amount <= 0:
            raise ValueError("prediction target quantity must be positive")
        if len(set(self.source_event_ids)) != len(self.source_event_ids):
            raise ValueError("prediction source events must be unique")
        return self


class ModeExecutionTrace(DomainModel):
    mode: RuntimeMode
    trace_id: str = Field(min_length=1, max_length=255)
    prediction_id: str = Field(min_length=1, max_length=255)
    strategy_id: StrategyId
    model_version_id: str = Field(min_length=1, max_length=128)
    risk_decision_id: RiskDecisionId
    instrument_id: InstrumentId
    client_order_id: ClientOrderId
    economic_idempotency_key: IdempotencyKey
    command_sha256: str
    side: OrderSide
    target_quantity: Quantity
    requested_quantity: Quantity
    expected_price: Price
    executable_price: Price | None
    fill_price: Price | None
    filled_quantity: Quantity
    fee: Money
    decision_time: UtcDateTime
    market_available_at: UtcDateTime
    status: str = Field(min_length=1, max_length=64)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    hypothetical: bool
    write_attempted: bool = False

    @model_validator(mode="after")
    def validate_trace(self) -> ModeExecutionTrace:
        ensure_sha256(self.command_sha256, field_name="command_sha256")
        if self.market_available_at < self.decision_time:
            raise ValueError("trace cannot use market data available before its decision")
        if self.target_quantity.amount <= 0 or self.requested_quantity.amount <= 0:
            raise ValueError("trace target and requested quantities must be positive")
        quantities = (self.target_quantity, self.requested_quantity, self.filled_quantity)
        if len({item.asset_id for item in quantities}) != 1:
            raise ValueError("trace quantities must share one asset")
        if self.filled_quantity.amount < 0:
            raise ValueError("trace filled quantity cannot be negative")
        if self.filled_quantity.amount > self.requested_quantity.amount:
            raise ValueError("trace cannot overfill the requested quantity")
        prices = tuple(
            item
            for item in (self.expected_price, self.executable_price, self.fill_price)
            if item is not None
        )
        if len({(item.base_asset_id, item.quote_asset_id) for item in prices}) != 1:
            raise ValueError("trace prices must share one base/quote unit")
        if quantities[0].asset_id != prices[0].base_asset_id:
            raise ValueError("trace quantity must use the price base asset")
        if self.fee.asset_id != prices[0].quote_asset_id or self.fee.amount < 0:
            raise ValueError("trace fee must be nonnegative and use the quote asset")
        if self.mode is RuntimeMode.SHADOW:
            if self.fill_price is not None or self.filled_quantity.amount != 0:
                raise ValueError("Shadow trace cannot contain a fill")
            if not self.hypothetical or self.write_attempted:
                raise ValueError("Shadow trace must be hypothetical and read-only")
        if self.write_attempted:
            raise ValueError("P13 runtime cannot attempt a venue write")
        return self


class RuntimeReadModelEvent(DomainModel):
    event_id: str = Field(min_length=1, max_length=255)
    sequence: int = Field(ge=1)
    mode: RuntimeMode
    event_type: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=255)
    occurred_at: UtcDateTime
    available_at: UtcDateTime
    payload_sha256: str
    source_event_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_read_event(self) -> RuntimeReadModelEvent:
        ensure_sha256(self.payload_sha256, field_name="payload_sha256")
        if self.available_at < self.occurred_at:
            raise ValueError("read-model event availability cannot precede occurrence")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("read-model source events must be unique")
        return self


class MarketModeLimitations(DomainModel):
    paper_uses_virtual_fills: bool = True
    shadow_has_write_capability: bool = False
    testnet_pnl_is_strategy_evidence: bool = False
    simulated_liquidity_is_live_capacity_evidence: bool = False
    real_account_access_performed: bool = False
    venue_network_requests_performed: int = Field(default=0, ge=0)
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_limitations(self) -> MarketModeLimitations:
        if not self.paper_uses_virtual_fills:
            raise ValueError("Paper must identify fills as virtual")
        if any(
            (
                self.shadow_has_write_capability,
                self.testnet_pnl_is_strategy_evidence,
                self.simulated_liquidity_is_live_capacity_evidence,
                self.real_account_access_performed,
                self.venue_network_requests_performed > 0,
            )
        ):
            raise ValueError("P13 market-mode limitations cannot claim production evidence")
        return self


class ExecutionErrorPoint(DomainModel):
    trace_id: str
    target_order_gap: FiniteDecimal
    expected_to_executable_bps: FiniteDecimal | None
    executable_to_fill_bps: FiniteDecimal | None
    decision_latency_ms: int = Field(ge=0)
    fill_ratio: UnitInterval
    fee_amount: NonNegativeDecimal
    reason_codes: tuple[str, ...] = Field(min_length=1)
