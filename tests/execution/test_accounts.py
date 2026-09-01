"""Account stream gap and snapshot reconciliation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from aegisquant.execution.accounts import (
    AccountEventType,
    AccountStreamEvent,
    AccountSynchronizer,
    AccountSyncState,
)
from tests.p12_helpers import NOW, adapter


def stream_event(sequence: int) -> AccountStreamEvent:
    venue = adapter().venue_id
    return AccountStreamEvent(
        event_id=f"account-event-{sequence}",
        venue_id=venue,
        sequence=sequence,
        event_type=AccountEventType.ORDER,
        observed_at=NOW + timedelta(seconds=sequence),
        available_at=NOW + timedelta(seconds=sequence),
        evidence_ids=(f"venue-sequence-{sequence}",),
    )


def test_gap_requires_rest_snapshot_before_sync() -> None:
    venue_adapter = adapter()
    synchronizer = AccountSynchronizer(venue_id=venue_adapter.venue_id)
    assert synchronizer.consume(stream_event(1)).state is AccountSyncState.SYNCHRONIZED
    gap = synchronizer.consume(stream_event(3))
    assert gap.sequence_gap is True
    assert gap.state is AccountSyncState.RECONCILIATION_REQUIRED


@pytest.mark.asyncio
async def test_snapshot_reconciles_and_reports_order_differences() -> None:
    venue_adapter = adapter()
    synchronizer = AccountSynchronizer(venue_id=venue_adapter.venue_id)
    snapshot = await venue_adapter.account_snapshot()
    result = synchronizer.reconcile(snapshot, local_open_order_ids=("local-missing",))
    assert result.state is AccountSyncState.RECONCILIATION_REQUIRED
    assert result.unknown_local_order_ids == ("local-missing",)


def test_duplicate_account_event_is_idempotent() -> None:
    synchronizer = AccountSynchronizer(venue_id=adapter().venue_id)
    first = stream_event(1)
    assert synchronizer.consume(first).applied is True
    assert synchronizer.consume(first).applied is False
