"""Deterministic timestamp, asset, and treatment-permutation placebo tests."""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from aegisquant.research.causal.contracts import (
    CausalDiagnosticPolicy,
    PlaceboKind,
    PlaceboTestResult,
)
from aegisquant.research.causal.diagnostics import DEFAULT_CAUSAL_DIAGNOSTIC_POLICY


def evaluate_placebo_distribution(
    *,
    kind: PlaceboKind,
    observed_effect: Decimal,
    placebo_effects: tuple[Decimal, ...],
    policy: CausalDiagnosticPolicy = DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
) -> PlaceboTestResult:
    if kind not in policy.required_placebo_kinds:
        raise ValueError("placebo kind is not required by the diagnostic policy")
    if not placebo_effects:
        raise ValueError("placebo distribution cannot be empty")
    extreme = sum(abs(value) >= abs(observed_effect) for value in placebo_effects)
    p_value = Decimal(extreme + 1) / Decimal(len(placebo_effects) + 1)
    passed = (
        len(placebo_effects) >= policy.minimum_placebo_draws
        and p_value <= policy.maximum_placebo_p_value
    )
    return PlaceboTestResult(
        kind=kind,
        observed_effect=observed_effect,
        placebo_effects=placebo_effects,
        empirical_p_value=p_value,
        maximum_p_value=policy.maximum_placebo_p_value,
        minimum_draws=policy.minimum_placebo_draws,
        passed=passed,
    )


def treatment_permutation_placebo(
    *,
    outcomes: tuple[Decimal, ...],
    treatments: tuple[bool, ...],
    draws: int,
    seed: int,
    policy: CausalDiagnosticPolicy = DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
) -> PlaceboTestResult:
    if len(outcomes) < 4 or len(outcomes) != len(treatments):
        raise ValueError("treatment permutation requires aligned outcomes and assignments")
    treated_count = sum(treatments)
    if treated_count == 0 or treated_count == len(treatments):
        raise ValueError("treatment permutation requires both groups")
    if draws < policy.minimum_placebo_draws:
        raise ValueError("treatment permutation draw count is below policy")
    values = np.asarray([float(value) for value in outcomes], dtype=np.float64)
    assignment = np.asarray(treatments, dtype=np.bool_)

    def difference(mask: np.ndarray) -> Decimal:
        return Decimal(format(float(np.mean(values[mask]) - np.mean(values[~mask])), ".15g"))

    observed = difference(assignment)
    rng = np.random.default_rng(seed)
    placebo_effects = tuple(difference(rng.permutation(assignment)) for _ in range(draws))
    return evaluate_placebo_distribution(
        kind=PlaceboKind.TREATMENT_PERMUTATION,
        observed_effect=observed,
        placebo_effects=placebo_effects,
        policy=policy,
    )
