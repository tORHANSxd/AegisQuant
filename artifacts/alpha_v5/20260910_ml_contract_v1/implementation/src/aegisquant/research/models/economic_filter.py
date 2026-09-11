# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Fixed-budget return filters with probability and residual calibration on validation only."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

import numpy as np
from pydantic import Field
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
from aegisquant.research.models.economic_gate import (
    CalibrationStatus,
    EconomicForecast,
    PointForecastStatus,
)
from aegisquant.research.models.tree import TreeModelKind, TreeModelSpec, fit_predict_tree
from aegisquant.research.validation.ml_contract import (
    FitProvenance,
    FoldRegistration,
    OOFPrediction,
    validate_oof_alignment,
    validate_prediction_dependencies,
    validate_registered_fit,
)
from aegisquant.research.validation.splits import SampleSpan

EconomicModelFamily = Literal["XGBOOST", "LIGHTGBM", "ELASTIC_NET", "CONSTANT"]


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
    raw_prediction_std: float = 0.0
    mean_bias: float = 0.0
    effective_coefficient_count: int | None = None
    intercept: Decimal | None = None
    coefficients: tuple[Decimal, ...] | None = None
    target_standard_deviation: float = 0.0
    regularization_alpha: Decimal | None = None
    oof_provenance_sha256: str | None = Field(default=None, exclude_if=lambda v: v is None)
    fitted_model_provenance_sha256: str | None = Field(default=None, exclude_if=lambda v: v is None)


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
    holding_intervals: int | None = None,
    oof_predictions: tuple[OOFPrediction, ...] | None = None,
    fit_provenance: FitProvenance | None = None,
    evaluation_spans: tuple[SampleSpan, ...] | None = None,
    registrations: tuple[FoldRegistration, ...] | None = None,
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
        oof_predictions is None and train.timestamps[-1] >= validation.timestamps[0]
    ) or validation.timestamps[-1] >= test.timestamps[0]:
        raise ValueError("economic filter requires train -> validation -> test order")
    if (oof_predictions is None and max(train_label_end_times) >= validation.timestamps[0]) or max(
        validation_label_end_times
    ) >= test.timestamps[0]:
        raise ValueError("economic filter label horizons were not purged before the next partition")
    if any(not v.is_finite() or v < 0 for v in validation_round_trip_costs):
        raise ValueError("economic filter costs must be known finite nonnegative estimates")
    oof_hash = None
    if oof_predictions is not None:
        if (
            fit_provenance is None
            or evaluation_spans is None
            or registrations is None
            or fit_provenance.scope != "PURGED_OUTER_TRAIN"
        ):
            raise ValueError("OOF mode requires outer fit and evaluation provenance")
        registered_outer = validate_registered_fit(fit_provenance, registrations)
        oof_hash = validate_oof_alignment(
            oof_predictions,
            sample_ids=validation.sample_ids,
            timestamps=validation.timestamps,
            label_end_times=validation_label_end_times,
            consumed_at=test.timestamps[0],
            registrations=registrations,
        )
        if registered_outer.evaluation_spans != evaluation_spans:
            raise ValueError("evaluation spans differ from the current registered outer fold")
        for record in oof_predictions:
            registered_inner = validate_registered_fit(record.fit, registrations)
            if (
                registered_inner.outer_fold_id != registered_outer.fold_id
                or record.sample not in registered_outer.training_spans
                or any(
                    item not in registered_outer.training_spans
                    for item in registered_inner.training_spans
                )
            ):
                raise ValueError("OOF sample/fit must belong to the current outer training fold")
        if (
            tuple(item.sample_id for item in fit_provenance.training_spans) != train.sample_ids
            or tuple(item.group_time for item in fit_provenance.training_spans) != train.timestamps
            or tuple(item.label_end_time for item in fit_provenance.training_spans)
            != train_label_end_times
            or fit_provenance.training_payload_sha256
            != canonical_sha256(
                {"ids": train.sample_ids, "features": train.features, "targets": train.targets}
            )
        ):
            raise ValueError("outer fit provenance does not bind the actual training payload")
        if (
            tuple(item.sample_id for item in evaluation_spans) != test.sample_ids
            or tuple(item.group_time for item in evaluation_spans) != test.timestamps
        ):
            raise ValueError("evaluation provenance does not align with inference")
        for span in evaluation_spans:
            validate_prediction_dependencies(fit_provenance, span, span.group_time)
    elif fit_provenance is not None or evaluation_spans is not None or registrations is not None:
        raise ValueError("fit/evaluation provenance requires OOF mode")
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
    coefficients = intercept = alpha = None
    if family == "ELASTIC_NET":
        linear_spec = BaselineModelSpec(
            model_id=model_id,
            kind=BaselineModelKind.ELASTIC_NET,
            seed=seed,
            alpha=Decimal("0.001"),
            l1_ratio=Decimal("0.5"),
        )
        if (
            fit_provenance is not None
            and fit_provenance.model_specification_sha256 != linear_spec.spec_sha256
        ):
            raise ValueError("outer model specification hash mismatch")
        prediction = fit_predict_baseline(spec=linear_spec, train=train, test=combined)
        point = np.asarray([float(v) for v in prediction.predictions], dtype=np.float64)
        model_hash = linear_spec.spec_sha256
        coefficients, intercept, alpha = (
            prediction.coefficients,
            prediction.intercept,
            linear_spec.alpha,
        )
    elif family == "CONSTANT":
        model_hash = canonical_sha256(
            {"family": "CONSTANT", "rule": "TRAIN_MEAN_SAME_CALIBRATION", "seed": seed}
        )
        if fit_provenance is not None and fit_provenance.model_specification_sha256 != model_hash:
            raise ValueError("outer model specification hash mismatch")
        point = np.full(len(combined.sample_ids), np.mean(train.targets), dtype=np.float64)
    else:
        tree_spec = TreeModelSpec(
            model_id=model_id,
            kind=TreeModelKind(family),
            seed=seed,
            estimators=32,
            max_depth=3,
            learning_rate=0.05,
        )
        if (
            fit_provenance is not None
            and fit_provenance.model_specification_sha256
            != canonical_sha256(tree_spec.model_dump(mode="json"))
        ):
            raise ValueError("outer model specification hash mismatch")
        tree_prediction = fit_predict_tree(spec=tree_spec, train=train, test=combined)
        point = np.asarray([float(v) for v in tree_prediction.mean], dtype=np.float64)
        model_hash = canonical_sha256(tree_spec.model_dump(mode="json"))
    validation_count = len(validation.sample_ids)
    calibration_point, test_point = point[:validation_count], point[validation_count:]
    if oof_predictions is not None:
        calibration_point = np.asarray(
            [float(item.prediction) for item in oof_predictions], dtype=np.float64
        )
    validation_truth = np.asarray(validation.targets, dtype=np.float64)
    cost = np.asarray([float(v) for v in validation_round_trip_costs], dtype=np.float64)
    labels = (validation_truth > cost).astype(np.int64)
    residual = validation_truth - calibration_point
    q10, q50, q90 = (float(v) for v in np.quantile(residual, (0.1, 0.5, 0.9)))
    mean_bias = float(np.mean(residual))
    component_hash = canonical_sha256(
        {
            "validation_ids": validation.sample_ids,
            "validation_targets": validation.targets,
            "point_forecasts": calibration_point.tolist(),
            "residual_quantiles": [q10, q50, q90],
            "mean_bias": mean_bias,
            "calibrated_through": max(validation_label_end_times).isoformat(),
            "seed": seed,
        }
    )
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
            raw_prediction=_decimal(float(value)),
            mean_bias=_decimal(mean_bias),
            trained_through=max(train_label_end_times),
            point_forecast_status=PointForecastStatus.AVAILABLE,
            residual_calibration_status=CalibrationStatus.VALIDATION_CALIBRATED
            if validation_count >= 30
            else CalibrationStatus.UNAVAILABLE,
            probability_calibration_status=status,
            residual_calibrated_through=max(validation_label_end_times),
            probability_calibrated_through=max(validation_label_end_times)
            if evidence_hash
            else None,
            component_evidence_sha256=component_hash,
            label_contract_version="holding-intervals-v2"
            if holding_intervals is not None
            else "decision-offset-v1",
            holding_intervals=holding_intervals
            if holding_intervals is not None
            else horizon_bars - 1,
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
        raw_prediction_std=float(np.std(test_point)),
        mean_bias=mean_bias,
        coefficients=coefficients,
        intercept=intercept,
        regularization_alpha=alpha,
        effective_coefficient_count=sum(value != 0 for value in coefficients)
        if coefficients is not None
        else None,
        target_standard_deviation=float(np.std(train.targets)),
        oof_provenance_sha256=oof_hash,
        fitted_model_provenance_sha256=canonical_sha256(fit_provenance.model_dump(mode="json"))
        if fit_provenance
        else None,
        calibration_method="purged OOF Platt and residual q10/q50/q90"
        if oof_hash
        else "validation-only Platt and residual q10/q50/q90",
    )
