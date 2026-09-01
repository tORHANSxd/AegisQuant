"""Startup reconciliation, unknown submit blocking, and graceful shutdown."""

from __future__ import annotations

import pytest

from aegisquant.execution.adapter import SimulatorFault
from aegisquant.execution.lifecycle import ExecutionEngineState, ExecutionLifecycle
from aegisquant.execution.models import SubmitDisposition
from tests.p12_helpers import adapter, command


@pytest.mark.asyncio
async def test_start_submit_quiesce_stop() -> None:
    lifecycle = ExecutionLifecycle(adapter=adapter())
    started = await lifecycle.start(local_open_order_ids=())
    assert started.state is ExecutionEngineState.RUNNING
    assert (await lifecycle.submit(command())).disposition is SubmitDisposition.ACCEPTED
    assert lifecycle.quiesce().new_submissions_allowed is False
    assert lifecycle.stop().state is ExecutionEngineState.STOPPED


@pytest.mark.asyncio
async def test_unknown_submit_cannot_be_sent_again_before_recovery() -> None:
    venue = adapter()
    lifecycle = ExecutionLifecycle(adapter=venue)
    await lifecycle.start(local_open_order_ids=())
    venue.inject_fault(SimulatorFault.SUBMIT_TIMEOUT_AFTER_ACCEPT)
    assert (await lifecycle.submit(command())).disposition is SubmitDisposition.UNKNOWN
    with pytest.raises(RuntimeError, match="MUST-RECOVER"):
        await lifecycle.submit(command())
    assert venue.economic_order_count == 1


@pytest.mark.asyncio
async def test_startup_mismatch_halts_before_new_orders() -> None:
    lifecycle = ExecutionLifecycle(adapter=adapter())
    result = await lifecycle.start(local_open_order_ids=("not-at-venue",))
    assert result.state is ExecutionEngineState.HALTED
    assert result.new_submissions_allowed is False


@pytest.mark.asyncio
async def test_crash_restart_reconciles_known_open_order_before_running() -> None:
    venue = adapter()
    await venue.submit(command())
    lifecycle = ExecutionLifecycle(adapter=venue)
    result = await lifecycle.crash_recover(
        local_open_order_ids=(str(command().command.client_order_id),)
    )
    assert result.state is ExecutionEngineState.RUNNING
    assert result.unresolved_client_order_ids == ()
