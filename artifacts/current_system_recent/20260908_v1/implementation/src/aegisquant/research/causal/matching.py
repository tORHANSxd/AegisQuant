"""Deterministic nearest-state matching for historical event controls."""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np

from aegisquant.domain.time import UtcDateTime
from aegisquant.research.causal.contracts import (
    HistoricalState,
    MatchedControl,
    MatchedStateSet,
    MatchingSpec,
)


def _decimal(value: float) -> Decimal:
    if not math.isfinite(value):
        raise ValueError("causal matching produced a non-finite distance")
    return Decimal(format(value, ".15g"))


def _uniform_weights(count: int) -> tuple[Decimal, ...]:
    base = Decimal("1") / Decimal(count)
    values = [base] * count
    values[-1] = Decimal("1") - sum(values[:-1], Decimal("0"))
    return tuple(values)


def match_historical_states(
    *,
    treated: HistoricalState,
    candidates: tuple[HistoricalState, ...],
    spec: MatchingSpec,
    as_of_time: UtcDateTime,
) -> MatchedStateSet:
    """Match only controls that were fully known before the treated decision."""

    treated = HistoricalState.model_validate_json(treated.model_dump_json())
    candidates = tuple(
        HistoricalState.model_validate_json(candidate.model_dump_json()) for candidate in candidates
    )
    spec = MatchingSpec.model_validate_json(spec.model_dump_json())
    if treated.outcome_available_at > as_of_time:
        raise ValueError("AQ-CAUSAL-TREATED-OUTCOME-LOOKAHEAD")
    eligible: list[HistoricalState] = []
    for candidate in candidates:
        if candidate.state_id == treated.state_id or (
            treated.event_id is not None and candidate.event_id == treated.event_id
        ):
            continue
        if candidate.covariate_names != treated.covariate_names:
            raise ValueError("matching covariate schemas differ")
        if candidate.decision_time >= treated.decision_time:
            continue
        if candidate.outcome_available_at > as_of_time:
            continue
        if (
            spec.historical_outcomes_known_at_treatment
            and candidate.outcome_available_at > treated.decision_time
        ):
            continue
        if spec.require_same_asset and candidate.asset != treated.asset:
            continue
        if spec.require_same_regime and candidate.regime != treated.regime:
            continue
        eligible.append(candidate)
    eligible.sort(key=lambda item: (item.decision_time, item.state_id))
    if len(eligible) < spec.matched_count:
        raise ValueError("AQ-CAUSAL-MATCH-INSUFFICIENT-CONTROLS")

    control_matrix = np.asarray(
        [[float(value) for value in item.covariates] for item in eligible], dtype=np.float64
    )
    treated_vector = np.asarray([float(value) for value in treated.covariates], dtype=np.float64)
    scales = np.std(control_matrix, axis=0)
    scales = np.where(scales <= np.finfo(np.float64).eps, 1.0, scales)
    distances = np.sqrt(np.mean(((control_matrix - treated_vector) / scales) ** 2, axis=1))
    ranked = sorted(
        zip(eligible, distances, strict=True),
        key=lambda item: (float(item[1]), item[0].state_id),
    )
    selected = tuple(item for item in ranked if float(item[1]) <= float(spec.caliper))[
        : spec.matched_count
    ]
    if len(selected) < spec.matched_count:
        raise ValueError("AQ-CAUSAL-MATCH-CALIPER-REJECTED")
    weights = _uniform_weights(len(selected))
    controls = tuple(
        MatchedControl(
            state_id=state.state_id,
            state_sha256=state.state_sha256,
            distance=_decimal(float(distance)),
            weight=weight,
        )
        for (state, distance), weight in zip(selected, weights, strict=True)
    )
    return MatchedStateSet(
        treated_state_sha256=treated.state_sha256,
        matching_spec_sha256=spec.spec_sha256,
        candidate_count=len(eligible),
        matched_controls=controls,
        as_of_time=as_of_time,
    )
