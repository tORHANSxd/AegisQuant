"""Split-conformal calibration and deterministic abstention policy."""

from __future__ import annotations

import math
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval


class ConformalCalibration(DomainModel):
    alpha: UnitInterval
    residual_quantile: NonNegativeDecimal
    sample_count: int = Field(gt=0)


def fit_split_conformal(
    *, predictions: tuple[Decimal, ...], realized: tuple[Decimal, ...], alpha: Decimal
) -> ConformalCalibration:
    if len(predictions) != len(realized) or not predictions:
        raise ValueError("conformal calibration dimensions differ")
    if not Decimal("0") < alpha < Decimal("1"):
        raise ValueError("conformal alpha must be between zero and one")
    residuals = sorted(abs(left - right) for left, right in zip(predictions, realized, strict=True))
    rank = min(len(residuals), math.ceil((len(residuals) + 1) * float(1 - alpha)))
    return ConformalCalibration(
        alpha=alpha,
        residual_quantile=residuals[rank - 1],
        sample_count=len(residuals),
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
