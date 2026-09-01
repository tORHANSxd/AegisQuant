from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aegisquant.domain.intelligence import QualityState
from aegisquant.features import FeatureSetManifest
from aegisquant.labels import LabelSetManifest
from aegisquant.research.datasets import (
    CostAssumptionManifest,
    DataQualityReport,
    DatasetManifest,
    LeakageAuditManifest,
    LeakageAuditState,
    SplitManifest,
    TrainingManifestBundle,
    UniverseManifest,
)

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)


def bundle_payload() -> dict[str, object]:
    return {
        "dataset": DatasetManifest(
            dataset_id="research-v1",
            dataset_sha256="a" * 64,
            row_count=100,
            starts_at=NOW,
            ends_at=NOW + timedelta(days=30),
            source_dataset_ids=("market-v1", "events-v1"),
            created_at=NOW + timedelta(days=31),
        ),
        "feature_set": FeatureSetManifest(
            feature_set_id="features-v1",
            definition_hashes=("b" * 64,),
            created_at=NOW,
        ),
        "label_set": LabelSetManifest(
            label_set_id="labels-v1",
            definition_hashes=("c" * 64,),
            created_at=NOW,
        ),
        "universe": UniverseManifest(
            universe_id="universe-v1",
            snapshot_hashes=("d" * 64,),
            point_in_time=True,
            created_at=NOW,
        ),
        "split": SplitManifest(
            split_id="split-v1",
            split_sha256="e" * 64,
            policy_id="walk-forward-v1",
            fold_hashes=("f" * 64,),
            final_holdout_id="holdout-v1",
            shuffle=False,
            created_at=NOW,
        ),
        "costs": CostAssumptionManifest(
            policy_version="cost-v1",
            policy_sha256="1" * 64,
            components=("fee", "spread", "slippage", "impact", "funding", "borrow"),
            created_at=NOW,
        ),
        "quality": DataQualityReport(
            quality_state=QualityState.GOOD,
            checked_rows=100,
            missing_fraction=0.0,
            stale_fraction=0.0,
            issues=(),
            generated_at=NOW,
        ),
        "leakage": LeakageAuditManifest(
            audit_id="audit-v1",
            state=LeakageAuditState.PASSED,
            checked_records=100,
            finding_codes=(),
            generated_at=NOW,
        ),
    }


def test_training_requires_all_eight_content_addressed_manifests() -> None:
    bundle = TrainingManifestBundle.model_validate(bundle_payload())
    assert len(bundle.bundle_sha256) == 64
    assert set(type(bundle).model_fields) == {
        "dataset",
        "feature_set",
        "label_set",
        "universe",
        "split",
        "costs",
        "quality",
        "leakage",
    }
    missing = bundle_payload()
    missing.pop("leakage")
    with pytest.raises(ValidationError, match="leakage"):
        TrainingManifestBundle.model_validate(missing)


def test_training_fails_closed_on_bad_quality_or_leakage() -> None:
    degraded = bundle_payload()
    degraded["quality"] = DataQualityReport(
        quality_state=QualityState.DEGRADED,
        checked_rows=100,
        missing_fraction=0.1,
        stale_fraction=0.0,
        issues=("missing",),
        generated_at=NOW,
    )
    with pytest.raises(ValidationError, match="DATA-QUALITY-NOT-GOOD"):
        TrainingManifestBundle.model_validate(degraded)

    leaked = bundle_payload()
    leaked["leakage"] = LeakageAuditManifest(
        audit_id="audit-failed",
        state=LeakageAuditState.FAILED,
        checked_records=100,
        finding_codes=("AQ-LEAKAGE-FUTURE-AVAILABILITY",),
        generated_at=NOW,
    )
    with pytest.raises(ValidationError, match="LEAKAGE-AUDIT-FAILED"):
        TrainingManifestBundle.model_validate(leaked)
