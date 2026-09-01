"""P13 network/database/model/data/clock/process chaos matrix."""

from __future__ import annotations

from aegisquant.runtime.chaos import EXPECTED_STATE, run_chaos_drill
from aegisquant.runtime.models import FaultKind, RuntimeState
from tests.p12_helpers import NOW


def test_six_faults_fail_closed_then_recover_to_same_nonfunded_mode() -> None:
    for fault in FaultKind:
        result = run_chaos_drill(fault_kind=fault, started_at=NOW)
        assert result.observed_fault_state is EXPECTED_STATE[fault]
        assert result.new_risk_allowed_during_fault is False
        assert result.final_state is RuntimeState.RUNNING
        assert result.duplicate_order_count == 0
        assert result.duplicate_fill_count == 0
        assert result.unknown_funds_fact_count == 0
        assert result.venue_network_requests_performed == 0
