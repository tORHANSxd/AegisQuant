# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Deterministic simplex-constrained synthetic control without a new dependency."""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np

from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.research.causal.contracts import (
    CausalEstimand,
    CausalMethod,
    CausalPointEstimate,
    HistoricalState,
    StateWeight,
    SyntheticControlResult,
    SyntheticControlSpec,
)
from aegisquant.research.causal.diagnostics import (
    DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
    pre_treatment_fit_report,
)


def _decimal(value: float) -> Decimal:
    if not math.isfinite(value):
        raise ValueError("synthetic control produced a non-finite value")
    return Decimal(format(value, ".15g"))


def _project_simplex(vector: np.ndarray) -> np.ndarray:
    """Project a vector onto non-negative weights summing to one."""

    ordered = np.sort(vector)[::-1]
    cumulative = np.cumsum(ordered) - 1.0
    candidates = ordered - cumulative / np.arange(1, len(vector) + 1) > 0
    if not np.any(candidates):
        raise ValueError("simplex projection found no feasible weight")
    rho = int(np.nonzero(candidates)[0][-1])
    threshold = cumulative[rho] / float(rho + 1)
    projected = np.maximum(vector - threshold, 0.0)
    return projected / float(np.sum(projected))


def _decimal_weights(values: np.ndarray) -> tuple[Decimal, ...]:
    weights = [_decimal(float(value)) for value in values]
    total = sum(weights, Decimal("0"))
    if total <= 0:
        raise ValueError("synthetic control weights collapsed to zero")
    normalized = [value / total for value in weights]
    normalized[-1] = Decimal("1") - sum(normalized[:-1], Decimal("0"))
    if normalized[-1] < 0:
        raise ValueError("synthetic control decimal normalization became negative")
    return tuple(normalized)


def fit_synthetic_control(
    *,
    treated: HistoricalState,
    donors: tuple[HistoricalState, ...],
    spec: SyntheticControlSpec,
    as_of_time: UtcDateTime,
) -> SyntheticControlResult:
    treated = HistoricalState.model_validate_json(treated.model_dump_json())
    donors = tuple(HistoricalState.model_validate_json(donor.model_dump_json()) for donor in donors)
    spec = SyntheticControlSpec.model_validate_json(spec.model_dump_json())
    if len(donors) < 2:
        raise ValueError("synthetic control requires at least two donors")
    if len({item.state_id for item in donors}) != len(donors):
        raise ValueError("synthetic control donor ids must be unique")
    ordered = tuple(sorted(donors, key=lambda item: item.state_id))
    if treated.outcome_available_at > as_of_time:
        raise ValueError("AQ-CAUSAL-SYNTHETIC-TREATED-OUTCOME-LOOKAHEAD")
    if any(
        donor.decision_time >= treated.decision_time
        or donor.outcome_available_at > treated.decision_time
        for donor in ordered
    ):
        raise ValueError("AQ-CAUSAL-SYNTHETIC-DONOR-LOOKAHEAD")
    width = len(treated.pre_treatment_outcomes)
    if any(
        item.covariate_names != treated.covariate_names or len(item.pre_treatment_outcomes) != width
        for item in ordered
    ):
        raise ValueError("synthetic control donor schemas differ")
    matrix = np.asarray(
        [[float(value) for value in item.pre_treatment_outcomes] for item in ordered],
        dtype=np.float64,
    ).T
    target = np.asarray(
        [float(value) for value in treated.pre_treatment_outcomes], dtype=np.float64
    )
    weights = np.full(len(ordered), 1.0 / len(ordered), dtype=np.float64)
    spectral = float(np.linalg.norm(matrix, ord=2))
    lipschitz = 2.0 * (spectral**2 + float(spec.ridge_penalty))
    if not math.isfinite(lipschitz) or lipschitz <= 0:
        raise ValueError("synthetic control design has no usable scale")
    step = 1.0 / lipschitz
    converged = False
    iterations = 0
    for iteration in range(1, spec.maximum_iterations + 1):
        iterations = iteration
        residual = matrix @ weights - target
        gradient = 2.0 * (matrix.T @ residual + float(spec.ridge_penalty) * weights)
        updated = _project_simplex(weights - step * gradient)
        if float(np.max(np.abs(updated - weights))) <= float(spec.convergence_tolerance):
            weights = updated
            converged = True
            break
        weights = updated
    if not converged:
        raise ValueError("AQ-CAUSAL-SYNTHETIC-CONTROL-NOT-CONVERGED")

    decimal_weights = _decimal_weights(weights)
    counterfactual_pre = tuple(
        canonical_result(
            sum(
                (
                    donor.pre_treatment_outcomes[index] * weight
                    for donor, weight in zip(ordered, decimal_weights, strict=True)
                ),
                Decimal("0"),
            )
        )
        for index in range(width)
    )
    counterfactual_outcome = canonical_result(
        sum(
            (
                donor.outcome * weight
                for donor, weight in zip(ordered, decimal_weights, strict=True)
            ),
            Decimal("0"),
        )
    )
    effect = canonical_result(treated.outcome - counterfactual_outcome)
    fit = pre_treatment_fit_report(
        treated_path=treated.pre_treatment_outcomes,
        counterfactual_path=counterfactual_pre,
        policy=DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
    )
    donor_weights = tuple(
        StateWeight(state_id=donor.state_id, state_sha256=donor.state_sha256, weight=weight)
        for donor, weight in zip(ordered, decimal_weights, strict=True)
    )
    point = CausalPointEstimate(
        method=CausalMethod.SYNTHETIC_CONTROL,
        estimand=CausalEstimand.ATT,
        effect=effect,
        standard_error=None,
        confidence_lower=None,
        confidence_upper=None,
        treated_count=1,
        control_count=len(ordered),
        estimator_spec_sha256=spec.spec_sha256,
    )
    return SyntheticControlResult(
        point_estimate=point,
        donor_weights=donor_weights,
        counterfactual_outcome=counterfactual_outcome,
        pre_treatment_fit=fit,
        converged=True,
        iterations=iterations,
    )
