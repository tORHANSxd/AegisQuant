"""Order state monotonicity, replay, gaps, and late events."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.identifiers import ClientOrderId, VenueOrderId
from aegisquant.domain.values import Quantity
from aegisquant.execution.state_machine import (
    InternalOrderState,
    OrderEventType,
    OrderStateEvent,
    apply_order_event,
    initial_order_record,
    replay_order_events,
)
from tests.p12_helpers import BTC, NOW


def event(
    sequence: int,
    event_type: OrderEventType,
    cumulative: str = "0",
    *,
    event_id: str | None = None,
    recovery: bool = False,
) -> OrderStateEvent:
    return OrderStateEvent(
        event_id=event_id or f"event-{sequence}-{event_type.value}",
        client_order_id=ClientOrderId("client-state-p12"),
        event_type=event_type,
        venue_sequence=sequence,
        observed_at=NOW + timedelta(seconds=sequence),
        available_at=NOW + timedelta(seconds=sequence),
        venue_order_id=(
            VenueOrderId("venue-state-p12")
            if event_type
            in {
                OrderEventType.VENUE_ACCEPTED,
                OrderEventType.PARTIAL_FILL,
                OrderEventType.FILL,
                OrderEventType.CANCELED,
                OrderEventType.EXPIRED,
            }
            else None
        ),
        venue_cumulative_filled=Quantity(amount=Decimal(cumulative), asset_id=BTC),
        recovery_resolution=recovery,
        reason_code=f"AQ-EXEC-TEST-{event_type.value}",
    )


def initial():
    return initial_order_record(
        client_order_id=ClientOrderId("client-state-p12"),
        total_quantity=Quantity(amount=Decimal("1"), asset_id=BTC),
        created_at=NOW,
    )


def test_full_state_path_replays_deterministically() -> None:
    events = (
        event(1, OrderEventType.RISK_APPROVED),
        event(2, OrderEventType.SUBMIT_STARTED),
        event(3, OrderEventType.VENUE_ACCEPTED),
        event(4, OrderEventType.PARTIAL_FILL, "0.4"),
        event(5, OrderEventType.FILL, "1"),
        event(6, OrderEventType.RECONCILED, "1"),
    )
    result = replay_order_events(initial(), events)
    assert result.state is InternalOrderState.TERMINAL_RECONCILED
    assert result.cumulative_filled.amount == Decimal("1")
    assert replay_order_events(initial(), events) == result


def test_duplicate_is_idempotent_and_late_event_never_rolls_back() -> None:
    accepted = replay_order_events(
        initial(),
        (
            event(1, OrderEventType.RISK_APPROVED),
            event(2, OrderEventType.SUBMIT_STARTED),
            event(3, OrderEventType.VENUE_ACCEPTED),
            event(4, OrderEventType.PARTIAL_FILL, "0.5"),
        ),
    )
    duplicate = apply_order_event(accepted, event(4, OrderEventType.PARTIAL_FILL, "0.5"))
    assert duplicate.applied is False
    late = apply_order_event(
        accepted,
        event(3, OrderEventType.VENUE_ACCEPTED, "0", event_id="late-accepted"),
    )
    assert late.record.state is InternalOrderState.PARTIALLY_FILLED
    assert late.record.cumulative_filled.amount == Decimal("0.5")


def test_sequence_gap_and_timeout_require_recovery() -> None:
    submitting = replay_order_events(
        initial(),
        (
            event(1, OrderEventType.RISK_APPROVED),
            event(2, OrderEventType.SUBMIT_STARTED),
        ),
    )
    timeout = apply_order_event(submitting, event(3, OrderEventType.SUBMIT_TIMEOUT))
    assert timeout.after is InternalOrderState.SUBMIT_UNKNOWN
    gap = apply_order_event(timeout.record, event(5, OrderEventType.VENUE_ACCEPTED))
    assert gap.after is InternalOrderState.RECOVERY_REQUIRED
    assert gap.sequence_gap_detected is True

    resolved = apply_order_event(
        gap.record,
        event(8, OrderEventType.VENUE_ACCEPTED, recovery=True),
    )
    assert resolved.after is InternalOrderState.VENUE_ACCEPTED


def test_venue_overfill_is_rejected_as_impossible_economic_fact() -> None:
    with pytest.raises(ValueError, match="OVERFILL"):
        apply_order_event(initial(), event(1, OrderEventType.PARTIAL_FILL, "1.1"))
