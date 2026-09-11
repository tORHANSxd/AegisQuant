"""Matched difference-in-differences event-study point estimator."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.domain.values import canonical_result
from aegisquant.research.causal.contracts import (
    CausalEstimand,
    CausalMethod,
    CausalPointEstimate,
    EventStudySpec,
    HistoricalState,
    MatchedStateSet,
    MatchingSpec,
)
from aegisquant.research.causal.matching import match_historical_states


def estimate_matched_event_study(
    *,
    treated: HistoricalState,
    controls: tuple[HistoricalState, ...],
    matched: MatchedStateSet,
    matching_spec: MatchingSpec,
    spec: EventStudySpec,
) -> CausalPointEstimate:
    """Estimate ATT from post-minus-last-pre changes in one matched state set."""

    treated = HistoricalState.model_validate_json(treated.model_dump_json())
    controls = tuple(
        HistoricalState.model_validate_json(control.model_dump_json()) for control in controls
    )
    matched = MatchedStateSet.model_validate_json(matched.model_dump_json())
    matching_spec = MatchingSpec.model_validate_json(matching_spec.model_dump_json())
    spec = EventStudySpec.model_validate_json(spec.model_dump_json())
    expected_match = match_historical_states(
        treated=treated,
        candidates=controls,
        spec=matching_spec,
        as_of_time=matched.as_of_time,
    )
    if matched != expected_match:
        raise ValueError("AQ-CAUSAL-EVENT-STUDY-MATCH-BINDING-MISMATCH")
    by_id = {item.state_id: item for item in controls}
    if len(by_id) != len(controls):
        raise ValueError("event-study control ids must be unique")
    try:
        selected = tuple(by_id[item.state_id] for item in matched.matched_controls)
    except KeyError as error:
        raise ValueError("matched control is absent from event-study inputs") from error
    if any(item.covariate_names != treated.covariate_names for item in selected):
        raise ValueError("event-study covariate schemas differ")
    if any(
        len(item.pre_treatment_outcomes) != len(treated.pre_treatment_outcomes) for item in selected
    ):
        raise ValueError("event-study pre-treatment windows differ")
    treated_change = treated.outcome - treated.pre_treatment_outcomes[-1]
    control_changes = tuple(state.outcome - state.pre_treatment_outcomes[-1] for state in selected)
    weighted_control_change = sum(
        (
            control_change * match.weight
            for control_change, match in zip(control_changes, matched.matched_controls, strict=True)
        ),
        Decimal("0"),
    )
    effect = canonical_result(treated_change - weighted_control_change)
    return CausalPointEstimate(
        method=CausalMethod.MATCHED_EVENT_STUDY,
        estimand=CausalEstimand.ATT,
        effect=effect,
        standard_error=None,
        confidence_lower=None,
        confidence_upper=None,
        treated_count=1,
        control_count=len(selected),
        estimator_spec_sha256=spec.spec_sha256,
    )
