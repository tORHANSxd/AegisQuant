"""Doubly robust AIPW estimation from point-in-time nuisance predictions."""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np

from aegisquant.research.causal.contracts import (
    CausalEstimand,
    CausalMethod,
    CausalPointEstimate,
    DoublyRobustObservation,
    DoublyRobustSpec,
)


def _decimal(value: float) -> Decimal:
    if not math.isfinite(value):
        raise ValueError("doubly robust estimator produced a non-finite value")
    return Decimal(format(value, ".15g"))


def estimate_aipw(
    *,
    observations: tuple[DoublyRobustObservation, ...],
    spec: DoublyRobustSpec,
) -> CausalPointEstimate:
    """Estimate ATE using pre-computed out-of-sample nuisance predictions."""

    observations = tuple(
        DoublyRobustObservation.model_validate_json(item.model_dump_json()) for item in observations
    )
    spec = DoublyRobustSpec.model_validate_json(spec.model_dump_json())
    if len(observations) < 4 or len({item.sample_id for item in observations}) != len(observations):
        raise ValueError("AIPW requires at least four unique observations")
    ordered = tuple(sorted(observations, key=lambda item: (item.decision_time, item.sample_id)))
    treated_count = sum(item.treated for item in ordered)
    control_count = len(ordered) - treated_count
    if treated_count < 2 or control_count < 2:
        raise ValueError("AIPW requires at least two treated and two control observations")
    if any(
        not spec.propensity_lower_bound <= item.propensity_score <= spec.propensity_upper_bound
        for item in ordered
    ):
        raise ValueError("AQ-CAUSAL-AIPW-POSITIVITY-FAILED")
    influence: list[float] = []
    for item in ordered:
        treatment = 1.0 if item.treated else 0.0
        outcome = float(item.outcome)
        propensity = float(item.propensity_score)
        control_prediction = float(item.predicted_outcome_if_control)
        treated_prediction = float(item.predicted_outcome_if_treated)
        influence.append(
            treated_prediction
            - control_prediction
            + treatment * (outcome - treated_prediction) / propensity
            - (1.0 - treatment) * (outcome - control_prediction) / (1.0 - propensity)
        )
    values = np.asarray(influence, dtype=np.float64)
    effect = _decimal(float(np.mean(values)))
    standard_error = _decimal(float(np.std(values, ddof=1) / math.sqrt(len(values))))
    half_width = spec.confidence_z * standard_error
    return CausalPointEstimate(
        method=CausalMethod.DOUBLY_ROBUST_AIPW,
        estimand=CausalEstimand.ATE,
        effect=effect,
        standard_error=standard_error,
        confidence_lower=effect - half_width,
        confidence_upper=effect + half_width,
        treated_count=treated_count,
        control_count=control_count,
        estimator_spec_sha256=spec.spec_sha256,
    )
