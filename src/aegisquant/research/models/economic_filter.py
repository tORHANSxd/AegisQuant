# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Fixed-budget return filters with probability and residual calibration on validation only."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

import numpy as np
from sklearn.linear_model import LogisticRegression

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import canonical_result
from aegisquant.research.models.baselines import (
    BaselineDataset,
    BaselineModelKind,
    BaselineModelSpec,
    fit_predict_baseline,
)
from aegisquant.research.models.economic_gate import CalibrationStatus, EconomicForecast
from aegisquant.research.models.tree import TreeModelKind, TreeModelSpec, fit_predict_tree

EconomicModelFamily = Literal["XGBOOST", "LIGHTGBM", "ELASTIC_NET"]


class EconomicFilterResult(DomainModel):
    model_id: str
    family: EconomicModelFamily
    forecasts: tuple[EconomicForecast, ...]
    model_spec_sha256: str
    training_samples_sha256: str
    calibration_sha256: str | None
    training_rows: int
    validation_rows: int
    validation_positive_labels: int
    calibration_status: CalibrationStatus
    trials_consumed: Literal[1] = 1
    calibration_method: str = "validation-only Platt and residual q10/q50/q90"
    test_targets_used: Literal[False] = False
    primary_direction_source: Literal["TREND_MODULE_ONLY"] = "TREND_MODULE_ONLY"


def _decimal(value: float) -> Decimal:
    return canonical_result(Decimal(format(value, ".15g")))


def fit_economic_filter(
    *,
    family: EconomicModelFamily,
    train: BaselineDataset,
    validation: BaselineDataset,
    test: BaselineDataset,
    train_label_end_times: tuple[datetime, ...],
    validation_label_end_times: tuple[datetime, ...],
    validation_round_trip_costs: tuple[Decimal, ...],
    seed: int = 20260903,
    horizon_bars: Literal[6, 12] = 6,
) -> EconomicFilterResult:
    if (
        len(train_label_end_times) != len(train.sample_ids)
        or len(validation_label_end_times) != len(validation.sample_ids)
        or len(validation_round_trip_costs) != len(validation.sample_ids)
    ):
        raise ValueError("economic filter label/cost dimensions differ")
    if train.feature_names != validation.feature_names or train.feature_names != test.feature_names:
        raise ValueError("economic filter feature schemas differ")
    if (
        train.timestamps[-1] >= validation.timestamps[0]
        or validation.timestamps[-1] >= test.timestamps[0]
    ):
        raise ValueError("economic filter requires train -> validation -> test order")
    if (
        max(train_label_end_times) >= validation.timestamps[0]
        or max(validation_label_end_times) >= test.timestamps[0]
    ):
        raise ValueError("economic filter label horizons were not purged before the next partition")
    if any(not v.is_finite() or v < 0 for v in validation_round_trip_costs):
        raise ValueError("economic filter costs must be known finite nonnegative estimates")
    # A single fitted model produces both validation and test point forecasts.
    # Targets on the combined inference set are inert placeholders.
    combined = BaselineDataset(
        sample_ids=(*validation.sample_ids, *test.sample_ids),
        timestamps=(*validation.timestamps, *test.timestamps),
        feature_names=train.feature_names,
        features=(*validation.features, *test.features),
        targets=(0.0,) * (len(validation.sample_ids) + len(test.sample_ids)),
    )
    model_id = f"cat-{family.lower()}-h{horizon_bars}"
    if family == "ELASTIC_NET":
        linear_spec = BaselineModelSpec(
            model_id=model_id,
            kind=BaselineModelKind.ELASTIC_NET,
            seed=seed,
            alpha=Decimal("0.001"),
            l1_ratio=Decimal("0.5"),
        )
        prediction = fit_predict_baseline(spec=linear_spec, train=train, test=combined)
        point = np.asarray([float(v) for v in prediction.predictions], dtype=np.float64)
        model_hash = linear_spec.spec_sha256
    else:
        tree_spec = TreeModelSpec(
            model_id=model_id,
            kind=TreeModelKind(family),
            seed=seed,
            estimators=32,
            max_depth=3,
            learning_rate=0.05,
        )
        tree_prediction = fit_predict_tree(spec=tree_spec, train=train, test=combined)
        point = np.asarray([float(v) for v in tree_prediction.mean], dtype=np.float64)
        model_hash = canonical_sha256(tree_spec.model_dump(mode="json"))
    validation_count = len(validation.sample_ids)
    calibration_point, test_point = point[:validation_count], point[validation_count:]
    validation_truth = np.asarray(validation.targets, dtype=np.float64)
    cost = np.asarray([float(v) for v in validation_round_trip_costs], dtype=np.float64)
    labels = (validation_truth > cost).astype(np.int64)
    residual = validation_truth - calibration_point
    q10, q50, q90 = (float(v) for v in np.quantile(residual, (0.1, 0.5, 0.9)))
    mean_bias = float(np.mean(residual))
    status = CalibrationStatus.UNAVAILABLE
    evidence_hash: str | None = None
    probabilities = np.full(len(test_point), 0.5)
    if validation_count >= 30 and len(set(labels.tolist())) == 2:
        center = float(np.mean(calibration_point))
        scale = max(float(np.std(calibration_point)), 1e-8)
        calibrator = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=seed)
        calibrator.fit(((calibration_point - center) / scale).reshape(-1, 1), labels)
        probabilities = calibrator.predict_proba(((test_point - center) / scale).reshape(-1, 1))[
            :, 1
        ]
        status = CalibrationStatus.VALIDATION_CALIBRATED
        evidence_hash = canonical_sha256(
            {
                "validation_ids": validation.sample_ids,
                "validation_targets": validation.targets,
                "known_round_trip_costs": [str(v) for v in validation_round_trip_costs],
                "point_forecasts": calibration_point.tolist(),
                "residual_quantiles": [q10, q50, q90],
                "calibrator_coefficient": calibrator.coef_.tolist(),
                "calibrator_intercept": np.asarray(calibrator.intercept_).tolist(),
                "calibrated_through": max(validation_label_end_times).isoformat(),
                "seed": seed,
            }
        )
    forecasts = tuple(
        EconomicForecast(
            expected_gross_return=_decimal(float(value) + mean_bias),
            q10_return=_decimal(float(value) + q10),
            q50_return=_decimal(float(value) + q50),
            q90_return=_decimal(float(value) + q90),
            p_net_positive=_decimal(float(probability)),
            prediction_uncertainty=_decimal((q90 - q10) / 2),
            available_time=time,
            horizon_bars=horizon_bars,
            calibration_status=status,
            calibrated_through=max(validation_label_end_times)
            if evidence_hash is not None
            else None,
            calibration_sha256=evidence_hash,
        )
        for value, probability, time in zip(test_point, probabilities, test.timestamps, strict=True)
    )
    return EconomicFilterResult(
        model_id=model_id,
        family=family,
        forecasts=forecasts,
        model_spec_sha256=model_hash,
        training_samples_sha256=canonical_sha256(
            {"ids": train.sample_ids, "features": train.features, "targets": train.targets}
        ),
        calibration_sha256=evidence_hash,
        training_rows=len(train.sample_ids),
        validation_rows=validation_count,
        validation_positive_labels=int(np.sum(labels)),
        calibration_status=status,
    )
