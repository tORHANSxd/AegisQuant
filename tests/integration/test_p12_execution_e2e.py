"""P12 simulator end-to-end timeout, partial fill, cancel, and reconnect flow."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.execution import VenueOrderStatus
from aegisquant.domain.values import Money, Quantity
from aegisquant.execution.models import CancelDisposition, SubmitDisposition
from aegisquant.execution.recovery import RecoveryDisposition
from aegisquant.execution.simulator import run_timeout_partial_cancel_scenario
from tests.p12_helpers import BTC, NOW, USDT, adapter, command, reference_price


@pytest.mark.asyncio
async def test_testnet_semantics_execute_end_to_end_without_network() -> None:
    result = await run_timeout_partial_cancel_scenario(
        adapter=adapter(),
        command=command(),
        partial_quantity=Quantity(amount=Decimal("0.4"), asset_id=BTC),
        price=reference_price(),
        fee=Money(amount=Decimal("1"), asset_id=USDT),
        checked_at=NOW + timedelta(seconds=5),
    )
    assert result.submit_disposition is SubmitDisposition.UNKNOWN
    assert result.recovery_disposition is RecoveryDisposition.FOUND_OPEN_ORDER
    assert result.final_status is VenueOrderStatus.CANCELED
    assert result.cancel_disposition is CancelDisposition.CANCELED
    assert result.duplicate_economic_orders == 0
    assert result.network_requests_performed == 0
