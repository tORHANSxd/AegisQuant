"""Deterministic alert, incident timeline, and recovery-evidence contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.runtime.models import AlertSeverity, FaultKind, RuntimeState


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    MITIGATED = "MITIGATED"
    RECOVERED = "RECOVERED"


class RuntimeAlert(DomainModel):
    alert_id: str = Field(min_length=1, max_length=255)
    severity: AlertSeverity
    fault_kind: FaultKind
    raised_at: UtcDateTime
    state: RuntimeState
    new_risk_allowed: bool
    runbook_path: str = Field(pattern=r"^docs/runbooks/[A-Z0-9_]+\.md$")
    reason_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_alert(self) -> RuntimeAlert:
        if self.severity in {AlertSeverity.SEV0, AlertSeverity.SEV1} and self.new_risk_allowed:
            raise ValueError("critical runtime alert must block new risk")
        return self


class IncidentTimelineEntry(DomainModel):
    sequence: int = Field(ge=1)
    occurred_at: UtcDateTime
    event_type: str = Field(min_length=1, max_length=64)
    state: RuntimeState
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    operator_action_required: bool


class RecoveryEvidence(DomainModel):
    checkpoint_verified: bool
    duplicate_order_count: int = Field(ge=0)
    duplicate_fill_count: int = Field(ge=0)
    unknown_funds_fact_count: int = Field(ge=0)
    reconciliation_clear: bool
    recovered_mode_unchanged: bool

    @model_validator(mode="after")
    def validate_recovery(self) -> RecoveryEvidence:
        if any(
            (
                not self.checkpoint_verified,
                self.duplicate_order_count,
                self.duplicate_fill_count,
                self.unknown_funds_fact_count,
                not self.reconciliation_clear,
                not self.recovered_mode_unchanged,
            )
        ):
            raise ValueError("recovery evidence is not safe to close")
        return self


class IncidentRecord(DomainModel):
    incident_id: str = Field(min_length=1, max_length=255)
    alert: RuntimeAlert
    status: IncidentStatus
    timeline: tuple[IncidentTimelineEntry, ...] = Field(min_length=1)
    recovery_evidence: RecoveryEvidence | None
    postmortem_required: bool
    real_funds_impacted: bool = False

    @model_validator(mode="after")
    def validate_incident(self) -> IncidentRecord:
        sequences = [item.sequence for item in self.timeline]
        times = [item.occurred_at for item in self.timeline]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("incident timeline sequence must be contiguous")
        if times != sorted(times):
            raise ValueError("incident timeline time must be monotonic")
        if self.status is IncidentStatus.RECOVERED and self.recovery_evidence is None:
            raise ValueError("recovered incident requires recovery evidence")
        if self.status is not IncidentStatus.RECOVERED and self.recovery_evidence is not None:
            raise ValueError("open incident cannot carry closing evidence")
        if self.real_funds_impacted:
            raise ValueError("P13 drills cannot claim real funds impact")
        return self


RUNBOOK_BY_FAULT = {
    FaultKind.NETWORK: "docs/runbooks/VENUE_DISCONNECT.md",
    FaultKind.DATABASE: "docs/runbooks/DATABASE_FAILURE.md",
    FaultKind.MODEL: "docs/runbooks/MODEL_DRIFT.md",
    FaultKind.DATA_SOURCE: "docs/runbooks/DATA_STALE.md",
    FaultKind.CLOCK: "docs/runbooks/CLOCK_DRIFT.md",
    FaultKind.PROCESS: "docs/runbooks/PROCESS_CRASH.md",
}


def open_incident(
    *,
    incident_id: str,
    fault_kind: FaultKind,
    severity: AlertSeverity,
    occurred_at: UtcDateTime,
    state: RuntimeState,
) -> IncidentRecord:
    alert = RuntimeAlert(
        alert_id=f"alert-{incident_id}",
        severity=severity,
        fault_kind=fault_kind,
        raised_at=occurred_at,
        state=state,
        new_risk_allowed=False,
        runbook_path=RUNBOOK_BY_FAULT[fault_kind],
        reason_code=f"AQ-RUNTIME-{fault_kind.value}-FAULT",
    )
    return IncidentRecord(
        incident_id=incident_id,
        alert=alert,
        status=IncidentStatus.OPEN,
        timeline=(
            IncidentTimelineEntry(
                sequence=1,
                occurred_at=occurred_at,
                event_type="DETECTED",
                state=state,
                evidence_ids=(alert.alert_id,),
                operator_action_required=severity in {AlertSeverity.SEV0, AlertSeverity.SEV1},
            ),
        ),
        recovery_evidence=None,
        postmortem_required=severity in {AlertSeverity.SEV0, AlertSeverity.SEV1},
        real_funds_impacted=False,
    )


def close_incident(
    incident: IncidentRecord,
    *,
    recovered_at: UtcDateTime,
    evidence: RecoveryEvidence,
) -> IncidentRecord:
    if incident.status is not IncidentStatus.OPEN:
        raise ValueError("only an open incident can be recovered")
    if recovered_at < incident.timeline[-1].occurred_at:
        raise ValueError("recovery cannot precede incident timeline")
    entry = IncidentTimelineEntry(
        sequence=len(incident.timeline) + 1,
        occurred_at=recovered_at,
        event_type="RECOVERED",
        state=RuntimeState.RUNNING,
        evidence_ids=(f"recovery-{incident.incident_id}",),
        operator_action_required=False,
    )
    return IncidentRecord(
        incident_id=incident.incident_id,
        alert=incident.alert,
        status=IncidentStatus.RECOVERED,
        timeline=(*incident.timeline, entry),
        recovery_evidence=evidence,
        postmortem_required=incident.postmortem_required,
        real_funds_impacted=incident.real_funds_impacted,
    )
