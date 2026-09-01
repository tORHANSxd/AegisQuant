"""Runtime watchdog, stale-input gates, checkpoint, and recovery tests."""

from __future__ import annotations

from datetime import timedelta

from aegisquant.runtime.models import FaultKind, RuntimeMode, RuntimeState
from aegisquant.runtime.supervisor import RuntimePolicy, RuntimeSupervisor
from tests.p12_helpers import NOW


def policy(*, capacity: int = 8, restarts: int = 2) -> RuntimePolicy:
    return RuntimePolicy(
        maximum_data_age_seconds=10,
        maximum_model_age_seconds=60,
        maximum_clock_drift_ms=100,
        maximum_restarts=restarts,
        health_history_capacity=capacity,
        qualifying_wall_clock_hours=12,
    )


def test_stale_data_degrades_and_blocks_new_risk_until_recovered() -> None:
    supervisor = RuntimeSupervisor(mode=RuntimeMode.PAPER, policy=policy())
    supervisor.start(observed_at=NOW)
    stale = supervisor.heartbeat(
        observed_at=NOW + timedelta(seconds=1),
        data_age_seconds=11,
        model_age_seconds=0,
        clock_drift_ms=0,
    )
    assert stale.state is RuntimeState.DEGRADED
    assert stale.new_risk_allowed is False
    recovered = supervisor.recover(
        kind=FaultKind.DATA_SOURCE,
        observed_at=NOW + timedelta(seconds=2),
    )
    assert recovered.state is RuntimeState.RUNNING
    assert recovered.new_risk_allowed is True


def test_clock_drift_latches_halt_until_manual_recovery() -> None:
    supervisor = RuntimeSupervisor(mode=RuntimeMode.SHADOW, policy=policy())
    supervisor.start(observed_at=NOW)
    checkpoint = supervisor.checkpoint()
    halted = supervisor.heartbeat(
        observed_at=NOW + timedelta(seconds=1),
        data_age_seconds=0,
        model_age_seconds=0,
        clock_drift_ms=101,
    )
    assert halted.state is RuntimeState.HALTED
    still_halted = supervisor.recover(
        kind=FaultKind.CLOCK,
        observed_at=NOW + timedelta(seconds=2),
    )
    assert still_halted.state is RuntimeState.HALTED
    recovered = supervisor.recover(
        kind=FaultKind.CLOCK,
        observed_at=NOW + timedelta(seconds=3),
        checkpoint=checkpoint,
        operator_authorized=True,
    )
    assert recovered.state is RuntimeState.RUNNING


def test_process_recovery_requires_verified_same_mode_checkpoint() -> None:
    supervisor = RuntimeSupervisor(mode=RuntimeMode.PAPER, policy=policy())
    supervisor.start(observed_at=NOW)
    checkpoint = supervisor.checkpoint()
    crashed = supervisor.fault(kind=FaultKind.PROCESS, observed_at=NOW + timedelta(seconds=1))
    assert crashed.state is RuntimeState.RECOVERING
    recovered = supervisor.recover(
        kind=FaultKind.PROCESS,
        observed_at=NOW + timedelta(seconds=2),
        checkpoint=checkpoint,
    )
    assert recovered.state is RuntimeState.RUNNING
    assert supervisor.restart_count == 1


def test_health_history_is_fixed_capacity() -> None:
    supervisor = RuntimeSupervisor(mode=RuntimeMode.PAPER, policy=policy(capacity=8))
    supervisor.start(observed_at=NOW)
    for second in range(1, 30):
        supervisor.heartbeat(
            observed_at=NOW + timedelta(seconds=second),
            data_age_seconds=0,
            model_age_seconds=0,
            clock_drift_ms=0,
        )
    assert len(supervisor.history) == 8
    assert supervisor.history[0].sequence == 23
