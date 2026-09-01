"""Accelerated P13 stability is bounded and explicitly nonqualifying."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.runtime.models import RuntimeState
from aegisquant.runtime.supervisor import StabilityEvidence, run_accelerated_stability
from tests.p12_helpers import NOW


def test_seven_logical_days_are_bounded_but_not_wall_clock_acceptance() -> None:
    evidence = run_accelerated_stability(started_at=NOW)
    assert evidence.logical_cycles == 10_080
    assert evidence.logical_duration_minutes == 10_080
    assert evidence.history_peak <= evidence.history_capacity
    assert evidence.bounded_state_verified is True
    assert evidence.restart_count == 1
    assert evidence.final_state is RuntimeState.RUNNING
    assert evidence.qualifying_wall_clock_acceptance is False
    assert evidence.deferred_by_user is True
    assert evidence.wall_clock_memory_acceptance_passed is False


def test_short_or_deferred_run_cannot_be_marked_qualifying() -> None:
    with pytest.raises(ValidationError, match="cannot qualify"):
        StabilityEvidence(
            logical_cycles=2,
            logical_duration_minutes=2,
            wall_clock_seconds=Decimal("1"),
            required_wall_clock_hours=12,
            qualifying_wall_clock_acceptance=True,
            deferred_by_user=True,
            final_state=RuntimeState.RUNNING,
            history_capacity=8,
            history_peak=2,
            restart_count=0,
            duplicate_order_count=0,
            duplicate_fill_count=0,
            unknown_funds_fact_count=0,
            rss_start_bytes=0,
            rss_end_bytes=0,
            bounded_state_verified=True,
            wall_clock_memory_acceptance_passed=False,
            reason_codes=("unsafe",),
        )
