"""Independent P11 risk snapshots, events, decisions, and pre-trade requests."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    AccountId,
    AssetId,
    InstrumentId,
    ProposalId,
    RiskDecisionId,
    StrategyId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    Price,
    Quantity,
    UnitInterval,
    canonical_result,
)


class RiskState(StrEnum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    REDUCE_ONLY = "REDUCE_ONLY"
    HALTED = "HALTED"
    RECOVERY = "RECOVERY"


class RiskDecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REDUCE_ONLY = "REDUCE_ONLY"
    HALTED = "HALTED"


class CircuitBreakerType(StrEnum):
    DATA = "DATA"
    MODEL = "MODEL"
    LOSS = "LOSS"
    MARGIN = "MARGIN"
    LIQUIDITY = "LIQUIDITY"
    VENUE = "VENUE"
    SECURITY = "SECURITY"
    MAJOR_EVENT = "MAJOR_EVENT"


class RiskConfirmation(StrEnum):
    RUMOR = "RUMOR"
    CONFIRMED = "CONFIRMED"


class RiskAction(StrEnum):
    MONITOR = "MONITOR"
    TIGHTEN_LIMITS = "TIGHTEN_LIMITS"
    REDUCE = "REDUCE"
    HALT = "HALT"


class MajorEventType(StrEnum):
    OFFICIAL_SECURITY_INCIDENT = "OFFICIAL_SECURITY_INCIDENT"
    WITHDRAWAL_SUSPENSION = "WITHDRAWAL_SUSPENSION"
    STABLECOIN_DEPEG = "STABLECOIN_DEPEG"
    MAJOR_REGULATORY = "MAJOR_REGULATORY"
    INFRASTRUCTURE_OUTAGE = "INFRASTRUCTURE_OUTAGE"


class RiskPosition(DomainModel):
    instrument_id: InstrumentId
    asset_id: AssetId
    strategy_id: StrategyId
    account_id: AccountId
    signed_weight: FiniteDecimal


class RiskSnapshot(DomainModel):
    snapshot_id: str = Field(min_length=1, max_length=255)
    as_of_time: UtcDateTime
    available_at: UtcDateTime
    data_last_available_at: UtcDateTime
    model_last_available_at: UtcDateTime
    positions: tuple[RiskPosition, ...]
    portfolio_gross_weight: NonNegativeDecimal
    daily_pnl_fraction: FiniteDecimal
    drawdown_fraction: NonNegativeDecimal
    margin_utilization: UnitInterval
    liquidity_score: UnitInterval
    venue_operational: bool
    security_clear: bool
    major_event_clear: bool
    ledger_reconciled: bool
    snapshot_sha256: str

    @field_validator("snapshot_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="risk snapshot hash")

    @model_validator(mode="after")
    def validate_snapshot(self) -> RiskSnapshot:
        if self.available_at < self.as_of_time:
            raise ValueError("risk snapshot availability cannot precede as-of time")
        if self.data_last_available_at > self.as_of_time:
            raise ValueError("risk snapshot cannot include future data")
        if self.model_last_available_at > self.as_of_time:
            raise ValueError("risk snapshot cannot include future model state")
        if len({item.instrument_id for item in self.positions}) != len(self.positions):
            raise ValueError("risk snapshot positions must be instrument-unique")
        gross = sum((abs(item.signed_weight) for item in self.positions), start=0)
        if gross != self.portfolio_gross_weight:
            raise ValueError("risk snapshot gross weight does not match positions")
        return self


class RiskEvent(DomainModel):
    risk_event_id: str = Field(min_length=1, max_length=255)
    breaker_type: CircuitBreakerType
    confirmation: RiskConfirmation
    action: RiskAction
    major_event_type: MajorEventType | None = None
    observed_at: UtcDateTime
    available_at: UtcDateTime
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    official_source: bool
    llm_generated: bool = False
    requested_reduction_fraction: UnitInterval = Decimal("0")

    @model_validator(mode="after")
    def validate_event(self) -> RiskEvent:
        if self.available_at < self.observed_at:
            raise ValueError("risk event availability cannot precede observation")
        if self.confirmation is RiskConfirmation.CONFIRMED and not self.official_source:
            raise ValueError("confirmed risk events require official source evidence")
        is_major = self.breaker_type is CircuitBreakerType.MAJOR_EVENT
        if is_major != (self.major_event_type is not None):
            raise ValueError("major event type must appear exactly on major event breakers")
        return self


class RiskAlert(DomainModel):
    alert_id: str
    breaker_type: CircuitBreakerType
    state: RiskState
    reason_code: str
    evidence_ids: tuple[str, ...]
    created_at: UtcDateTime


class CircuitBreakerOutcome(DomainModel):
    state: RiskState
    new_risk_allowed: bool
    target_scale: UnitInterval
    reason_codes: tuple[str, ...]
    alerts: tuple[RiskAlert, ...]


class ApprovedTarget(DomainModel):
    instrument_id: InstrumentId
    asset_id: AssetId
    strategy_id: StrategyId
    account_id: AccountId
    current_weight: FiniteDecimal
    proposed_target_weight: FiniteDecimal
    approved_target_weight: FiniteDecimal
    approved_delta_weight: FiniteDecimal

    @model_validator(mode="after")
    def validate_approved_delta(self) -> ApprovedTarget:
        expected = canonical_result(self.approved_target_weight - self.current_weight)
        if self.approved_delta_weight != expected:
            raise ValueError("approved delta must equal approved target minus current")
        if abs(self.approved_target_weight) > abs(self.proposed_target_weight):
            raise ValueError("risk decision cannot amplify a proposed target")
        return self


class RiskDecision(DomainModel):
    risk_decision_id: RiskDecisionId
    proposal_id: ProposalId
    proposal_sha256: str
    snapshot_id: str
    snapshot_sha256: str
    policy_version: str
    policy_sha256: str
    decided_at: UtcDateTime
    valid_until: UtcDateTime
    status: RiskDecisionStatus
    state: RiskState
    new_risk_allowed: bool
    approved_targets: tuple[ApprovedTarget, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("proposal_sha256", "snapshot_sha256", "policy_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="risk decision hash reference")

    @model_validator(mode="after")
    def validate_decision(self) -> RiskDecision:
        if self.valid_until <= self.decided_at:
            raise ValueError("risk decision must expire after it is created")
        if self.status is RiskDecisionStatus.APPROVED:
            if not self.new_risk_allowed or not self.approved_targets:
                raise ValueError("approved decision requires targets and new-risk permission")
        elif self.new_risk_allowed:
            raise ValueError("non-approved risk decision cannot allow new risk")
        if self.status in {RiskDecisionStatus.REJECTED, RiskDecisionStatus.HALTED} and (
            self.approved_targets
        ):
            raise ValueError("rejected or halted decision cannot approve targets")
        if (
            self.status is RiskDecisionStatus.REDUCE_ONLY
            and self.state is not RiskState.REDUCE_ONLY
        ):
            raise ValueError("reduce-only decision requires reduce-only state")
        if self.status is RiskDecisionStatus.HALTED and self.state is not RiskState.HALTED:
            raise ValueError("halted decision requires halted state")
        return self


class PreTradeRequest(DomainModel):
    request_id: str = Field(min_length=1, max_length=255)
    proposal_id: ProposalId
    risk_decision_id: RiskDecisionId
    instrument_id: InstrumentId
    asset_id: AssetId
    strategy_id: StrategyId
    account_id: AccountId
    requested_delta_weight: FiniteDecimal
    side: OrderSide
    order_type: OrderType
    quantity: Quantity
    limit_price: Price | None = None
    time_in_force: TimeInForce
    created_at: UtcDateTime
    valid_until: UtcDateTime

    @model_validator(mode="after")
    def validate_request(self) -> PreTradeRequest:
        if self.requested_delta_weight == 0:
            raise ValueError("pre-trade request delta cannot be zero")
        expected_side = OrderSide.BUY if self.requested_delta_weight > 0 else OrderSide.SELL
        if self.side is not expected_side:
            raise ValueError("pre-trade side must match requested delta direction")
        if self.quantity.amount <= 0:
            raise ValueError("pre-trade quantity must be positive")
        if self.valid_until <= self.created_at:
            raise ValueError("pre-trade request must have a future expiry")
        needs_limit = self.order_type is OrderType.LIMIT
        if needs_limit != (self.limit_price is not None):
            raise ValueError("limit price must appear exactly on limit requests")
        return self
