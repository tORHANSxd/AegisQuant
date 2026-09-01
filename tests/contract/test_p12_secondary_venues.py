"""OKX, Bybit, and Deribit contract-only execution boundaries."""

from __future__ import annotations

import pytest

from aegisquant.domain.identifiers import VenueId
from aegisquant.execution.accounts import VenueAccountSnapshot
from aegisquant.execution.venues import (
    SECONDARY_VENUE_IDS,
    ContractOnlyExecutionAdapter,
    ContractOnlySendBlocked,
)
from tests.p12_helpers import NOW, command, rules


@pytest.mark.asyncio
@pytest.mark.parametrize("venue_id", SECONDARY_VENUE_IDS)
async def test_secondary_venue_contracts_can_never_send(venue_id: VenueId) -> None:
    fixture = ContractOnlyExecutionAdapter(
        venue_id=venue_id,
        rules=(rules(venue_id=venue_id),),
        account=VenueAccountSnapshot(
            snapshot_id=f"snapshot-{venue_id}",
            venue_id=venue_id,
            sequence=0,
            captured_at=NOW,
            balances=(),
            open_orders=(),
            recent_fill_ids=(),
        ),
    )
    assert fixture.contract().send_enabled is False
    with pytest.raises(ContractOnlySendBlocked, match="SUBMIT-BLOCKED"):
        await fixture.submit(command())
