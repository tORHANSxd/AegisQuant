"""Monotonic, replayable, and idempotent execution order state machine."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ClientOrderId, VenueOrderId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Quantity


class InternalOrderState(StrEnum):
    CREATED = "CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMITTING = "SUBMITTING"
    SUBMIT_UNKNOWN = "SUBMIT_UNKNOWN"
    VENUE_ACCEPTED = "VENUE_ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_UNKNOWN = "CANCEL_UNKNOWN"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    TERMINAL_RECONCILED = "TERMINAL_RECONCILED"


class OrderEventType(StrEnum):
    RISK_APPROVED = "RISK_APPROVED"
    SUBMIT_STARTED = "SUBMIT_STARTED"
    SUBMIT_TIMEOUT = "SUBMIT_TIMEOUT"
    VENUE_ACCEPTED = "VENUE_ACCEPTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL = "FILL"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_TIMEOUT = "CANCEL_TIMEOUT"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN_VENUE_STATE = "UNKNOWN_VENUE_STATE"
    RECONCILED = "RECONCILED"


TERMINAL_STATES = frozenset(
    {
        InternalOrderState.FILLED,
        InternalOrderState.CANCELED,
        InternalOrderState.REJECTED,
        InternalOrderState.EXPIRED,
    }
)


class OrderStateEvent(DomainModel):
    event_id: str = Field(min_length=1, max_length=255)
    client_order_id: ClientOrderId
    event_type: OrderEventType
    venue_sequence: int = Field(ge=1)
    observed_at: UtcDateTime
    available_at: UtcDateTime
    venue_order_id: VenueOrderId | None = None
    venue_cumulative_filled: Quantity
    recovery_resolution: bool = False
    reason_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_event(self) -> OrderStateEvent:
        if self.available_at < self.observed_at:
            raise ValueError("order event availability cannot precede observation")
        if self.venue_cumulative_filled.amount < 0:
            raise ValueError("venue cumulative fill cannot be negative")
        if (
            self.event_type
            in {
                OrderEventType.VENUE_ACCEPTED,
                OrderEventType.PARTIAL_FILL,
                OrderEventType.FILL,
                OrderEventType.CANCELED,
                OrderEventType.EXPIRED,
            }
            and self.venue_order_id is None
        ):
            raise ValueError("venue order event requires venue order id")
        return self


class InternalOrderRecord(DomainModel):
    client_order_id: ClientOrderId
    state: InternalOrderState
    total_quantity: Quantity
    cumulative_filled: Quantity
    venue_order_id: VenueOrderId | None = None
    last_venue_sequence: int = Field(ge=0)
    last_available_at: UtcDateTime
    processed_event_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_record(self) -> InternalOrderRecord:
        if self.cumulative_filled.asset_id != self.total_quantity.asset_id:
            raise ValueError("order fill and total quantity assets differ")
        if not Decimal("0") <= self.cumulative_filled.amount <= self.total_quantity.amount:
            raise ValueError("order cumulative fill is outside total quantity")
        if len(set(self.processed_event_ids)) != len(self.processed_event_ids):
            raise ValueError("processed order event ids must be unique")
        return self


class OrderTransition(DomainModel):
    before: InternalOrderState
    after: InternalOrderState
    record: InternalOrderRecord
    applied: bool
    late_or_out_of_order: bool
    sequence_gap_detected: bool


def initial_order_record(
    *, client_order_id: ClientOrderId, total_quantity: Quantity, created_at: UtcDateTime
) -> InternalOrderRecord:
    if total_quantity.amount <= 0:
        raise ValueError("order total quantity must be positive")
    return InternalOrderRecord(
        client_order_id=client_order_id,
        state=InternalOrderState.CREATED,
        total_quantity=total_quantity,
        cumulative_filled=Quantity(amount=Decimal("0"), asset_id=total_quantity.asset_id),
        last_venue_sequence=0,
        last_available_at=created_at,
        processed_event_ids=(),
        reason_codes=("AQ-EXEC-ORDER-CREATED",),
    )


def _target_state(event: OrderStateEvent, total: Quantity) -> InternalOrderState:
    mapping = {
        OrderEventType.RISK_APPROVED: InternalOrderState.RISK_APPROVED,
        OrderEventType.SUBMIT_STARTED: InternalOrderState.SUBMITTING,
        OrderEventType.SUBMIT_TIMEOUT: InternalOrderState.SUBMIT_UNKNOWN,
        OrderEventType.VENUE_ACCEPTED: InternalOrderState.VENUE_ACCEPTED,
        OrderEventType.CANCEL_REQUESTED: InternalOrderState.CANCEL_REQUESTED,
        OrderEventType.CANCEL_TIMEOUT: InternalOrderState.CANCEL_UNKNOWN,
        OrderEventType.CANCELED: InternalOrderState.CANCELED,
        OrderEventType.REJECTED: InternalOrderState.REJECTED,
        OrderEventType.EXPIRED: InternalOrderState.EXPIRED,
        OrderEventType.UNKNOWN_VENUE_STATE: InternalOrderState.RECOVERY_REQUIRED,
        OrderEventType.RECONCILED: InternalOrderState.TERMINAL_RECONCILED,
    }
    if event.event_type in {OrderEventType.PARTIAL_FILL, OrderEventType.FILL}:
        return (
            InternalOrderState.FILLED
            if event.venue_cumulative_filled.amount == total.amount
            else InternalOrderState.PARTIALLY_FILLED
        )
    return mapping[event.event_type]


ALLOWED_TRANSITIONS = {
    InternalOrderState.CREATED: {InternalOrderState.RISK_APPROVED},
    InternalOrderState.RISK_APPROVED: {
        InternalOrderState.SUBMITTING,
        InternalOrderState.EXPIRED,
    },
    InternalOrderState.SUBMITTING: {
        InternalOrderState.SUBMIT_UNKNOWN,
        InternalOrderState.VENUE_ACCEPTED,
        InternalOrderState.PARTIALLY_FILLED,
        InternalOrderState.FILLED,
        InternalOrderState.REJECTED,
        InternalOrderState.RECOVERY_REQUIRED,
    },
    InternalOrderState.SUBMIT_UNKNOWN: {
        InternalOrderState.VENUE_ACCEPTED,
        InternalOrderState.PARTIALLY_FILLED,
        InternalOrderState.FILLED,
        InternalOrderState.REJECTED,
        InternalOrderState.RECOVERY_REQUIRED,
    },
    InternalOrderState.VENUE_ACCEPTED: {
        InternalOrderState.PARTIALLY_FILLED,
        InternalOrderState.FILLED,
        InternalOrderState.CANCEL_REQUESTED,
        InternalOrderState.CANCELED,
        InternalOrderState.EXPIRED,
        InternalOrderState.RECOVERY_REQUIRED,
    },
    InternalOrderState.PARTIALLY_FILLED: {
        InternalOrderState.FILLED,
        InternalOrderState.CANCEL_REQUESTED,
        InternalOrderState.CANCELED,
        InternalOrderState.EXPIRED,
        InternalOrderState.RECOVERY_REQUIRED,
    },
    InternalOrderState.CANCEL_REQUESTED: {
        InternalOrderState.CANCEL_UNKNOWN,
        InternalOrderState.CANCELED,
        InternalOrderState.PARTIALLY_FILLED,
        InternalOrderState.FILLED,
        InternalOrderState.RECOVERY_REQUIRED,
    },
    InternalOrderState.CANCEL_UNKNOWN: {
        InternalOrderState.CANCELED,
        InternalOrderState.PARTIALLY_FILLED,
        InternalOrderState.FILLED,
        InternalOrderState.RECOVERY_REQUIRED,
    },
}


def apply_order_event(record: InternalOrderRecord, event: OrderStateEvent) -> OrderTransition:
    """Apply one event without allowing duplicate or regressive state changes."""
    if event.client_order_id != record.client_order_id:
        raise ValueError("AQ-EXEC-ORDER-EVENT-CLIENT-ID-MISMATCH")
    if event.venue_cumulative_filled.asset_id != record.total_quantity.asset_id:
        raise ValueError("AQ-EXEC-ORDER-EVENT-QUANTITY-ASSET-MISMATCH")
    if event.venue_cumulative_filled.amount > record.total_quantity.amount:
        raise ValueError("AQ-EXEC-ORDER-OVERFILL")
    if event.event_id in record.processed_event_ids:
        return OrderTransition(
            before=record.state,
            after=record.state,
            record=record,
            applied=False,
            late_or_out_of_order=event.venue_sequence <= record.last_venue_sequence,
            sequence_gap_detected=False,
        )
    late = event.venue_sequence <= record.last_venue_sequence
    gap = record.last_venue_sequence > 0 and event.venue_sequence > record.last_venue_sequence + 1
    if event.venue_cumulative_filled.amount < record.cumulative_filled.amount:
        if not late:
            raise ValueError("AQ-EXEC-CUMULATIVE-FILL-REGRESSION")
        cumulative = record.cumulative_filled
    else:
        cumulative = event.venue_cumulative_filled
    target = _target_state(event, record.total_quantity)
    if (
        gap and not event.recovery_resolution
    ) or event.event_type is OrderEventType.UNKNOWN_VENUE_STATE:
        target = InternalOrderState.RECOVERY_REQUIRED
    elif record.state is InternalOrderState.TERMINAL_RECONCILED:
        target = (
            InternalOrderState.TERMINAL_RECONCILED
            if event.event_type is OrderEventType.RECONCILED
            else InternalOrderState.RECOVERY_REQUIRED
        )
    elif record.state in TERMINAL_STATES:
        if event.event_type is OrderEventType.RECONCILED:
            target = InternalOrderState.TERMINAL_RECONCILED
        elif target is not record.state or cumulative.amount != record.cumulative_filled.amount:
            target = InternalOrderState.RECOVERY_REQUIRED
        else:
            target = record.state
    elif record.state is InternalOrderState.RECOVERY_REQUIRED:
        if event.event_type is OrderEventType.RECONCILED:
            raise ValueError("AQ-EXEC-RECOVERY-REQUIRES-RESOLVED-VENUE-STATE")
        if not event.recovery_resolution:
            target = InternalOrderState.RECOVERY_REQUIRED
    else:
        allowed = ALLOWED_TRANSITIONS.get(record.state, set())
        if target not in allowed and target is not record.state:
            if late:
                target = record.state
            else:
                raise ValueError(
                    f"AQ-EXEC-ILLEGAL-STATE-TRANSITION:{record.state.value}->{target.value}"
                )
    updated = record.model_copy(
        update={
            "state": target,
            "cumulative_filled": cumulative,
            "venue_order_id": event.venue_order_id or record.venue_order_id,
            "last_venue_sequence": max(record.last_venue_sequence, event.venue_sequence),
            "last_available_at": max(record.last_available_at, event.available_at),
            "processed_event_ids": (*record.processed_event_ids, event.event_id),
            "reason_codes": (*record.reason_codes, event.reason_code),
        }
    )
    return OrderTransition(
        before=record.state,
        after=target,
        record=updated,
        applied=True,
        late_or_out_of_order=late,
        sequence_gap_detected=gap,
    )


def replay_order_events(
    initial: InternalOrderRecord, events: tuple[OrderStateEvent, ...]
) -> InternalOrderRecord:
    record = initial
    for event in events:
        record = apply_order_event(record, event).record
    return record
