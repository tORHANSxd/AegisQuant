"""Baseline drift and out-of-distribution monitoring with fail-safe actions."""

from __future__ import annotations

import math
from decimal import Decimal
from enum import StrEnum

import numpy as np
from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import NonNegativeDecimal


class MonitoringWindow(DomainModel):
    feature_names: tuple[str, ...] = Field(min_length=1)
    features: tuple[tuple[float | None, ...], ...] = Field(min_length=2)
    predictions: tuple[float, ...] = Field(min_length=2)
    residuals: tuple[float, ...] = Field(min_length=2)
    calibration_errors: tuple[float, ...] = Field(min_length=2)
    inference_latency_ms: tuple[float, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_window(self) -> MonitoringWindow:
        rows = len(self.features)
        if any(len(row) != len(self.feature_names) for row in self.features):
            raise ValueError("monitoring feature matrix is not rectangular")
        if any(
            len(values) != rows
            for values in (
                self.predictions,
                self.residuals,
                self.calibration_errors,
                self.inference_latency_ms,
            )
        ):
            raise ValueError("monitoring window dimensions differ")
        finite = (*self.predictions, *self.residuals, *self.calibration_errors)
        if any(not math.isfinite(value) for value in finite):
            raise ValueError("monitoring values must be finite")
        if any(not math.isfinite(value) or value < 0 for value in self.inference_latency_ms):
            raise ValueError("monitoring latency must be finite and non-negative")
        return self


class DriftAction(StrEnum):
    NONE = "NONE"
    RETRAIN_PROPOSAL = "RETRAIN_PROPOSAL"
    DEGRADE = "DEGRADE"
    ABSTAIN = "ABSTAIN"


class DriftPolicy(DomainModel):
    warning_score: NonNegativeDecimal
    critical_score: NonNegativeDecimal
    ood_abstain_score: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_thresholds(self) -> DriftPolicy:
        if self.warning_score > self.critical_score:
            raise ValueError("drift warning cannot exceed critical threshold")
        return self


class DriftReport(DomainModel):
    metrics: dict[str, NonNegativeDecimal]
    aggregate_score: NonNegativeDecimal
    ood_score: NonNegativeDecimal
    action: DriftAction
    reason_codes: tuple[str, ...]


def _mean_shift(reference: tuple[float, ...], current: tuple[float, ...]) -> float:
    reference_array = np.asarray(reference, dtype=np.float64)
    current_array = np.asarray(current, dtype=np.float64)
    scale = max(float(np.std(reference_array, ddof=1)), 1e-12)
    return abs(float(np.mean(current_array)) - float(np.mean(reference_array))) / scale


def assess_drift(
    *, reference: MonitoringWindow, current: MonitoringWindow, policy: DriftPolicy
) -> DriftReport:
    if reference.feature_names != current.feature_names:
        raise ValueError("drift feature schemas differ")
    feature_scores: list[float] = []
    reference_missing = 0
    current_missing = 0
    for column in range(len(reference.feature_names)):
        reference_list: list[float] = []
        current_list: list[float] = []
        for row in reference.features:
            value = row[column]
            if value is not None:
                reference_list.append(value)
        for row in current.features:
            value = row[column]
            if value is not None:
                current_list.append(value)
        reference_values = tuple(reference_list)
        current_values = tuple(current_list)
        reference_missing += len(reference.features) - len(reference_values)
        current_missing += len(current.features) - len(current_values)
        if not reference_values or not current_values:
            feature_scores.append(10.0)
        else:
            feature_scores.append(_mean_shift(reference_values, current_values))
    missing_reference_rate = reference_missing / (
        len(reference.features) * len(reference.feature_names)
    )
    missing_current_rate = current_missing / (len(current.features) * len(current.feature_names))
    metrics_float = {
        "input_shift": max(feature_scores),
        "missingness_shift": abs(missing_current_rate - missing_reference_rate),
        "prediction_shift": _mean_shift(reference.predictions, current.predictions),
        "residual_shift": _mean_shift(reference.residuals, current.residuals),
        "calibration_shift": _mean_shift(reference.calibration_errors, current.calibration_errors),
        "latency_shift": abs(
            float(np.mean(current.inference_latency_ms))
            / max(float(np.mean(reference.inference_latency_ms)), 1e-12)
            - 1.0
        ),
    }
    aggregate = max(metrics_float.values())
    ood = max(feature_scores)
    aggregate_decimal = Decimal(format(aggregate, ".15g"))
    ood_decimal = Decimal(format(ood, ".15g"))
    if ood_decimal > policy.ood_abstain_score:
        action = DriftAction.ABSTAIN
        reasons = ("AQ-MODEL-OOD",)
    elif aggregate_decimal > policy.critical_score:
        action = DriftAction.DEGRADE
        reasons = ("AQ-MODEL-DRIFT-CRITICAL",)
    elif aggregate_decimal > policy.warning_score:
        action = DriftAction.RETRAIN_PROPOSAL
        reasons = ("AQ-MODEL-DRIFT-WARNING",)
    else:
        action = DriftAction.NONE
        reasons = ()
    return DriftReport(
        metrics={key: Decimal(format(value, ".15g")) for key, value in metrics_float.items()},
        aggregate_score=aggregate_decimal,
        ood_score=ood_decimal,
        action=action,
        reason_codes=reasons,
    )
