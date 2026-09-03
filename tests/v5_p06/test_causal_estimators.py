from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.research.causal import (
    DoublyRobustObservation,
    DoublyRobustSpec,
    EventStudySpec,
    MatchingSpec,
    SyntheticControlSpec,
    estimate_aipw,
    estimate_matched_event_study,
    fit_synthetic_control,
    match_historical_states,
)
from tests.v5_p06.helpers import BASE, digest, historical_state


def matching_fixture():
    treated_time = BASE + timedelta(days=10)
    treated = historical_state(
        "treated",
        decision_time=treated_time,
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("0"), Decimal("0.5"), Decimal("1")),
        outcome=Decimal("3"),
    )
    controls = (
        historical_state(
            "control-a",
            decision_time=BASE,
            covariates=(Decimal("0"), Decimal("0")),
            pre_path=(Decimal("0"), Decimal("0.5"), Decimal("1")),
            outcome=Decimal("1.5"),
        ),
        historical_state(
            "control-b",
            decision_time=BASE + timedelta(days=1),
            covariates=(Decimal("0.1"), Decimal("0.1")),
            pre_path=(Decimal("0.1"), Decimal("0.6"), Decimal("1.1")),
            outcome=Decimal("1.6"),
        ),
        historical_state(
            "control-c",
            decision_time=BASE + timedelta(days=2),
            covariates=(Decimal("-0.1"), Decimal("-0.1")),
            pre_path=(Decimal("-0.1"), Decimal("0.4"), Decimal("0.9")),
            outcome=Decimal("1.4"),
        ),
        historical_state(
            "far-control",
            decision_time=BASE + timedelta(days=3),
            covariates=(Decimal("10"), Decimal("10")),
            pre_path=(Decimal("10"), Decimal("10"), Decimal("10")),
            outcome=Decimal("10"),
        ),
    )
    return treated, controls, treated_time + timedelta(hours=2)


def test_matching_is_historical_deterministic_and_caliper_bound() -> None:
    treated, controls, as_of = matching_fixture()
    spec = MatchingSpec(spec_id="nearest-v1", matched_count=3, caliper=Decimal("1"))
    result = match_historical_states(
        treated=treated, candidates=tuple(reversed(controls)), spec=spec, as_of_time=as_of
    )
    assert tuple(item.state_id for item in result.matched_controls) == (
        "control-a",
        "control-b",
        "control-c",
    )
    assert sum((item.weight for item in result.matched_controls), Decimal("0")) == 1


def test_matching_rejects_future_and_insufficient_controls() -> None:
    treated, controls, as_of = matching_fixture()
    future = historical_state(
        "future-control",
        decision_time=treated.decision_time + timedelta(seconds=1),
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("0"), Decimal("0.5"), Decimal("1")),
        outcome=Decimal("1"),
    )
    spec = MatchingSpec(spec_id="nearest-v1", matched_count=3, caliper=Decimal("0.0001"))
    with pytest.raises(ValueError, match="CALIPER-REJECTED"):
        match_historical_states(
            treated=treated,
            candidates=(*controls[:3], future),
            spec=spec,
            as_of_time=as_of + timedelta(days=1),
        )


def test_matched_event_study_recovers_difference_in_differences() -> None:
    treated, controls, as_of = matching_fixture()
    matching_spec = MatchingSpec(spec_id="nearest-v1", matched_count=3, caliper=Decimal("1"))
    match = match_historical_states(
        treated=treated,
        candidates=controls,
        spec=matching_spec,
        as_of_time=as_of,
    )
    estimate = estimate_matched_event_study(
        treated=treated,
        controls=controls,
        matched=match,
        matching_spec=matching_spec,
        spec=EventStudySpec(spec_id="did-v1"),
    )
    assert estimate.effect == Decimal("1.5")
    assert estimate.standard_error is None
    assert estimate.confidence_lower is None


def test_matched_event_study_rejects_forged_match_binding() -> None:
    treated, controls, as_of = matching_fixture()
    matching_spec = MatchingSpec(spec_id="nearest-v1", matched_count=3, caliper=Decimal("1"))
    matched = match_historical_states(
        treated=treated,
        candidates=controls,
        spec=matching_spec,
        as_of_time=as_of,
    ).model_copy(update={"treated_state_sha256": "f" * 64})
    with pytest.raises(ValueError, match="AQ-CAUSAL-EVENT-STUDY-MATCH-BINDING-MISMATCH"):
        estimate_matched_event_study(
            treated=treated,
            controls=controls,
            matched=matched,
            matching_spec=matching_spec,
            spec=EventStudySpec(spec_id="did-v1"),
        )


def test_synthetic_control_recovers_known_counterfactual() -> None:
    decision = BASE + timedelta(days=10)
    donor_a = historical_state(
        "donor-a",
        decision_time=BASE,
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("1"), Decimal("2"), Decimal("3")),
        outcome=Decimal("4"),
    )
    donor_b = historical_state(
        "donor-b",
        decision_time=BASE + timedelta(days=1),
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("3"), Decimal("2"), Decimal("1")),
        outcome=Decimal("0"),
    )
    treated = historical_state(
        "treated-synthetic",
        decision_time=decision,
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("1.5"), Decimal("2"), Decimal("2.5")),
        outcome=Decimal("4"),
    )
    result = fit_synthetic_control(
        treated=treated,
        donors=(donor_b, donor_a),
        spec=SyntheticControlSpec(spec_id="simplex-v1"),
        as_of_time=treated.outcome_available_at,
    )
    assert float(result.counterfactual_outcome) == pytest.approx(3.0, abs=1e-5)
    assert float(result.point_estimate.effect) == pytest.approx(1.0, abs=1e-5)
    assert result.pre_treatment_fit.passed is True
    assert sum((item.weight for item in result.donor_weights), Decimal("0")) == 1


def test_synthetic_control_rejects_future_donor_outcome() -> None:
    treated, controls, _ = matching_fixture()
    future_donor = controls[0].model_copy(
        update={"outcome_available_at": treated.decision_time + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="AQ-CAUSAL-SYNTHETIC-DONOR-LOOKAHEAD"):
        fit_synthetic_control(
            treated=treated,
            donors=(future_donor, controls[1]),
            spec=SyntheticControlSpec(spec_id="simplex-v1"),
            as_of_time=treated.outcome_available_at,
        )


def test_aipw_uses_pit_nuisance_predictions_and_recovers_ate() -> None:
    observations = tuple(
        DoublyRobustObservation(
            sample_id=f"sample-{index}",
            decision_time=BASE + timedelta(days=index),
            nuisance_available_at=BASE + timedelta(days=index, seconds=-1),
            nuisance_training_cutoff=BASE + timedelta(days=index, seconds=-2),
            outcome_available_at=BASE + timedelta(days=index, hours=1),
            treated=index >= 2,
            outcome=Decimal("1") if index >= 2 else Decimal("0"),
            propensity_score=Decimal("0.5"),
            predicted_outcome_if_control=Decimal("0"),
            predicted_outcome_if_treated=Decimal("1"),
            nuisance_model_sha256=digest("nuisance-model"),
            feature_snapshot_sha256=digest(f"feature-{index}"),
        )
        for index in range(4)
    )
    estimate = estimate_aipw(
        observations=observations,
        spec=DoublyRobustSpec(spec_id="aipw-v1"),
    )
    assert estimate.effect == Decimal("1")
    assert estimate.standard_error == Decimal("0")

    forged = observations[0].model_copy(
        update={"nuisance_available_at": observations[0].decision_time + timedelta(seconds=1)}
    )
    with pytest.raises(ValidationError, match="AQ-CAUSAL-NUISANCE-LOOKAHEAD"):
        DoublyRobustObservation.model_validate(forged.model_dump())


def test_aipw_fails_closed_on_positivity_violation() -> None:
    observations = tuple(
        DoublyRobustObservation(
            sample_id=f"sample-{index}",
            decision_time=BASE + timedelta(days=index),
            nuisance_available_at=BASE + timedelta(days=index),
            nuisance_training_cutoff=BASE + timedelta(days=index),
            outcome_available_at=BASE + timedelta(days=index, hours=1),
            treated=index >= 2,
            outcome=Decimal(index >= 2),
            propensity_score=Decimal("0.99") if index == 3 else Decimal("0.5"),
            predicted_outcome_if_control=Decimal("0"),
            predicted_outcome_if_treated=Decimal("1"),
            nuisance_model_sha256=digest("nuisance-model"),
            feature_snapshot_sha256=digest(f"feature-{index}"),
        )
        for index in range(4)
    )
    with pytest.raises(ValueError, match="POSITIVITY-FAILED"):
        estimate_aipw(
            observations=observations,
            spec=DoublyRobustSpec(spec_id="aipw-v1"),
        )
