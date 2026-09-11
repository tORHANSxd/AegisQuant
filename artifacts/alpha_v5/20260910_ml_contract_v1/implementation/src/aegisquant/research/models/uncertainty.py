"""Split-conformal calibration and deterministic abstention policy."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval
from aegisquant.research.validation.ml_contract import (
    FoldRegistration,
    OOFPrediction,
    validate_oof_alignment,
)


class ConformalCalibration(DomainModel):
    alpha: UnitInterval
    residual_quantile: NonNegativeDecimal
    sample_count: int = Field(gt=0)
    oof_provenance_sha256: str | None = Field(default=None, exclude_if=lambda v: v is None)
    coverage_contract: str | None = Field(default=None, exclude_if=lambda v: v is None)


def fit_split_conformal(
    *,
    predictions: tuple[Decimal, ...],
    realized: tuple[Decimal, ...],
    alpha: Decimal,
    oof_predictions: tuple[OOFPrediction, ...] | None = None,
    applied_at: datetime | None = None,
    registrations: tuple[FoldRegistration, ...] | None = None,
) -> ConformalCalibration:
    if len(predictions) != len(realized) or not predictions:
        raise ValueError("conformal calibration dimensions differ")
    if not Decimal("0") < alpha < Decimal("1"):
        raise ValueError("conformal alpha must be between zero and one")
    if any(not value.is_finite() for value in predictions + realized):
        raise ValueError("conformal observations must be finite")
    provenance_hash = None
    if oof_predictions is not None:
        if (
            applied_at is None
            or registrations is None
            or predictions != tuple(item.prediction for item in oof_predictions)
        ):
            raise ValueError("conformal OOF prediction values/time must align")
        provenance_hash = validate_oof_alignment(
            oof_predictions,
            sample_ids=tuple(item.sample.sample_id for item in oof_predictions),
            timestamps=tuple(item.sample.group_time for item in oof_predictions),
            label_end_times=tuple(item.sample.label_end_time for item in oof_predictions),
            consumed_at=applied_at,
            registrations=registrations,
        )
    elif applied_at is not None or registrations is not None:
        raise ValueError("conformal application time requires OOF provenance")
    residuals = sorted(abs(left - right) for left, right in zip(predictions, realized, strict=True))
    rank = min(len(residuals), math.ceil((len(residuals) + 1) * float(1 - alpha)))
    return ConformalCalibration(
        alpha=alpha,
        residual_quantile=residuals[rank - 1],
        sample_count=len(residuals),
        oof_provenance_sha256=provenance_hash,
        coverage_contract="OOF_RESIDUAL_PREDICTIVE_INTERVAL_NOT_MEAN_CI;TEMPORAL_BLOCK_COVERAGE_NOT_VERIFIED;NO_EXACT_NONSTATIONARY_GUARANTEE"
        if provenance_hash
        else None,
    )


class CalibratedInterval(DomainModel):
    lower: FiniteDecimal
    median: FiniteDecimal
    upper: FiniteDecimal

    @model_validator(mode="after")
    def validate_order(self) -> CalibratedInterval:
        if not self.lower <= self.median <= self.upper:
            raise ValueError("calibrated interval must be ordered")
        return self


def conformal_interval(
    prediction: Decimal, calibration: ConformalCalibration
) -> CalibratedInterval:
    return CalibratedInterval(
        lower=prediction - calibration.residual_quantile,
        median=prediction,
        upper=prediction + calibration.residual_quantile,
    )


class AbstainReason(StrEnum):
    LOW_EDGE = "LOW_EDGE"
    HIGH_UNCERTAINTY = "HIGH_UNCERTAINTY"
    HIGH_DISAGREEMENT = "HIGH_DISAGREEMENT"
    STALE_DATA = "STALE_DATA"
    COST_TOO_HIGH = "COST_TOO_HIGH"
    OUT_OF_DISTRIBUTION = "OUT_OF_DISTRIBUTION"
    RISK_LIMIT = "RISK_LIMIT"


class AbstainPolicy(DomainModel):
    minimum_absolute_edge: NonNegativeDecimal
    maximum_uncertainty: NonNegativeDecimal
    maximum_disagreement: NonNegativeDecimal
    maximum_staleness_seconds: NonNegativeDecimal
    maximum_cost: NonNegativeDecimal
    maximum_ood_score: NonNegativeDecimal


class AbstainInputs(DomainModel):
    expected_edge: FiniteDecimal
    uncertainty: NonNegativeDecimal
    disagreement: NonNegativeDecimal
    staleness_seconds: NonNegativeDecimal
    expected_cost: NonNegativeDecimal
    ood_score: NonNegativeDecimal
    risk_blocked: bool


class AbstainDecision(DomainModel):
    should_abstain: bool
    reasons: tuple[AbstainReason, ...]

    @model_validator(mode="after")
    def validate_consistency(self) -> AbstainDecision:
        if self.should_abstain != bool(self.reasons):
            raise ValueError("abstain flag and reasons must agree")
        return self


def decide_abstention(*, policy: AbstainPolicy, inputs: AbstainInputs) -> AbstainDecision:
    checks = (
        (abs(inputs.expected_edge) < policy.minimum_absolute_edge, AbstainReason.LOW_EDGE),
        (inputs.uncertainty > policy.maximum_uncertainty, AbstainReason.HIGH_UNCERTAINTY),
        (inputs.disagreement > policy.maximum_disagreement, AbstainReason.HIGH_DISAGREEMENT),
        (
            inputs.staleness_seconds > policy.maximum_staleness_seconds,
            AbstainReason.STALE_DATA,
        ),
        (inputs.expected_cost > policy.maximum_cost, AbstainReason.COST_TOO_HIGH),
        (inputs.ood_score > policy.maximum_ood_score, AbstainReason.OUT_OF_DISTRIBUTION),
        (inputs.risk_blocked, AbstainReason.RISK_LIMIT),
    )
    reasons = tuple(reason for failed, reason in checks if failed)
    return AbstainDecision(should_abstain=bool(reasons), reasons=reasons)
