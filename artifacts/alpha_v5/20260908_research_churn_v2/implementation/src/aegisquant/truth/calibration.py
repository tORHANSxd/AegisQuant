# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Temporal Truth Council, probability calibration, and calibration metrics."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final, Literal, Self

import numpy as np
from pydantic import Field, model_validator
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ArtifactId, ClaimId
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval
from aegisquant.research.validation.splits import (
    SampleSpan,
    TemporalFold,
    TemporalSplitPolicy,
    walk_forward_splits,
)
from aegisquant.truth.features import (
    MODEL_FEATURE_NAMES,
    EvidenceFeatureVector,
    TruthCalibrationKey,
)

_EPSILON: Final = 1e-9
_MODEL_IDS: Final = {
    "LOGISTIC_BASELINE": "truth-logistic-baseline-v1",
    "GRADIENT_BOOSTING": "truth-gradient-boosting-v1",
    "BAYESIAN_HIERARCHICAL": "truth-bayesian-hierarchical-v1",
}


def _decimal(value: float) -> Decimal:
    if not math.isfinite(value):
        raise ValueError("AQ-TRUTH-NONFINITE-METRIC")
    return Decimal(format(value, ".15g"))


def _clamp_probability(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("AQ-TRUTH-NONFINITE-PROBABILITY")
    return min(max(value, _EPSILON), 1.0 - _EPSILON)


class TruthCalibrationSample(DomainModel):
    """One resolved claim whose feature and label availability are both explicit."""

    sample_id: str = Field(min_length=1)
    claim_id: ClaimId
    features: EvidenceFeatureVector
    truth_label: Literal[0, 1]
    decision_time: UtcDateTime
    resolved_at: UtcDateTime
    label_available_at: UtcDateTime
    label_sha256: str
    sample_version: str = Field(min_length=1)
    created_at: UtcDateTime
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_sample(self) -> Self:
        ensure_sha256(self.label_sha256, field_name="label_sha256")
        if not self.sample_id.strip() or not self.sample_version.strip():
            raise ValueError("AQ-TRUTH-EMPTY-CALIBRATION-SAMPLE-FIELD")
        if self.features.claim_id != self.claim_id:
            raise ValueError("AQ-TRUTH-CALIBRATION-FEATURE-CLAIM-MISMATCH")
        if (
            self.features.extracted_at != self.decision_time
            or self.features.available_at != self.decision_time
        ):
            raise ValueError("AQ-TRUTH-CALIBRATION-FEATURE-SNAPSHOT-MISMATCH")
        if not (
            self.decision_time
            < self.resolved_at
            <= self.label_available_at
            <= self.created_at
            <= self.available_at
        ):
            raise ValueError("AQ-TRUTH-CALIBRATION-LABEL-TIME-ORDER")
        return self

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class ReliabilityBin(DomainModel):
    bin_index: int = Field(ge=0)
    lower_bound: UnitInterval
    upper_bound: UnitInterval
    sample_count: int = Field(ge=0)
    mean_probability: UnitInterval | None
    observed_frequency: UnitInterval | None

    @model_validator(mode="after")
    def validate_bin(self) -> Self:
        if self.lower_bound > self.upper_bound:
            raise ValueError("AQ-TRUTH-RELIABILITY-BIN-ORDER")
        populated = self.mean_probability is not None and self.observed_frequency is not None
        if populated != (self.sample_count > 0):
            raise ValueError("AQ-TRUTH-RELIABILITY-BIN-POPULATION-MISMATCH")
        return self


class TruthCalibrationMetrics(DomainModel):
    sample_count: int = Field(gt=0)
    brier_score: NonNegativeDecimal
    log_loss: NonNegativeDecimal
    expected_calibration_error: NonNegativeDecimal
    maximum_calibration_error: NonNegativeDecimal
    calibration_slope: FiniteDecimal | None
    calibration_intercept: FiniteDecimal | None
    precision: UnitInterval
    recall: UnitInterval
    specificity: UnitInterval
    f1: UnitInterval
    pr_auc: UnitInterval
    high_confidence_sample_count: int = Field(ge=0)
    high_confidence_accuracy: UnitInterval
    reliability_diagram: tuple[ReliabilityBin, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        if sum(item.sample_count for item in self.reliability_diagram) != self.sample_count:
            raise ValueError("AQ-TRUTH-RELIABILITY-DIAGRAM-COUNT-MISMATCH")
        if self.high_confidence_sample_count > self.sample_count:
            raise ValueError("AQ-TRUTH-HIGH-CONFIDENCE-COUNT-MISMATCH")
        if (self.calibration_slope is None) != (self.calibration_intercept is None):
            raise ValueError("AQ-TRUTH-CALIBRATION-LINE-PARTIAL")
        return self


def evaluate_truth_probabilities(
    *,
    probabilities: tuple[Decimal, ...],
    labels: tuple[int, ...],
    bin_count: int = 10,
) -> TruthCalibrationMetrics:
    """Compute classification and calibration metrics with a fixed reliability diagram."""

    if len(probabilities) != len(labels) or not probabilities:
        raise ValueError("AQ-TRUTH-CALIBRATION-DIMENSION-MISMATCH")
    if bin_count < 2:
        raise ValueError("AQ-TRUTH-CALIBRATION-BIN-COUNT")
    if set(labels) - {0, 1}:
        raise ValueError("AQ-TRUTH-NONBINARY-LABEL")
    probability_values = tuple(_clamp_probability(float(value)) for value in probabilities)
    label_values = tuple(int(value) for value in labels)
    count = len(label_values)
    brier = (
        sum(
            (probability - label) ** 2
            for probability, label in zip(probability_values, label_values, strict=True)
        )
        / count
    )
    log_loss = (
        -sum(
            label * math.log(probability) + (1 - label) * math.log(1.0 - probability)
            for probability, label in zip(probability_values, label_values, strict=True)
        )
        / count
    )

    members_by_bin: dict[int, list[int]] = defaultdict(list)
    for index, probability in enumerate(probability_values):
        members_by_bin[min(int(probability * bin_count), bin_count - 1)].append(index)
    reliability: list[ReliabilityBin] = []
    weighted_error = 0.0
    maximum_error = 0.0
    for bin_index in range(bin_count):
        members = members_by_bin[bin_index]
        lower = Decimal(bin_index) / Decimal(bin_count)
        upper = Decimal(bin_index + 1) / Decimal(bin_count)
        if members:
            mean_probability = sum(probability_values[index] for index in members) / len(members)
            observed = sum(label_values[index] for index in members) / len(members)
            error = abs(mean_probability - observed)
            weighted_error += error * len(members) / count
            maximum_error = max(maximum_error, error)
            mean_decimal: Decimal | None = _decimal(mean_probability)
            observed_decimal: Decimal | None = _decimal(observed)
        else:
            mean_decimal = None
            observed_decimal = None
        reliability.append(
            ReliabilityBin(
                bin_index=bin_index,
                lower_bound=lower,
                upper_bound=upper,
                sample_count=len(members),
                mean_probability=mean_decimal,
                observed_frequency=observed_decimal,
            )
        )

    positives = sum(label_values)
    negatives = count - positives
    predicted_positive = tuple(value >= 0.5 for value in probability_values)
    true_positive = sum(
        predicted and label == 1
        for predicted, label in zip(predicted_positive, label_values, strict=True)
    )
    false_positive = sum(
        predicted and label == 0
        for predicted, label in zip(predicted_positive, label_values, strict=True)
    )
    true_negative = sum(
        not predicted and label == 0
        for predicted, label in zip(predicted_positive, label_values, strict=True)
    )
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0
    )
    recall = true_positive / positives if positives else 0
    specificity = true_negative / negatives if negatives else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    pr_auc = (
        float(average_precision_score(np.asarray(label_values), np.asarray(probability_values)))
        if positives
        else 0.0
    )
    high_confidence_indices = tuple(
        index
        for index, probability in enumerate(probability_values)
        if probability >= 0.8 or probability <= 0.2
    )
    high_confidence_accuracy = (
        sum(
            (probability_values[index] >= 0.5) == bool(label_values[index])
            for index in high_confidence_indices
        )
        / len(high_confidence_indices)
        if high_confidence_indices
        else 0.0
    )

    slope: Decimal | None = None
    intercept: Decimal | None = None
    if positives and negatives:
        logits = np.asarray(
            [math.log(value / (1.0 - value)) for value in probability_values],
            dtype=np.float64,
        ).reshape(-1, 1)
        calibration_line = LogisticRegression(
            C=1_000_000.0,
            max_iter=10_000,
            random_state=0,
            solver="lbfgs",
        )
        calibration_line.fit(logits, np.asarray(label_values, dtype=np.int64))
        slope = _decimal(float(np.asarray(calibration_line.coef_)[0, 0]))
        intercept = _decimal(float(np.asarray(calibration_line.intercept_)[0]))

    return TruthCalibrationMetrics(
        sample_count=count,
        brier_score=_decimal(brier),
        log_loss=_decimal(log_loss),
        expected_calibration_error=_decimal(weighted_error),
        maximum_calibration_error=_decimal(maximum_error),
        calibration_slope=slope,
        calibration_intercept=intercept,
        precision=_decimal(precision),
        recall=_decimal(recall),
        specificity=_decimal(specificity),
        f1=_decimal(f1),
        pr_auc=_decimal(pr_auc),
        high_confidence_sample_count=len(high_confidence_indices),
        high_confidence_accuracy=_decimal(high_confidence_accuracy),
        reliability_diagram=tuple(reliability),
    )


class TruthModelFamily(StrEnum):
    LOGISTIC_BASELINE = "LOGISTIC_BASELINE"
    GRADIENT_BOOSTING = "GRADIENT_BOOSTING"
    BAYESIAN_HIERARCHICAL = "BAYESIAN_HIERARCHICAL"


class ProbabilityCalibrationMethod(StrEnum):
    PLATT_LOGISTIC = "PLATT_LOGISTIC"
    ISOTONIC = "ISOTONIC"
    TEMPERATURE_SCALING = "TEMPERATURE_SCALING"
    BETA_CALIBRATION = "BETA_CALIBRATION"


_PREDECLARED_CALIBRATION_METHOD: Final = ProbabilityCalibrationMethod.PLATT_LOGISTIC


class TruthCandidateEvaluation(DomainModel):
    model_id: str = Field(min_length=1)
    family: TruthModelFamily
    model_spec_sha256: str
    fit_sample_ids: tuple[str, ...] = Field(min_length=1)
    validation_sample_ids: tuple[str, ...] = Field(min_length=1)
    validation_prediction_sha256: str
    validation_metrics: TruthCalibrationMetrics

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        ensure_sha256(self.model_spec_sha256, field_name="model_spec_sha256")
        ensure_sha256(
            self.validation_prediction_sha256,
            field_name="validation_prediction_sha256",
        )
        if set(self.fit_sample_ids) & set(self.validation_sample_ids):
            raise ValueError("AQ-TRUTH-CANDIDATE-FIT-VALIDATION-OVERLAP")
        if self.validation_metrics.sample_count != len(self.validation_sample_ids):
            raise ValueError("AQ-TRUTH-CANDIDATE-VALIDATION-COUNT-MISMATCH")
        return self


class CalibrationEvaluation(DomainModel):
    method: ProbabilityCalibrationMethod
    artifact_sha256: str
    fit_sample_ids: tuple[str, ...] = Field(min_length=1)
    evaluation_sample_ids: tuple[str, ...] = Field(min_length=1)
    probabilities: tuple[UnitInterval, ...] = Field(min_length=1)
    metrics: TruthCalibrationMetrics

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        ensure_sha256(self.artifact_sha256, field_name="calibration_artifact_sha256")
        if set(self.fit_sample_ids) & set(self.evaluation_sample_ids):
            raise ValueError("AQ-TRUTH-CALIBRATION-EVALUATION-OVERLAP")
        if len(self.probabilities) != len(self.evaluation_sample_ids):
            raise ValueError("AQ-TRUTH-CALIBRATION-PROBABILITY-COUNT-MISMATCH")
        if self.metrics.sample_count != len(self.evaluation_sample_ids):
            raise ValueError("AQ-TRUTH-CALIBRATION-METRIC-COUNT-MISMATCH")
        return self


class TruthCalibrationSlice(DomainModel):
    calibration_key: TruthCalibrationKey
    evaluation_sample_ids: tuple[str, ...] = Field(min_length=1)
    status: Literal["EVALUATED", "INSUFFICIENT_CLASS_VARIATION"]
    metrics: TruthCalibrationMetrics


class TruthCouncilReport(DomainModel):
    report_id: ArtifactId
    dataset_sha256: str
    split_policy: TemporalSplitPolicy
    fold: TemporalFold
    feature_names: tuple[str, ...]
    candidates: tuple[TruthCandidateEvaluation, ...]
    baseline_model_id: str = Field(min_length=1)
    selected_model_id: str = Field(min_length=1)
    rejected_model_ids: tuple[str, ...]
    minimum_incremental_improvement: NonNegativeDecimal
    selection_metric: Literal["VALIDATION_BRIER"] = "VALIDATION_BRIER"
    calibration_comparisons: tuple[CalibrationEvaluation, ...]
    selected_calibration_method: Literal[ProbabilityCalibrationMethod.PLATT_LOGISTIC] = (
        ProbabilityCalibrationMethod.PLATT_LOGISTIC
    )
    calibration_slices: tuple[TruthCalibrationSlice, ...] = Field(min_length=1)
    probability_aggregation: Literal["CALIBRATED_MODEL_NOT_AGENT_VOTE"] = (
        "CALIBRATED_MODEL_NOT_AGENT_VOTE"
    )
    llm_confidence_used_as_model_input: Literal[False] = False
    test_labels_used_for_model_selection: Literal[False] = False
    created_at: UtcDateTime
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        ensure_sha256(self.dataset_sha256, field_name="truth_dataset_sha256")
        if self.feature_names != MODEL_FEATURE_NAMES:
            raise ValueError("AQ-TRUTH-MODEL-FEATURE-SCHEMA-MISMATCH")
        candidate_ids = {item.model_id for item in self.candidates}
        if len(self.candidates) != len(TruthModelFamily) or len(candidate_ids) != len(
            self.candidates
        ):
            raise ValueError("AQ-TRUTH-DUPLICATE-COUNCIL-CANDIDATE")
        if {item.family for item in self.candidates} != set(TruthModelFamily):
            raise ValueError("AQ-TRUTH-COUNCIL-FAMILY-COVERAGE")
        if (
            self.baseline_model_id not in candidate_ids
            or self.selected_model_id not in candidate_ids
        ):
            raise ValueError("AQ-TRUTH-COUNCIL-MODEL-ID-MISMATCH")
        baseline = next(item for item in self.candidates if item.model_id == self.baseline_model_id)
        if baseline.family is not TruthModelFamily.LOGISTIC_BASELINE:
            raise ValueError("AQ-TRUTH-COUNCIL-BASELINE-FAMILY-MISMATCH")
        best = min(
            self.candidates,
            key=lambda item: (item.validation_metrics.brier_score, item.model_id),
        )
        expected_selected = (
            best
            if best.model_id == baseline.model_id
            or baseline.validation_metrics.brier_score - best.validation_metrics.brier_score
            >= self.minimum_incremental_improvement
            else baseline
        )
        if self.selected_model_id != expected_selected.model_id:
            raise ValueError("AQ-TRUTH-COUNCIL-SELECTION-POLICY-MISMATCH")
        if len(self.rejected_model_ids) != len(candidate_ids) - 1 or set(
            self.rejected_model_ids
        ) != candidate_ids - {self.selected_model_id}:
            raise ValueError("AQ-TRUTH-COUNCIL-REJECTED-MODEL-MISMATCH")
        if len(self.calibration_comparisons) != len(ProbabilityCalibrationMethod) or {
            item.method for item in self.calibration_comparisons
        } != set(ProbabilityCalibrationMethod):
            raise ValueError("AQ-TRUTH-CALIBRATION-METHOD-COVERAGE")
        selected = tuple(
            item
            for item in self.calibration_comparisons
            if item.method is self.selected_calibration_method
        )
        if len(selected) != 1:
            raise ValueError("AQ-TRUTH-SELECTED-CALIBRATION-MISSING")
        if any(item.fit_sample_ids != self.fold.train_ids for item in self.candidates):
            raise ValueError("AQ-TRUTH-COUNCIL-TRAIN-SPLIT-MISMATCH")
        if any(item.validation_sample_ids != self.fold.validation_ids for item in self.candidates):
            raise ValueError("AQ-TRUTH-COUNCIL-VALIDATION-SPLIT-MISMATCH")
        if any(
            item.fit_sample_ids != self.fold.calibration_ids
            or item.evaluation_sample_ids != self.fold.test_ids
            for item in self.calibration_comparisons
        ):
            raise ValueError("AQ-TRUTH-COUNCIL-CALIBRATION-SPLIT-MISMATCH")
        slice_ids = tuple(
            sample_id
            for item in self.calibration_slices
            for sample_id in item.evaluation_sample_ids
        )
        if len(slice_ids) != len(set(slice_ids)) or set(slice_ids) != set(self.fold.test_ids):
            raise ValueError("AQ-TRUTH-CALIBRATION-SLICE-COVERAGE-MISMATCH")
        if any(
            item.metrics.sample_count != len(item.evaluation_sample_ids)
            for item in self.calibration_slices
        ):
            raise ValueError("AQ-TRUTH-CALIBRATION-SLICE-COUNT-MISMATCH")
        slice_keys = tuple(
            item.calibration_key.content_sha256() for item in self.calibration_slices
        )
        if len(slice_keys) != len(set(slice_keys)):
            raise ValueError("AQ-TRUTH-CALIBRATION-DUPLICATE-SLICE")
        if self.created_at > self.available_at:
            raise ValueError("AQ-TRUTH-COUNCIL-TIME-ORDER")
        return self

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def build_truth_temporal_folds(
    samples: Iterable[TruthCalibrationSample],
    policy: TemporalSplitPolicy,
) -> tuple[TemporalFold, ...]:
    values = tuple(samples)
    return walk_forward_splits(
        (
            SampleSpan(
                sample_id=item.sample_id,
                group_time=item.decision_time,
                label_start_time=item.resolved_at,
                label_end_time=item.label_available_at,
                regime=item.features.calibration_key.event_type,
            )
            for item in values
        ),
        policy,
    )


@dataclass(frozen=True, slots=True)
class _CandidatePredictions:
    model_id: str
    family: TruthModelFamily
    spec_sha256: str
    validation: tuple[Decimal, ...]
    calibration: tuple[Decimal, ...]
    test: tuple[Decimal, ...]


def _matrix(samples: tuple[TruthCalibrationSample, ...]) -> np.ndarray:
    return np.asarray([item.features.model_values() for item in samples], dtype=np.float64)


def _labels(samples: tuple[TruthCalibrationSample, ...]) -> np.ndarray:
    return np.asarray([item.truth_label for item in samples], dtype=np.int64)


def _probability_decimals(values: np.ndarray) -> tuple[Decimal, ...]:
    flattened = np.asarray(values, dtype=np.float64).reshape(-1)
    return tuple(_decimal(_clamp_probability(float(value))) for value in flattened)


def _fit_candidate(
    *,
    family: TruthModelFamily,
    train: tuple[TruthCalibrationSample, ...],
    validation: tuple[TruthCalibrationSample, ...],
    calibration: tuple[TruthCalibrationSample, ...],
    test: tuple[TruthCalibrationSample, ...],
) -> _CandidatePredictions:
    train_y = _labels(train)
    if len(set(int(item) for item in train_y)) != 2:
        raise ValueError("AQ-TRUTH-COUNCIL-TRAIN-CLASS-COVERAGE")
    destinations = (validation, calibration, test)
    spec: dict[str, object]
    predicted: tuple[np.ndarray, ...]
    if family is TruthModelFamily.LOGISTIC_BASELINE:
        spec = {
            "family": family.value,
            "solver": "lbfgs",
            "max_iter": 10000,
            "seed": 0,
            "standardize": True,
        }
        estimator = Pipeline(
            (
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=10_000,
                        random_state=0,
                        solver="lbfgs",
                    ),
                ),
            )
        )
        estimator.fit(_matrix(train), train_y)
        predicted = tuple(estimator.predict_proba(_matrix(items))[:, 1] for items in destinations)
    elif family is TruthModelFamily.GRADIENT_BOOSTING:
        spec = {
            "family": family.value,
            "n_estimators": 50,
            "learning_rate": 0.05,
            "max_depth": 2,
            "seed": 0,
        }
        estimator = GradientBoostingClassifier(
            learning_rate=0.05,
            max_depth=2,
            n_estimators=50,
            random_state=0,
        )
        estimator.fit(_matrix(train), train_y)
        predicted = tuple(estimator.predict_proba(_matrix(items))[:, 1] for items in destinations)
    else:
        prior_strength = 4.0
        global_rate = (float(np.sum(train_y)) + 1.0) / (len(train_y) + 2.0)
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for sample in train:
            bucket = counts[sample.features.calibration_key.content_sha256()]
            bucket[0] += sample.truth_label
            bucket[1] += 1
        probabilities_by_key = {
            key: (positive + prior_strength * global_rate) / (count + prior_strength)
            for key, (positive, count) in counts.items()
        }
        spec = {
            "family": family.value,
            "global_prior": "beta(1,1)",
            "stratum_prior_strength": prior_strength,
            "stratum_dimensions": [
                "source_class",
                "event_type",
                "language",
                "claim_type",
            ],
        }
        predicted = tuple(
            np.asarray(
                [
                    probabilities_by_key.get(
                        sample.features.calibration_key.content_sha256(), global_rate
                    )
                    for sample in items
                ],
                dtype=np.float64,
            )
            for items in destinations
        )
    model_id = _MODEL_IDS[family.value]
    spec_sha256 = canonical_sha256(
        {
            "model_id": model_id,
            "spec": spec,
            "feature_names": list(MODEL_FEATURE_NAMES),
            "fit_sample_sha256": [item.content_sha256() for item in train],
        }
    )
    return _CandidatePredictions(
        model_id=model_id,
        family=family,
        spec_sha256=spec_sha256,
        validation=_probability_decimals(predicted[0]),
        calibration=_probability_decimals(predicted[1]),
        test=_probability_decimals(predicted[2]),
    )


@dataclass(frozen=True, slots=True)
class _FittedCalibrator:
    method: ProbabilityCalibrationMethod
    parameters: dict[str, object]
    transform: Callable[[np.ndarray], np.ndarray]


def _logits(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values.astype(np.float64), _EPSILON, 1.0 - _EPSILON)
    return np.log(clipped / (1.0 - clipped))


def _fit_calibrator(
    *,
    method: ProbabilityCalibrationMethod,
    raw_probabilities: tuple[Decimal, ...],
    labels: tuple[int, ...],
) -> _FittedCalibrator:
    raw = np.asarray([float(item) for item in raw_probabilities], dtype=np.float64)
    target = np.asarray(labels, dtype=np.int64)
    if len(raw) != len(target) or not len(raw) or len(set(int(item) for item in target)) != 2:
        raise ValueError("AQ-TRUTH-CALIBRATOR-FIT-DATA")
    if method is ProbabilityCalibrationMethod.PLATT_LOGISTIC:
        estimator = LogisticRegression(max_iter=10_000, random_state=0, solver="lbfgs")
        estimator.fit(_logits(raw).reshape(-1, 1), target)
        parameters: dict[str, object] = {
            "coefficient": float(np.asarray(estimator.coef_)[0, 0]),
            "intercept": float(np.asarray(estimator.intercept_)[0]),
        }

        def transform(values: np.ndarray) -> np.ndarray:
            return estimator.predict_proba(_logits(values).reshape(-1, 1))[:, 1]

    elif method is ProbabilityCalibrationMethod.ISOTONIC:
        estimator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        estimator.fit(raw, target)
        parameters = {
            "x_thresholds": [float(item) for item in estimator.X_thresholds_],
            "y_thresholds": [float(item) for item in estimator.y_thresholds_],
        }

        def transform(values: np.ndarray) -> np.ndarray:
            return np.asarray(estimator.predict(values), dtype=np.float64)

    elif method is ProbabilityCalibrationMethod.TEMPERATURE_SCALING:
        raw_logits = _logits(raw)
        candidates = np.linspace(0.25, 4.0, 151, dtype=np.float64)

        def loss(temperature: float) -> float:
            probabilities = 1.0 / (1.0 + np.exp(-raw_logits / temperature))
            probabilities = np.clip(probabilities, _EPSILON, 1.0 - _EPSILON)
            return float(
                -np.mean(
                    target * np.log(probabilities) + (1 - target) * np.log(1.0 - probabilities)
                )
            )

        temperature = min((float(item) for item in candidates), key=lambda item: (loss(item), item))
        parameters = {"temperature": temperature, "grid_points": len(candidates)}

        def transform(values: np.ndarray) -> np.ndarray:
            return 1.0 / (1.0 + np.exp(-_logits(values) / temperature))

    else:
        estimator = LogisticRegression(max_iter=10_000, random_state=0, solver="lbfgs")
        clipped = np.clip(raw, _EPSILON, 1.0 - _EPSILON)
        beta_features = np.column_stack((np.log(clipped), -np.log(1.0 - clipped)))
        estimator.fit(beta_features, target)
        parameters = {
            "coefficients": [float(item) for item in np.asarray(estimator.coef_)[0]],
            "intercept": float(np.asarray(estimator.intercept_)[0]),
        }

        def transform(values: np.ndarray) -> np.ndarray:
            clipped_values = np.clip(values, _EPSILON, 1.0 - _EPSILON)
            features = np.column_stack((np.log(clipped_values), -np.log(1.0 - clipped_values)))
            return estimator.predict_proba(features)[:, 1]

    return _FittedCalibrator(method=method, parameters=parameters, transform=transform)


def _calibration_evaluation(
    *,
    method: ProbabilityCalibrationMethod,
    raw_fit: tuple[Decimal, ...],
    fit_samples: tuple[TruthCalibrationSample, ...],
    raw_evaluation: tuple[Decimal, ...],
    evaluation_samples: tuple[TruthCalibrationSample, ...],
) -> CalibrationEvaluation:
    labels = tuple(item.truth_label for item in fit_samples)
    fitted = _fit_calibrator(method=method, raw_probabilities=raw_fit, labels=labels)
    transformed = fitted.transform(
        np.asarray([float(item) for item in raw_evaluation], dtype=np.float64)
    )
    probabilities = _probability_decimals(transformed)
    artifact_sha256 = canonical_sha256(
        {
            "method": method.value,
            "parameters": fitted.parameters,
            "fit_sample_ids": [item.sample_id for item in fit_samples],
            "fit_raw_probabilities": [str(item) for item in raw_fit],
            "fit_labels": list(labels),
        }
    )
    return CalibrationEvaluation(
        method=method,
        artifact_sha256=artifact_sha256,
        fit_sample_ids=tuple(item.sample_id for item in fit_samples),
        evaluation_sample_ids=tuple(item.sample_id for item in evaluation_samples),
        probabilities=probabilities,
        metrics=evaluate_truth_probabilities(
            probabilities=probabilities,
            labels=tuple(item.truth_label for item in evaluation_samples),
        ),
    )


def _select_samples(
    by_id: dict[str, TruthCalibrationSample], sample_ids: tuple[str, ...]
) -> tuple[TruthCalibrationSample, ...]:
    unknown = set(sample_ids) - by_id.keys()
    if unknown:
        raise ValueError("AQ-TRUTH-COUNCIL-SPLIT-REFERENCES-UNKNOWN-SAMPLE")
    return tuple(by_id[sample_id] for sample_id in sample_ids)


def _validate_temporal_partitions(
    *,
    fold: TemporalFold,
    train: tuple[TruthCalibrationSample, ...],
    validation: tuple[TruthCalibrationSample, ...],
    calibration: tuple[TruthCalibrationSample, ...],
    test: tuple[TruthCalibrationSample, ...],
) -> None:
    validation_start = min(item.decision_time for item in validation)
    calibration_start = min(item.decision_time for item in calibration)
    test_start = min(item.decision_time for item in test)
    if fold.validation_starts_at != validation_start or fold.test_ends_at != max(
        item.decision_time for item in test
    ):
        raise ValueError("AQ-TRUTH-COUNCIL-FOLD-BOUNDARY-MISMATCH")
    if not (
        max(item.decision_time for item in train)
        < validation_start
        <= max(item.decision_time for item in validation)
        < calibration_start
        <= max(item.decision_time for item in calibration)
        < test_start
    ):
        raise ValueError("AQ-TRUTH-COUNCIL-PARTITION-TIME-ORDER")
    if (
        max(item.label_available_at for item in train) >= validation_start
        or max(item.label_available_at for item in validation) >= calibration_start
        or max(item.label_available_at for item in calibration) >= test_start
    ):
        raise ValueError("AQ-TRUTH-COUNCIL-PARTITION-LABEL-LOOKAHEAD")


def run_truth_council(
    *,
    samples: tuple[TruthCalibrationSample, ...],
    split_policy: TemporalSplitPolicy,
    fold: TemporalFold,
    as_of_time: datetime,
    minimum_incremental_improvement: Decimal = Decimal("0.005"),
) -> TruthCouncilReport:
    """Fit candidates on train, select on validation, calibrate separately, evaluate on test."""

    as_of = ensure_utc(as_of_time)
    if minimum_incremental_improvement < 0:
        raise ValueError("AQ-TRUTH-NEGATIVE-MINIMUM-IMPROVEMENT")
    by_id = {item.sample_id: item for item in samples}
    if len(by_id) != len(samples):
        raise ValueError("AQ-TRUTH-DUPLICATE-CALIBRATION-SAMPLE-ID")
    if len({str(item.claim_id) for item in samples}) != len(samples):
        raise ValueError("AQ-TRUTH-DUPLICATE-CALIBRATION-CLAIM-ID")
    if fold not in build_truth_temporal_folds(samples, split_policy):
        raise ValueError("AQ-TRUTH-COUNCIL-FOLD-POLICY-MISMATCH")
    used_ids = {
        *fold.train_ids,
        *fold.validation_ids,
        *fold.calibration_ids,
        *fold.test_ids,
        *fold.purged_ids,
    }
    if used_ids - by_id.keys():
        raise ValueError("AQ-TRUTH-COUNCIL-FOLD-REFERENCES-UNKNOWN-SAMPLE")
    evaluated_ids = {*fold.train_ids, *fold.validation_ids, *fold.calibration_ids, *fold.test_ids}
    if any(by_id[sample_id].label_available_at > as_of for sample_id in evaluated_ids):
        raise ValueError("AQ-TRUTH-COUNCIL-FUTURE-LABEL")

    train = _select_samples(by_id, fold.train_ids)
    validation = _select_samples(by_id, fold.validation_ids)
    calibration = _select_samples(by_id, fold.calibration_ids)
    test = _select_samples(by_id, fold.test_ids)
    _validate_temporal_partitions(
        fold=fold,
        train=train,
        validation=validation,
        calibration=calibration,
        test=test,
    )
    candidate_predictions = tuple(
        _fit_candidate(
            family=family,
            train=train,
            validation=validation,
            calibration=calibration,
            test=test,
        )
        for family in TruthModelFamily
    )
    validation_labels = tuple(item.truth_label for item in validation)
    candidates = tuple(
        TruthCandidateEvaluation(
            model_id=item.model_id,
            family=item.family,
            model_spec_sha256=item.spec_sha256,
            fit_sample_ids=fold.train_ids,
            validation_sample_ids=fold.validation_ids,
            validation_prediction_sha256=canonical_sha256(
                {
                    "sample_ids": list(fold.validation_ids),
                    "probabilities": [str(value) for value in item.validation],
                }
            ),
            validation_metrics=evaluate_truth_probabilities(
                probabilities=item.validation,
                labels=validation_labels,
            ),
        )
        for item in candidate_predictions
    )
    baseline = next(
        item for item in candidates if item.family is TruthModelFamily.LOGISTIC_BASELINE
    )
    best = min(
        candidates,
        key=lambda item: (item.validation_metrics.brier_score, item.model_id),
    )
    selected = (
        best
        if best.model_id == baseline.model_id
        or baseline.validation_metrics.brier_score - best.validation_metrics.brier_score
        >= minimum_incremental_improvement
        else baseline
    )
    selected_predictions = next(
        item for item in candidate_predictions if item.model_id == selected.model_id
    )
    comparisons = tuple(
        _calibration_evaluation(
            method=method,
            raw_fit=selected_predictions.calibration,
            fit_samples=calibration,
            raw_evaluation=selected_predictions.test,
            evaluation_samples=test,
        )
        for method in ProbabilityCalibrationMethod
    )
    selected_evaluation = next(
        item for item in comparisons if item.method is _PREDECLARED_CALIBRATION_METHOD
    )
    probability_by_id = dict(zip(fold.test_ids, selected_evaluation.probabilities, strict=True))
    samples_by_key: dict[str, list[TruthCalibrationSample]] = defaultdict(list)
    for sample in test:
        samples_by_key[sample.features.calibration_key.content_sha256()].append(sample)
    slices: list[TruthCalibrationSlice] = []
    for key_hash in sorted(samples_by_key):
        members = tuple(samples_by_key[key_hash])
        member_probabilities = tuple(probability_by_id[item.sample_id] for item in members)
        member_labels = tuple(item.truth_label for item in members)
        slices.append(
            TruthCalibrationSlice(
                calibration_key=members[0].features.calibration_key,
                evaluation_sample_ids=tuple(item.sample_id for item in members),
                status=(
                    "EVALUATED" if len(set(member_labels)) == 2 else "INSUFFICIENT_CLASS_VARIATION"
                ),
                metrics=evaluate_truth_probabilities(
                    probabilities=member_probabilities,
                    labels=member_labels,
                ),
            )
        )

    dataset_sha256 = canonical_sha256(
        [item.content_sha256() for item in sorted(samples, key=lambda item: item.sample_id)]
    )
    return TruthCouncilReport(
        report_id=ArtifactId(f"truth-council:{fold.fold_id}"),
        dataset_sha256=dataset_sha256,
        split_policy=split_policy,
        fold=fold,
        feature_names=MODEL_FEATURE_NAMES,
        candidates=candidates,
        baseline_model_id=baseline.model_id,
        selected_model_id=selected.model_id,
        rejected_model_ids=tuple(
            item.model_id for item in candidates if item.model_id != selected.model_id
        ),
        minimum_incremental_improvement=minimum_incremental_improvement,
        calibration_comparisons=comparisons,
        selected_calibration_method=_PREDECLARED_CALIBRATION_METHOD,
        calibration_slices=tuple(slices),
        created_at=as_of,
        available_at=as_of,
    )
