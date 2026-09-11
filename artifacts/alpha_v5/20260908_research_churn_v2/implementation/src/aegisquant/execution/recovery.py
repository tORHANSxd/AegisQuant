"""Evidence-first recovery for unknown submit and cancel outcomes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import VenueOrderStatus
from aegisquant.domain.time import UtcDateTime
from aegisquant.execution.adapter import ExecutionAdapter
from aegisquant.execution.commands import CancelOrderCommand, SubmitOrderCommand
from aegisquant.execution.models import AdapterHealthState


class RecoveryDisposition(StrEnum):
    FOUND_OPEN_ORDER = "FOUND_OPEN_ORDER"
    FOUND_TERMINAL_ORDER = "FOUND_TERMINAL_ORDER"
    FOUND_FILL = "FOUND_FILL"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class SubmitRecoveryOutcome(DomainModel):
    client_order_id: str
    disposition: RecoveryDisposition
    checked_at: UtcDateTime
    retry_permitted: bool
    next_retry_generation: int | None = Field(default=None, ge=1)
    venue_evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)


class CancelRecoveryDisposition(StrEnum):
    CANCELED_CONFIRMED = "CANCELED_CONFIRMED"
    FILLED_BEFORE_CANCEL = "FILLED_BEFORE_CANCEL"
    STILL_OPEN = "STILL_OPEN"
    REQUERY_REQUIRED = "REQUERY_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class CancelRecoveryOutcome(DomainModel):
    client_order_id: str
    disposition: CancelRecoveryDisposition
    checked_at: UtcDateTime
    cancel_retry_permitted: bool
    venue_evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)


async def recover_submit_unknown(
    *,
    adapter: ExecutionAdapter,
    command: SubmitOrderCommand,
    checked_at: UtcDateTime,
) -> SubmitRecoveryOutcome:
    """Query all venue evidence before permitting a new client-ID generation."""
    client_id = command.command.client_order_id
    try:
        open_orders = await adapter.open_orders()
        recent_orders = await adapter.recent_orders()
        recent_fills = await adapter.recent_fills()
        health = await adapter.health()
    except (ConnectionError, TimeoutError):
        return _outcome(
            command,
            checked_at,
            RecoveryDisposition.MANUAL_REVIEW,
            evidence=("VENUE-QUERY-UNAVAILABLE",),
            reason="AQ-EXEC-RECOVERY-VENUE-QUERY-UNAVAILABLE",
        )
    matching_open = tuple(item for item in open_orders if item.client_order_id == client_id)
    if matching_open:
        return _outcome(
            command,
            checked_at,
            RecoveryDisposition.FOUND_OPEN_ORDER,
            evidence=tuple(str(item.venue_order_id) for item in matching_open),
            reason="AQ-EXEC-RECOVERY-FOUND-OPEN",
        )
    matching_orders = tuple(item for item in recent_orders if item.client_order_id == client_id)
    if matching_orders:
        statuses = {item.status for item in matching_orders}
        disposition = (
            RecoveryDisposition.FOUND_TERMINAL_ORDER
            if statuses
            & {
                VenueOrderStatus.FILLED,
                VenueOrderStatus.CANCELED,
                VenueOrderStatus.REJECTED,
                VenueOrderStatus.EXPIRED,
            }
            else RecoveryDisposition.FOUND_OPEN_ORDER
        )
        return _outcome(
            command,
            checked_at,
            disposition,
            evidence=tuple(str(item.venue_order_id) for item in matching_orders),
            reason="AQ-EXEC-RECOVERY-FOUND-ORDER",
        )
    matching_fills = tuple(item for item in recent_fills if item.client_order_id == client_id)
    if matching_fills:
        return _outcome(
            command,
            checked_at,
            RecoveryDisposition.FOUND_FILL,
            evidence=tuple(str(item.fill_id) for item in matching_fills),
            reason="AQ-EXEC-RECOVERY-FOUND-FILL",
        )
    if health.state is not AdapterHealthState.READY or health.reconciliation_required:
        return _outcome(
            command,
            checked_at,
            RecoveryDisposition.MANUAL_REVIEW,
            evidence=health.reason_codes,
            reason="AQ-EXEC-RECOVERY-VENUE-NOT-CERTAIN",
        )
    return SubmitRecoveryOutcome(
        client_order_id=str(client_id),
        disposition=RecoveryDisposition.SAFE_TO_RETRY,
        checked_at=checked_at,
        retry_permitted=True,
        next_retry_generation=command.identity.retry_generation + 1,
        venue_evidence_ids=("OPEN_ORDERS_EMPTY", "RECENT_ORDERS_EMPTY", "RECENT_FILLS_EMPTY"),
        reason_codes=("AQ-EXEC-RECOVERY-EXHAUSTIVE-ABSENCE",),
    )


async def recover_cancel_unknown(
    *,
    adapter: ExecutionAdapter,
    command: CancelOrderCommand,
    checked_at: UtcDateTime,
) -> CancelRecoveryOutcome:
    """Resolve a cancel timeout without treating response loss as cancellation."""
    try:
        open_orders = await adapter.open_orders()
        recent_orders = await adapter.recent_orders()
        recent_fills = await adapter.recent_fills()
        health = await adapter.health()
    except (ConnectionError, TimeoutError):
        return _cancel_outcome(
            command,
            checked_at,
            CancelRecoveryDisposition.MANUAL_REVIEW,
            retry=False,
            evidence=("VENUE-QUERY-UNAVAILABLE",),
            reason="AQ-EXEC-CANCEL-RECOVERY-QUERY-UNAVAILABLE",
        )
    client_id = command.client_order_id
    matching_fills = tuple(item for item in recent_fills if item.client_order_id == client_id)
    matching_orders = tuple(item for item in recent_orders if item.client_order_id == client_id)
    if any(item.status is VenueOrderStatus.FILLED for item in matching_orders) or matching_fills:
        evidence = tuple(str(item.fill_id) for item in matching_fills) or tuple(
            str(item.venue_order_id) for item in matching_orders
        )
        return _cancel_outcome(
            command,
            checked_at,
            CancelRecoveryDisposition.FILLED_BEFORE_CANCEL,
            retry=False,
            evidence=evidence,
            reason="AQ-EXEC-CANCEL-RECOVERY-FILLED",
        )
    if any(item.status is VenueOrderStatus.CANCELED for item in matching_orders):
        return _cancel_outcome(
            command,
            checked_at,
            CancelRecoveryDisposition.CANCELED_CONFIRMED,
            retry=False,
            evidence=tuple(str(item.venue_order_id) for item in matching_orders),
            reason="AQ-EXEC-CANCEL-RECOVERY-CONFIRMED",
        )
    if any(item.client_order_id == client_id for item in open_orders):
        return _cancel_outcome(
            command,
            checked_at,
            CancelRecoveryDisposition.STILL_OPEN,
            retry=True,
            evidence=tuple(
                str(item.venue_order_id)
                for item in open_orders
                if item.client_order_id == client_id
            ),
            reason="AQ-EXEC-CANCEL-RECOVERY-STILL-OPEN",
        )
    if health.state is not AdapterHealthState.READY or health.reconciliation_required:
        disposition = CancelRecoveryDisposition.MANUAL_REVIEW
        reason = "AQ-EXEC-CANCEL-RECOVERY-VENUE-NOT-CERTAIN"
    else:
        disposition = CancelRecoveryDisposition.REQUERY_REQUIRED
        reason = "AQ-EXEC-CANCEL-RECOVERY-NO-EVIDENCE"
    return _cancel_outcome(
        command,
        checked_at,
        disposition,
        retry=False,
        evidence=health.reason_codes,
        reason=reason,
    )


def _outcome(
    command: SubmitOrderCommand,
    checked_at: UtcDateTime,
    disposition: RecoveryDisposition,
    *,
    evidence: tuple[str, ...],
    reason: str,
) -> SubmitRecoveryOutcome:
    return SubmitRecoveryOutcome(
        client_order_id=str(command.command.client_order_id),
        disposition=disposition,
        checked_at=checked_at,
        retry_permitted=False,
        venue_evidence_ids=evidence,
        reason_codes=(reason,),
    )


def _cancel_outcome(
    command: CancelOrderCommand,
    checked_at: UtcDateTime,
    disposition: CancelRecoveryDisposition,
    *,
    retry: bool,
    evidence: tuple[str, ...],
    reason: str,
) -> CancelRecoveryOutcome:
    return CancelRecoveryOutcome(
        client_order_id=str(command.client_order_id),
        disposition=disposition,
        checked_at=checked_at,
        cancel_retry_permitted=retry,
        venue_evidence_ids=evidence,
        reason_codes=(reason,),
    )
