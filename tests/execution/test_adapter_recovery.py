"""Simulator adapter contract and evidence-first timeout recovery."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.execution import VenueOrderStatus
from aegisquant.domain.identifiers import ClientOrderId, IdempotencyKey
from aegisquant.domain.values import Money, Quantity
from aegisquant.execution.adapter import ExecutionAdapter, SimulatorFault
from aegisquant.execution.commands import AmendOrderCommand, CancelOrderCommand
from aegisquant.execution.models import (
    AmendDisposition,
    CancelDisposition,
    SubmitDisposition,
)
from aegisquant.execution.recovery import (
    CancelRecoveryDisposition,
    RecoveryDisposition,
    recover_cancel_unknown,
    recover_submit_unknown,
)
from tests.p12_helpers import BTC, NOW, USDT, adapter, command, reference_price


def cancel_command() -> CancelOrderCommand:
    source = command()
    return CancelOrderCommand(
        client_order_id=source.command.client_order_id,
        order_intent_id=source.command.order_intent_id,
        venue_id=source.command.venue_id,
        issued_at=NOW + timedelta(seconds=4),
        idempotency_key=IdempotencyKey("cancel-p12"),
        reason_code="AQ-EXEC-TEST-CANCEL",
    )


@pytest.mark.asyncio
async def test_adapter_protocol_submit_replay_partial_fill_and_cancel() -> None:
    venue = adapter()
    assert isinstance(venue, ExecutionAdapter)
    submit = await venue.submit(command())
    replay = await venue.submit(command())
    assert submit.disposition is SubmitDisposition.ACCEPTED
    assert replay.disposition is SubmitDisposition.IDEMPOTENT_REPLAY
    assert venue.economic_order_count == 1
    await venue.simulate_fill(
        client_order_id=str(command().command.client_order_id),
        quantity=Quantity(amount=Decimal("0.25"), asset_id=BTC),
        price=reference_price(),
        fee=Money(amount=Decimal("1"), asset_id=USDT),
    )
    order = (await venue.recent_orders())[0]
    assert order.status is VenueOrderStatus.PARTIALLY_FILLED
    cancel = await venue.cancel(cancel_command())
    assert cancel.disposition is CancelDisposition.CANCELED


@pytest.mark.asyncio
async def test_submit_timeout_is_not_blindly_retried() -> None:
    venue = adapter()
    venue.inject_fault(SimulatorFault.SUBMIT_TIMEOUT_AFTER_ACCEPT)
    result = await venue.submit(command())
    assert result.disposition is SubmitDisposition.UNKNOWN
    recovered = await recover_submit_unknown(
        adapter=venue,
        command=command(),
        checked_at=NOW + timedelta(seconds=5),
    )
    assert recovered.disposition is RecoveryDisposition.FOUND_OPEN_ORDER
    assert recovered.retry_permitted is False
    assert venue.economic_order_count == 1


@pytest.mark.asyncio
async def test_new_retry_generation_cannot_duplicate_economic_idempotency_key() -> None:
    venue = adapter()
    first = await venue.submit(command())
    retry = await venue.submit(command(retry_generation=1))
    assert first.disposition is SubmitDisposition.ACCEPTED
    assert retry.disposition is SubmitDisposition.IDEMPOTENT_REPLAY
    assert retry.economic_order_created is False
    assert venue.economic_order_count == 1


@pytest.mark.asyncio
async def test_exhaustive_absence_allows_new_generation_only() -> None:
    venue = adapter()
    recovered = await recover_submit_unknown(
        adapter=venue,
        command=command(),
        checked_at=NOW + timedelta(seconds=5),
    )
    assert recovered.disposition is RecoveryDisposition.SAFE_TO_RETRY
    assert recovered.retry_permitted is True
    assert recovered.next_retry_generation == 1


@pytest.mark.asyncio
async def test_disconnect_blocks_queries_until_reconnect() -> None:
    venue = adapter()
    venue.inject_fault(SimulatorFault.DISCONNECTED)
    try:
        await venue.account_snapshot()
    except ConnectionError as error:
        assert "DISCONNECTED" in str(error)
    else:
        raise AssertionError("disconnected adapter unexpectedly returned an account snapshot")
    venue.reconnect()
    assert (await venue.health()).sequence_healthy is True


@pytest.mark.asyncio
async def test_cancel_timeout_is_reconciled_from_terminal_order_evidence() -> None:
    venue = adapter()
    await venue.submit(command())
    venue.inject_fault(SimulatorFault.CANCEL_TIMEOUT_AFTER_CANCEL)
    assert (await venue.cancel(cancel_command())).disposition is CancelDisposition.UNKNOWN
    recovered = await recover_cancel_unknown(
        adapter=venue,
        command=cancel_command(),
        checked_at=NOW + timedelta(seconds=5),
    )
    assert recovered.disposition is CancelRecoveryDisposition.CANCELED_CONFIRMED
    assert recovered.cancel_retry_permitted is False


@pytest.mark.asyncio
async def test_cancel_replace_race_rejects_amend_after_cancel() -> None:
    venue = adapter()
    await venue.submit(command())
    await venue.cancel(cancel_command())
    amended = await venue.amend(
        AmendOrderCommand(
            client_order_id=ClientOrderId("client-amended-p12"),
            replaces_client_order_id=command().command.client_order_id,
            order_intent_id=command().command.order_intent_id,
            venue_id=venue.venue_id,
            issued_at=NOW + timedelta(seconds=5),
            idempotency_key=IdempotencyKey("amend-p12"),
            quantity=Quantity(amount=Decimal("0.5"), asset_id=BTC),
            limit_price=reference_price(Decimal("49900")),
            rule_version="binance-test-rules-v1",
        )
    )
    assert amended.disposition is AmendDisposition.REJECTED


@pytest.mark.asyncio
async def test_disconnected_submit_recovery_stays_manual() -> None:
    venue = adapter()
    venue.inject_fault(SimulatorFault.DISCONNECTED)
    recovered = await recover_submit_unknown(
        adapter=venue,
        command=command(),
        checked_at=NOW + timedelta(seconds=5),
    )
    assert recovered.disposition is RecoveryDisposition.MANUAL_REVIEW
    assert recovered.retry_permitted is False
