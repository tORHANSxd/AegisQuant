from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aegisquant.research.datasets import LeakageAuditState
from aegisquant.research.validation import (
    FeatureAccessRecord,
    FeatureSourceKind,
    LabelWindowRecord,
    NormalizationScope,
    assert_no_leakage,
    audit_leakage,
)

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)


def access(**updates: object) -> FeatureAccessRecord:
    payload: dict[str, object] = {
        "record_id": "access-1",
        "sample_id": "sample-1",
        "feature_id": "returns.log@1.0.0",
        "decision_time": NOW,
        "source_event_time": NOW - timedelta(minutes=1),
        "available_time": NOW - timedelta(seconds=1),
        "source_kind": FeatureSourceKind.FEATURE,
        "normalization_scope": NormalizationScope.TRAIN_ONLY,
    }
    payload.update(updates)
    return FeatureAccessRecord.model_validate(payload)


def test_clean_point_in_time_records_pass_active_leakage_audit() -> None:
    report = audit_leakage(
        feature_accesses=(access(),),
        label_windows=(
            LabelWindowRecord(
                sample_id="sample-1",
                decision_time=NOW,
                label_start_time=NOW + timedelta(seconds=1),
                label_end_time=NOW + timedelta(minutes=5),
            ),
        ),
        generated_at=NOW + timedelta(hours=1),
    )
    assert report.state is LeakageAuditState.PASSED
    assert report.manifest().finding_codes == ()
    assert_no_leakage(report)


def test_injected_future_and_full_sample_leaks_are_all_detected() -> None:
    future = NOW + timedelta(seconds=1)
    report = audit_leakage(
        feature_accesses=(
            access(
                source_event_time=future,
                available_time=future,
                revision_time=future,
                engagement_snapshot_time=future,
                source_kind=FeatureSourceKind.LABEL,
                normalization_scope=NormalizationScope.FULL_SAMPLE,
            ),
        ),
        label_windows=(
            LabelWindowRecord(
                sample_id="sample-1",
                decision_time=NOW,
                label_start_time=NOW,
                label_end_time=future,
            ),
        ),
        generated_at=NOW + timedelta(hours=1),
    )
    assert report.state is LeakageAuditState.FAILED
    assert {item.code for item in report.findings} == {
        "AQ-LEAKAGE-FUTURE-EVENT",
        "AQ-LEAKAGE-FUTURE-AVAILABILITY",
        "AQ-LEAKAGE-FUTURE-REVISION",
        "AQ-LEAKAGE-FUTURE-ENGAGEMENT",
        "AQ-LEAKAGE-LABEL-AS-FEATURE",
        "AQ-LEAKAGE-FULL-SAMPLE-NORMALIZATION",
        "AQ-LEAKAGE-LABEL-WINDOW-OVERLAP",
    }
    with pytest.raises(ValueError, match="AQ-RESEARCH-LEAKAGE-DETECTED"):
        assert_no_leakage(report)
