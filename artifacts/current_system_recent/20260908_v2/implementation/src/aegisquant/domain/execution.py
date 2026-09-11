"""Risk-approved order intent, venue fact, fill, and recovery contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    ClientOrderId,
    FillId,
    IdempotencyKey,
    InstrumentId,
    OrderIntentId,
    RecoveryCaseId,
    RiskDecisionId,
    VenueId,
    VenueOrderId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Money, Price, Quantity


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    GOOD_TIL_CANCELED = "GTC"
    IMMEDIATE_OR_CANCEL = "IOC"
    FILL_OR_KILL = "FOK"


class OrderCommandType(StrEnum):
    PLACE = "PLACE"
    CANCEL = "CANCEL"
    AMEND = "AMEND"


class VenueOrderStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RecoveryStatus(StrEnum):
    OPEN = "OPEN"
    REQUERY_REQUIRED = "REQUERY_REQUIRED"
    RECONCILED = "RECONCILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class OrderIntent(DomainModel):
    order_intent_id: OrderIntentId
    risk_decision_id: RiskDecisionId
    instrument_id: InstrumentId
    side: OrderSide
    order_type: OrderType
    quantity: Quantity
    limit_price: Price | None = None
    time_in_force: TimeInForce
    reduce_only: bool
    created_at: UtcDateTime
    valid_until: UtcDateTime
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def validate_intent(self) -> OrderIntent:
        if self.quantity.amount <= 0:
            raise ValueError("order intent quantity must be positive")
        if self.valid_until <= self.created_at:
            raise ValueError("order intent must have a future expiry")
        needs_limit = self.order_type is OrderType.LIMIT
        if needs_limit != (self.limit_price is not None):
            raise ValueError("limit price must appear exactly on limit orders")
        return self


class OrderCommand(DomainModel):
    client_order_id: ClientOrderId
    order_intent_id: OrderIntentId
    venue_id: VenueId
    command_type: OrderCommandType
    issued_at: UtcDateTime
    idempotency_key: IdempotencyKey
    replaces_client_order_id: ClientOrderId | None = None

    @model_validator(mode="after")
    def validate_command(self) -> OrderCommand:
        if self.command_type is OrderCommandType.AMEND and self.replaces_client_order_id is None:
            raise ValueError("amend command requires the replaced client order id")
        if (
            self.command_type is not OrderCommandType.AMEND
            and self.replaces_client_order_id is not None
        ):
            raise ValueError("only amend commands may replace a client order")
        return self


class VenueOrder(DomainModel):
    venue_order_id: VenueOrderId | None
    client_order_id: ClientOrderId
    order_intent_id: OrderIntentId
    venue_id: VenueId
    status: VenueOrderStatus
    locally_sent_at: UtcDateTime | None = None
    venue_accepted_at: UtcDateTime | None = None
    last_venue_update_at: UtcDateTime | None = None
    cumulative_filled_quantity: Quantity
    rejection_code: str | None = None

    @model_validator(mode="after")
    def require_venue_evidence(self) -> VenueOrder:
        accepted_states = {
            VenueOrderStatus.ACCEPTED,
            VenueOrderStatus.PARTIALLY_FILLED,
            VenueOrderStatus.FILLED,
            VenueOrderStatus.CANCELED,
            VenueOrderStatus.EXPIRED,
        }
        if self.status in accepted_states and (
            self.venue_order_id is None or self.venue_accepted_at is None
        ):
            raise ValueError("accepted venue state requires venue evidence")
        if self.status is VenueOrderStatus.REJECTED and self.rejection_code is None:
            raise ValueError("rejected venue order requires a stable rejection code")
        return self


VenueOrderState = VenueOrder


class Fill(DomainModel):
    fill_id: FillId
    venue_order_id: VenueOrderId
    client_order_id: ClientOrderId
    order_intent_id: OrderIntentId
    instrument_id: InstrumentId
    side: OrderSide
    quantity: Quantity
    price: Price
    fee: Money
    event_time: UtcDateTime
    available_time: UtcDateTime
    ingest_time: UtcDateTime
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def validate_fill(self) -> Fill:
        if self.quantity.amount <= 0:
            raise ValueError("fill quantity must be positive")
        if not self.event_time <= self.available_time <= self.ingest_time:
            raise ValueError("fill event/available/ingest times must be monotonic")
        return self


FillEvent = Fill


class OrderRecoveryCase(DomainModel):
    recovery_case_id: RecoveryCaseId
    client_order_id: ClientOrderId
    order_intent_id: OrderIntentId
    venue_id: VenueId
    status: RecoveryStatus
    opened_at: UtcDateTime
    last_checked_at: UtcDateTime
    local_evidence: tuple[str, ...]
    venue_evidence: tuple[str, ...]
    resolution: str | None = None

    @model_validator(mode="after")
    def validate_recovery(self) -> OrderRecoveryCase:
        if self.last_checked_at < self.opened_at:
            raise ValueError("recovery check cannot precede open time")
        if self.status is RecoveryStatus.RECONCILED and self.resolution is None:
            raise ValueError("reconciled recovery case requires a resolution")
        return self
