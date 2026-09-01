from __future__ import annotations

from pathlib import Path

import pytest

from aegisquant.research.models.foundation import (
    FOUNDATION_MODELS,
    FoundationCapability,
    evaluate_chronos2,
)


def test_foundation_plugins_record_revision_license_size_and_weight_hash() -> None:
    assert {item.family for item in FOUNDATION_MODELS} == {
        "CHRONOS_2",
        "MOIRAI_2",
        "TIMESFM_3",
        "KRONOS",
    }
    assert all(len(item.revision) == 40 for item in FOUNDATION_MODELS)
    assert all(len(item.weight_sha256) == 64 for item in FOUNDATION_MODELS)
    assert all(item.weight_size_bytes > 0 for item in FOUNDATION_MODELS)
    assert FOUNDATION_MODELS[0].capability is FoundationCapability.EVALUABLE
    assert all(not item.production_allowed for item in FOUNDATION_MODELS[1:])


def test_chronos_finite_evaluation_rejects_unbounded_request_before_download(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="bounds"):
        evaluate_chronos2(context=(1.0, 2.0), prediction_length=1, cache_dir=tmp_path)
    assert not any(tmp_path.iterdir())
