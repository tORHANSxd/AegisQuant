"""Bounded runtime supervision, checkpoint verification, and stability contracts."""

from __future__ import annotations

import time
from collections import deque
from datetime import timedelta
from decimal import Decimal

import psutil
from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal
from aegisquant.runtime.models import FaultKind, RuntimeMode, RuntimeState


class RuntimePolicy(DomainModel):
    maximum_data_age_seconds: int = Field(gt=0, le=3600)
    maximum_model_age_seconds: int = Field(gt=0, le=86_400)
    maximum_clock_drift_ms: int = Field(gt=0, le=60_000)
    maximum_restarts: int = Field(ge=0, le=100)
    health_history_capacity: int = Field(ge=8, le=10_000)
    qualifying_wall_clock_hours: int = Field(default=12, ge=12, le=168)


class RuntimeHealthSample(DomainModel):
    sequence: int = Field(ge=1)
    observed_at: UtcDateTime
    state: RuntimeState
    data_age_seconds: int = Field(ge=0)
    model_age_seconds: int = Field(ge=0)
    clock_drift_ms: int = Field(ge=0)
    active_faults: tuple[FaultKind, ...]
    new_risk_allowed: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_risk_gate(self) -> RuntimeHealthSample:
        if self.new_risk_allowed != (self.state is RuntimeState.RUNNING):
            raise ValueError("only a healthy RUNNING state may allow new risk")
        return self


class SupervisorCheckpointPayload(DomainModel):
    schema_version: str = "p13-supervisor-checkpoint-v1"
    mode: RuntimeMode
    state: RuntimeState
    sequence: int = Field(ge=0)
    restart_count: int = Field(ge=0)
    last_observed_at: UtcDateTime


class SupervisorCheckpoint(DomainModel):
    payload: SupervisorCheckpointPayload
    payload_sha256: str

    @model_validator(mode="after")
    def validate_checkpoint(self) -> SupervisorCheckpoint:
        ensure_sha256(self.payload_sha256, field_name="payload_sha256")
        if self.payload_sha256 != canonical_sha256(self.payload.model_dump(mode="json")):
            raise ValueError("AQ-RUNTIME-SUPERVISOR-CHECKPOINT-HASH-MISMATCH")
        return self


class StabilityEvidence(DomainModel):
    logical_cycles: int = Field(ge=1)
    logical_duration_minutes: int = Field(ge=1)
    wall_clock_seconds: NonNegativeDecimal
    required_wall_clock_hours: int = Field(ge=12)
    qualifying_wall_clock_acceptance: bool
    deferred_by_user: bool
    final_state: RuntimeState
    history_capacity: int = Field(ge=1)
    history_peak: int = Field(ge=1)
    restart_count: int = Field(ge=0)
    duplicate_order_count: int = Field(ge=0)
    duplicate_fill_count: int = Field(ge=0)
    unknown_funds_fact_count: int = Field(ge=0)
    rss_start_bytes: int = Field(ge=0)
    rss_end_bytes: int = Field(ge=0)
    bounded_state_verified: bool
    wall_clock_memory_acceptance_passed: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_qualification(self) -> StabilityEvidence:
        required_seconds = Decimal(self.required_wall_clock_hours * 3600)
        if self.qualifying_wall_clock_acceptance and (
            self.deferred_by_user
            or self.wall_clock_seconds < required_seconds
            or not self.wall_clock_memory_acceptance_passed
        ):
            raise ValueError("accelerated or deferred run cannot qualify as wall-clock acceptance")
        if self.history_peak > self.history_capacity:
            raise ValueError("health history exceeded its configured bound")
        if self.logical_duration_minutes != self.logical_cycles:
            raise ValueError("P13 accelerated harness requires one logical minute per cycle")
        return self


class RuntimeSupervisor:
    """Fail closed on stale inputs and critical infrastructure faults."""

    def __init__(self, *, mode: RuntimeMode, policy: RuntimePolicy) -> None:
        self.mode = mode
        self.policy = policy
        self.state = RuntimeState.STOPPED
        self.restart_count = 0
        self._sequence = 0
        self._last_observed_at: UtcDateTime | None = None
        self._active_faults: set[FaultKind] = set()
        self._history: deque[RuntimeHealthSample] = deque(maxlen=policy.health_history_capacity)

    @property
    def history(self) -> tuple[RuntimeHealthSample, ...]:
        return tuple(self._history)

    @property
    def new_risk_allowed(self) -> bool:
        return self.state is RuntimeState.RUNNING

    def start(self, *, observed_at: UtcDateTime) -> RuntimeHealthSample:
        if self.state is not RuntimeState.STOPPED:
            raise ValueError("runtime can only start from STOPPED")
        self.state = RuntimeState.STARTING
        self.state = RuntimeState.RUNNING
        return self._record(
            observed_at=observed_at,
            data_age_seconds=0,
            model_age_seconds=0,
            clock_drift_ms=0,
            reason="AQ-RUNTIME-STARTED",
        )

    def heartbeat(
        self,
        *,
        observed_at: UtcDateTime,
        data_age_seconds: int,
        model_age_seconds: int,
        clock_drift_ms: int,
    ) -> RuntimeHealthSample:
        self._require_monotonic(observed_at)
        if min(data_age_seconds, model_age_seconds, clock_drift_ms) < 0:
            raise ValueError("runtime health ages and drift cannot be negative")
        if self.state is RuntimeState.HALTED:
            return self._record(
                observed_at=observed_at,
                data_age_seconds=data_age_seconds,
                model_age_seconds=model_age_seconds,
                clock_drift_ms=clock_drift_ms,
                reason="AQ-RUNTIME-HALT-LATCHED",
            )
        if clock_drift_ms > self.policy.maximum_clock_drift_ms:
            self._active_faults.add(FaultKind.CLOCK)
            self.state = RuntimeState.HALTED
            reason = "AQ-RUNTIME-CLOCK-DRIFT-HALT"
        elif data_age_seconds > self.policy.maximum_data_age_seconds:
            self._active_faults.add(FaultKind.DATA_SOURCE)
            self.state = RuntimeState.DEGRADED
            reason = "AQ-RUNTIME-DATA-STALE"
        elif model_age_seconds > self.policy.maximum_model_age_seconds:
            self._active_faults.add(FaultKind.MODEL)
            self.state = RuntimeState.DEGRADED
            reason = "AQ-RUNTIME-MODEL-STALE"
        elif self._active_faults:
            self.state = RuntimeState.DEGRADED
            reason = "AQ-RUNTIME-FAULT-STILL-ACTIVE"
        else:
            self.state = RuntimeState.RUNNING
            reason = "AQ-RUNTIME-HEALTHY"
        return self._record(
            observed_at=observed_at,
            data_age_seconds=data_age_seconds,
            model_age_seconds=model_age_seconds,
            clock_drift_ms=clock_drift_ms,
            reason=reason,
        )

    def fault(self, *, kind: FaultKind, observed_at: UtcDateTime) -> RuntimeHealthSample:
        self._require_monotonic(observed_at)
        self._active_faults.add(kind)
        if kind in {FaultKind.DATABASE, FaultKind.CLOCK}:
            self.state = RuntimeState.HALTED
        elif kind is FaultKind.PROCESS:
            self.state = (
                RuntimeState.RECOVERING
                if self.restart_count < self.policy.maximum_restarts
                else RuntimeState.HALTED
            )
        else:
            self.state = RuntimeState.DEGRADED
        return self._record(
            observed_at=observed_at,
            data_age_seconds=0,
            model_age_seconds=0,
            clock_drift_ms=0,
            reason=f"AQ-RUNTIME-{kind.value}-FAULT",
        )

    def recover(
        self,
        *,
        kind: FaultKind,
        observed_at: UtcDateTime,
        checkpoint: SupervisorCheckpoint | None = None,
        operator_authorized: bool = False,
        reconciliation_clear: bool = True,
    ) -> RuntimeHealthSample:
        self._require_monotonic(observed_at)
        if kind not in self._active_faults:
            raise ValueError("cannot recover a fault that is not active")
        if not reconciliation_clear:
            self.state = RuntimeState.HALTED
            return self._record(
                observed_at=observed_at,
                data_age_seconds=0,
                model_age_seconds=0,
                clock_drift_ms=0,
                reason="AQ-RUNTIME-RECOVERY-RECONCILIATION-DIFFERENCE",
            )
        if checkpoint is not None and checkpoint.payload.mode is not self.mode:
            raise ValueError("AQ-RUNTIME-RECOVERY-MODE-MISMATCH")
        if kind is FaultKind.PROCESS:
            if checkpoint is None:
                self.state = RuntimeState.HALTED
                return self._record(
                    observed_at=observed_at,
                    data_age_seconds=0,
                    model_age_seconds=0,
                    clock_drift_ms=0,
                    reason="AQ-RUNTIME-RECOVERY-CHECKPOINT-REQUIRED",
                )
            self.restart_count += 1
            if self.restart_count > self.policy.maximum_restarts:
                self.state = RuntimeState.HALTED
                return self._record(
                    observed_at=observed_at,
                    data_age_seconds=0,
                    model_age_seconds=0,
                    clock_drift_ms=0,
                    reason="AQ-RUNTIME-RESTART-BUDGET-EXHAUSTED",
                )
        if self.state is RuntimeState.HALTED and not operator_authorized:
            return self._record(
                observed_at=observed_at,
                data_age_seconds=0,
                model_age_seconds=0,
                clock_drift_ms=0,
                reason="AQ-RUNTIME-MANUAL-RECOVERY-REQUIRED",
            )
        if self.state is RuntimeState.HALTED and checkpoint is None:
            return self._record(
                observed_at=observed_at,
                data_age_seconds=0,
                model_age_seconds=0,
                clock_drift_ms=0,
                reason="AQ-RUNTIME-RECOVERY-CHECKPOINT-REQUIRED",
            )
        self._active_faults.remove(kind)
        self.state = RuntimeState.RUNNING if not self._active_faults else RuntimeState.DEGRADED
        return self._record(
            observed_at=observed_at,
            data_age_seconds=0,
            model_age_seconds=0,
            clock_drift_ms=0,
            reason="AQ-RUNTIME-RECOVERED",
        )

    def quiesce(self, *, observed_at: UtcDateTime) -> RuntimeHealthSample:
        self._require_monotonic(observed_at)
        self.state = RuntimeState.QUIESCED
        return self._record(
            observed_at=observed_at,
            data_age_seconds=0,
            model_age_seconds=0,
            clock_drift_ms=0,
            reason="AQ-RUNTIME-QUIESCED",
        )

    def checkpoint(self) -> SupervisorCheckpoint:
        if self._last_observed_at is None:
            raise ValueError("cannot checkpoint before runtime start")
        payload = SupervisorCheckpointPayload(
            mode=self.mode,
            state=self.state,
            sequence=self._sequence,
            restart_count=self.restart_count,
            last_observed_at=self._last_observed_at,
        )
        return SupervisorCheckpoint(
            payload=payload,
            payload_sha256=canonical_sha256(payload.model_dump(mode="json")),
        )

    def _record(
        self,
        *,
        observed_at: UtcDateTime,
        data_age_seconds: int,
        model_age_seconds: int,
        clock_drift_ms: int,
        reason: str,
    ) -> RuntimeHealthSample:
        self._sequence += 1
        self._last_observed_at = observed_at
        sample = RuntimeHealthSample(
            sequence=self._sequence,
            observed_at=observed_at,
            state=self.state,
            data_age_seconds=data_age_seconds,
            model_age_seconds=model_age_seconds,
            clock_drift_ms=clock_drift_ms,
            active_faults=tuple(sorted(self._active_faults, key=lambda item: item.value)),
            new_risk_allowed=self.new_risk_allowed,
            reason_codes=(reason,),
        )
        self._history.append(sample)
        return sample

    def _require_monotonic(self, observed_at: UtcDateTime) -> None:
        if self._last_observed_at is not None and observed_at < self._last_observed_at:
            raise ValueError("AQ-RUNTIME-SUPERVISOR-TIME-REGRESSION")


def run_accelerated_stability(
    *,
    started_at: UtcDateTime,
    logical_cycles: int = 10_080,
    history_capacity: int = 128,
) -> StabilityEvidence:
    """Exercise seven logical days quickly; never label it wall-clock acceptance."""
    if logical_cycles < 2:
        raise ValueError("stability harness requires at least two cycles")
    process = psutil.Process()
    rss_start = process.memory_info().rss
    started = time.perf_counter()
    policy = RuntimePolicy(
        maximum_data_age_seconds=120,
        maximum_model_age_seconds=3600,
        maximum_clock_drift_ms=500,
        maximum_restarts=2,
        health_history_capacity=history_capacity,
        qualifying_wall_clock_hours=12,
    )
    supervisor = RuntimeSupervisor(mode=RuntimeMode.PAPER, policy=policy)
    supervisor.start(observed_at=started_at)
    checkpoint = supervisor.checkpoint()
    restart_at = logical_cycles // 2
    history_peak = len(supervisor.history)
    for sequence in range(1, logical_cycles):
        observed_at = started_at + timedelta(minutes=sequence)
        if sequence == restart_at:
            supervisor.fault(kind=FaultKind.PROCESS, observed_at=observed_at)
            supervisor.recover(
                kind=FaultKind.PROCESS,
                observed_at=observed_at,
                checkpoint=checkpoint,
                reconciliation_clear=True,
            )
        else:
            supervisor.heartbeat(
                observed_at=observed_at,
                data_age_seconds=0,
                model_age_seconds=0,
                clock_drift_ms=0,
            )
        history_peak = max(history_peak, len(supervisor.history))
    elapsed = Decimal(str(round(time.perf_counter() - started, 6)))
    rss_end = process.memory_info().rss
    return StabilityEvidence(
        logical_cycles=logical_cycles,
        logical_duration_minutes=logical_cycles,
        wall_clock_seconds=elapsed,
        required_wall_clock_hours=12,
        qualifying_wall_clock_acceptance=False,
        deferred_by_user=True,
        final_state=supervisor.state,
        history_capacity=history_capacity,
        history_peak=history_peak,
        restart_count=supervisor.restart_count,
        duplicate_order_count=0,
        duplicate_fill_count=0,
        unknown_funds_fact_count=0,
        rss_start_bytes=rss_start,
        rss_end_bytes=rss_end,
        bounded_state_verified=history_peak <= history_capacity,
        wall_clock_memory_acceptance_passed=False,
        reason_codes=(
            "AQ-RUNTIME-ACCELERATED-NONQUALIFYING",
            "AQ-RUNTIME-WALL-CLOCK-ACCEPTANCE-DEFERRED",
        ),
    )
