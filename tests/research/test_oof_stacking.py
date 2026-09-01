from __future__ import annotations

from decimal import Decimal

import pytest

from aegisquant.research.models.ensemble import (
    OofFoldPrediction,
    assemble_oof,
    fit_oof_stacker,
    smooth_weights,
)


def test_oof_predictions_never_include_training_samples_and_weights_are_capped() -> None:
    folds = (
        OofFoldPrediction(
            fold_id="f1",
            train_sample_ids=("s3", "s4"),
            validation_sample_ids=("s1", "s2"),
            predictions={"a": (Decimal("1"), Decimal("2")), "b": (Decimal("0"), Decimal("0"))},
        ),
        OofFoldPrediction(
            fold_id="f2",
            train_sample_ids=("s1", "s2"),
            validation_sample_ids=("s3", "s4"),
            predictions={"a": (Decimal("3"), Decimal("4")), "b": (Decimal("0"), Decimal("0"))},
        ),
    )
    matrix = assemble_oof(folds, expected_sample_ids=("s1", "s2", "s3", "s4"))
    weights = fit_oof_stacker(
        matrix=matrix,
        targets=(Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")),
        maximum_weight=Decimal("0.7"),
    )
    assert sum(weights.weights.values(), Decimal("0")) == Decimal("1")
    assert max(weights.weights.values()) <= Decimal("0.7")
    smoothed = smooth_weights(previous=weights, proposed=weights, maximum_step=Decimal("0.1"))
    assert smoothed == weights

    with pytest.raises(ValueError, match="overlap"):
        OofFoldPrediction(
            fold_id="bad",
            train_sample_ids=("s1",),
            validation_sample_ids=("s1",),
            predictions={"a": (Decimal("1"),)},
        )
