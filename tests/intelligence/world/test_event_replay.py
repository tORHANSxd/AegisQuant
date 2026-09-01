from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.intelligence.world.models import WorldSource
from aegisquant.intelligence.world.replay import (
    EngagementPoint,
    ReplayEvidence,
    SourceDisposition,
    SourceIncrementalMetrics,
    audit_future_engagement,
    audit_pretrend_and_placebo,
    evaluate_source_increment,
    replay_content_as_of,
    run_latency_stress,
)
from tests.intelligence.world.helpers import NOW, revision


def _revision_ledger():
    first_time = datetime(2026, 9, 1, 10, tzinfo=UTC)
    update_time = datetime(2026, 9, 1, 11, tzinfo=UTC)
    delete_time = datetime(2026, 9, 1, 13, tzinfo=UTC)
    return (
        revision(available_at=first_time),
        revision(
            revision_number=2, text="Bitcoin upgrade schedule corrected", available_at=update_time
        ),
        revision(
            revision_number=3,
            text=None,
            available_at=delete_time,
            deleted_at=delete_time,
        ),
    )


def _engagement_ledger():
    return (
        EngagementPoint(
            snapshot_id="engagement-1",
            content_id="content-1",
            observed_at=datetime(2026, 9, 1, 10, 30, tzinfo=UTC),
            available_at=datetime(2026, 9, 1, 10, 31, tzinfo=UTC),
            metrics={"likes": 10},
        ),
        EngagementPoint(
            snapshot_id="engagement-future",
            content_id="content-1",
            observed_at=datetime(2026, 9, 1, 12, 30, tzinfo=UTC),
            available_at=datetime(2026, 9, 1, 12, 31, tzinfo=UTC),
            metrics={"likes": 1000},
        ),
    )


def test_replay_preserves_first_update_delete_and_point_in_time_engagement() -> None:
    before_delete = replay_content_as_of(
        revisions=_revision_ledger(), engagement=_engagement_ledger(), as_of_time=NOW
    )
    after_delete = replay_content_as_of(
        revisions=_revision_ledger(),
        engagement=_engagement_ledger(),
        as_of_time=datetime(2026, 9, 1, 14, tzinfo=UTC),
    )
    assert before_delete.revision.revision == 2
    assert before_delete.engagement is not None
    assert before_delete.engagement.snapshot_id == "engagement-1"
    assert before_delete.excluded_future_engagement_count == 1
    assert after_delete.revision.revision == 3 and after_delete.deleted_as_of is True


def test_replay_rejects_ledger_that_lost_the_first_version() -> None:
    with pytest.raises(ValueError, match="retain the first"):
        replay_content_as_of(revisions=_revision_ledger()[1:], engagement=(), as_of_time=NOW)


def test_future_engagement_audit_never_reads_later_popularity() -> None:
    audit = audit_future_engagement(
        content_id="content-1", snapshots=_engagement_ledger(), as_of_time=NOW
    )
    assert audit.selected_snapshot_id == "engagement-1"
    assert audit.excluded_future_snapshot_ids == ("engagement-future",)
    assert audit.passed is True


def test_latency_stress_recomputes_eligibility_at_all_required_delays() -> None:
    evidence = (
        ReplayEvidence(
            evidence_id="early",
            source_family_id="family-a",
            available_at=NOW - timedelta(minutes=20),
            directional_score=Decimal("0.5"),
        ),
        ReplayEvidence(
            evidence_id="late",
            source_family_id="family-b",
            available_at=NOW - timedelta(seconds=20),
            directional_score=Decimal("-0.5"),
        ),
        ReplayEvidence(
            evidence_id="repost",
            source_family_id="family-a",
            available_at=NOW - timedelta(minutes=15),
            directional_score=Decimal("0.9"),
        ),
    )
    report = run_latency_stress(evidence=evidence, decision_time=NOW)
    assert tuple(item.delay_seconds for item in report.scenarios) == (5, 30, 120, 600)
    assert report.scenarios[0].independent_family_count == 2
    assert report.scenarios[1].independent_family_count == 1
    assert report.scenarios[-1].independent_family_count == 1


def test_pretrend_and_placebo_preserve_negative_audit_results() -> None:
    passing = audit_pretrend_and_placebo(
        pre_event_returns=(Decimal("0.001"), Decimal("-0.001")),
        post_event_returns=(Decimal("0.02"), Decimal("0.01")),
        placebo_returns=(Decimal("0.001"), Decimal("0")),
    )
    failing = audit_pretrend_and_placebo(
        pre_event_returns=(Decimal("0.02"), Decimal("0.01")),
        post_event_returns=(Decimal("0.02"), Decimal("0.01")),
        placebo_returns=(Decimal("0.03"), Decimal("0.02")),
    )
    assert passing.passed is True
    assert failing.passed is False
    assert failing.pretrend_detected and failing.placebo_warning


@pytest.mark.parametrize(
    ("event_value", "risk_value", "coverage", "reliability", "expected"),
    [
        ("0.1", "0", "0.8", "0.8", SourceDisposition.RETAIN),
        ("0", "0.1", "0.8", "0.7", SourceDisposition.RISK_ONLY),
        ("0", "0", "0.1", "0.3", SourceDisposition.RETIRE),
        ("0", "0", "0.8", "0.8", SourceDisposition.MONITOR),
    ],
)
def test_no_increment_source_can_be_retained_for_risk_or_retired(
    event_value: str,
    risk_value: str,
    coverage: str,
    reliability: str,
    expected: SourceDisposition,
) -> None:
    decision = evaluate_source_increment(
        SourceIncrementalMetrics(
            source=WorldSource.GDELT,
            event_incremental_value=Decimal(event_value),
            risk_incremental_value=Decimal(risk_value),
            coverage=Decimal(coverage),
            reliability=Decimal(reliability),
            evaluation_windows=4,
        )
    )
    assert decision.disposition is expected
