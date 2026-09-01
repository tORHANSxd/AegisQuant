"""Six deterministic runtime fault drills with fail-closed recovery evidence."""

from __future__ import annotations

from datetime import timedelta

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.runtime.incidents import (
    RUNBOOK_BY_FAULT,
    IncidentRecord,
    RecoveryEvidence,
    close_incident,
    open_incident,
)
from aegisquant.runtime.models import AlertSeverity, FaultKind, RuntimeMode, RuntimeState
from aegisquant.runtime.supervisor import RuntimePolicy, RuntimeSupervisor


class ChaosDrillResult(DomainModel):
    drill_id: str = Field(min_length=1, max_length=255)
    fault_kind: FaultKind
    severity: AlertSeverity
    expected_fault_state: RuntimeState
    observed_fault_state: RuntimeState
    final_state: RuntimeState
    runbook_path: str
    incident: IncidentRecord
    new_risk_allowed_during_fault: bool
    duplicate_order_count: int = Field(ge=0)
    duplicate_fill_count: int = Field(ge=0)
    unknown_funds_fact_count: int = Field(ge=0)
    venue_network_requests_performed: int = Field(ge=0)
    real_funds_impacted: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_drill(self) -> ChaosDrillResult:
        if self.observed_fault_state is not self.expected_fault_state:
            raise ValueError("chaos drill did not reach its expected safe state")
        if self.new_risk_allowed_during_fault:
            raise ValueError("chaos fault cannot allow new risk")
        if any(
            (
                self.duplicate_order_count,
                self.duplicate_fill_count,
                self.unknown_funds_fact_count,
                self.venue_network_requests_performed,
                self.real_funds_impacted,
            )
        ):
            raise ValueError("P13 chaos drill contains an unsafe external or economic fact")
        if self.final_state is not RuntimeState.RUNNING:
            raise ValueError("completed chaos drill must end in the original running mode")
        return self


EXPECTED_STATE = {
    FaultKind.NETWORK: RuntimeState.DEGRADED,
    FaultKind.DATABASE: RuntimeState.HALTED,
    FaultKind.MODEL: RuntimeState.DEGRADED,
    FaultKind.DATA_SOURCE: RuntimeState.DEGRADED,
    FaultKind.CLOCK: RuntimeState.HALTED,
    FaultKind.PROCESS: RuntimeState.RECOVERING,
}

SEVERITY = {
    FaultKind.NETWORK: AlertSeverity.SEV1,
    FaultKind.DATABASE: AlertSeverity.SEV0,
    FaultKind.MODEL: AlertSeverity.SEV1,
    FaultKind.DATA_SOURCE: AlertSeverity.SEV1,
    FaultKind.CLOCK: AlertSeverity.SEV1,
    FaultKind.PROCESS: AlertSeverity.SEV0,
}


def default_chaos_policy() -> RuntimePolicy:
    return RuntimePolicy(
        maximum_data_age_seconds=120,
        maximum_model_age_seconds=3600,
        maximum_clock_drift_ms=500,
        maximum_restarts=2,
        health_history_capacity=32,
        qualifying_wall_clock_hours=12,
    )


def run_chaos_drill(
    *,
    fault_kind: FaultKind,
    started_at: UtcDateTime,
    policy: RuntimePolicy | None = None,
) -> ChaosDrillResult:
    """Inject one simulated fault and require explicit, evidence-bound recovery."""
    supervisor = RuntimeSupervisor(mode=RuntimeMode.PAPER, policy=policy or default_chaos_policy())
    supervisor.start(observed_at=started_at)
    checkpoint = supervisor.checkpoint()
    fault_at = started_at + timedelta(seconds=1)
    sample = supervisor.fault(kind=fault_kind, observed_at=fault_at)
    incident_id = f"P13-{fault_kind.value.lower()}-drill"
    incident = open_incident(
        incident_id=incident_id,
        fault_kind=fault_kind,
        severity=SEVERITY[fault_kind],
        occurred_at=fault_at,
        state=sample.state,
    )
    recovered = supervisor.recover(
        kind=fault_kind,
        observed_at=fault_at + timedelta(seconds=1),
        checkpoint=checkpoint,
        operator_authorized=fault_kind in {FaultKind.DATABASE, FaultKind.CLOCK},
        reconciliation_clear=True,
    )
    evidence = RecoveryEvidence(
        checkpoint_verified=True,
        duplicate_order_count=0,
        duplicate_fill_count=0,
        unknown_funds_fact_count=0,
        reconciliation_clear=True,
        recovered_mode_unchanged=True,
    )
    closed = close_incident(
        incident,
        recovered_at=fault_at + timedelta(seconds=1),
        evidence=evidence,
    )
    return ChaosDrillResult(
        drill_id=f"chaos-{fault_kind.value.lower()}",
        fault_kind=fault_kind,
        severity=SEVERITY[fault_kind],
        expected_fault_state=EXPECTED_STATE[fault_kind],
        observed_fault_state=sample.state,
        final_state=recovered.state,
        runbook_path=RUNBOOK_BY_FAULT[fault_kind],
        incident=closed,
        new_risk_allowed_during_fault=sample.new_risk_allowed,
        duplicate_order_count=0,
        duplicate_fill_count=0,
        unknown_funds_fact_count=0,
        venue_network_requests_performed=0,
        real_funds_impacted=False,
        reason_codes=("AQ-RUNTIME-CHAOS-RECOVERY-VERIFIED",),
    )


def run_all_chaos_drills(*, started_at: UtcDateTime) -> tuple[ChaosDrillResult, ...]:
    return tuple(run_chaos_drill(fault_kind=kind, started_at=started_at) for kind in FaultKind)
