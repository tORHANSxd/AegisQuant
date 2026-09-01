"""P12 chaos cases preserve known economic facts under gaps and timeouts."""

from __future__ import annotations

from datetime import timedelta

import pytest

from aegisquant.execution.accounts import AccountSynchronizer, AccountSyncState
from aegisquant.execution.adapter import SimulatorFault
from aegisquant.execution.models import SubmitDisposition
from aegisquant.execution.recovery import RecoveryDisposition, recover_submit_unknown
from tests.execution.test_accounts import stream_event
from tests.p12_helpers import NOW, adapter, command


@pytest.mark.asyncio
async def test_response_loss_after_acceptance_never_creates_second_order() -> None:
    venue = adapter()
    venue.inject_fault(SimulatorFault.SUBMIT_TIMEOUT_AFTER_ACCEPT)
    assert (await venue.submit(command())).disposition is SubmitDisposition.UNKNOWN
    recovered = await recover_submit_unknown(
        adapter=venue, command=command(), checked_at=NOW + timedelta(seconds=5)
    )
    assert recovered.disposition is RecoveryDisposition.FOUND_OPEN_ORDER
    assert venue.economic_order_count == 1


def test_account_sequence_gap_never_claims_synchronized_funds() -> None:
    synchronizer = AccountSynchronizer(venue_id=adapter().venue_id)
    synchronizer.consume(stream_event(1))
    result = synchronizer.consume(stream_event(4))
    assert result.state is AccountSyncState.RECONCILIATION_REQUIRED
    assert result.sequence_gap is True
