"""Alert/runbook binding and SEV recovery-evidence tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aegisquant.runtime.chaos import run_all_chaos_drills
from aegisquant.runtime.incidents import IncidentStatus, RecoveryEvidence
from aegisquant.runtime.models import AlertSeverity, FaultKind
from tests.p12_helpers import NOW


def test_every_fault_drill_has_critical_alert_timeline_runbook_and_recovery() -> None:
    drills = run_all_chaos_drills(started_at=NOW)
    assert {item.fault_kind for item in drills} == set(FaultKind)
    for drill in drills:
        assert drill.severity in {AlertSeverity.SEV0, AlertSeverity.SEV1}
        assert drill.incident.status is IncidentStatus.RECOVERED
        assert len(drill.incident.timeline) == 2
        assert drill.runbook_path == drill.incident.alert.runbook_path
        assert drill.incident.recovery_evidence is not None
        assert drill.incident.postmortem_required is True
        assert drill.real_funds_impacted is False


def test_recovery_evidence_rejects_unknown_funds_or_duplicates() -> None:
    with pytest.raises(ValidationError, match="not safe to close"):
        RecoveryEvidence(
            checkpoint_verified=True,
            duplicate_order_count=1,
            duplicate_fill_count=0,
            unknown_funds_fact_count=0,
            reconciliation_clear=True,
            recovered_mode_unchanged=True,
        )
