from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.identifiers import EventId
from aegisquant.research.causal import (
    CausalEstimand,
    CausalMethod,
    CausalPointEstimate,
    IdentificationStatus,
    PlaceboKind,
    assemble_causal_diagnostics,
    build_causal_effect_estimate,
    covariate_balance_report,
    evaluate_placebo_distribution,
    pre_treatment_fit_report,
    pretrend_report,
    propensity_overlap_report,
    treatment_permutation_placebo,
)
from tests.v5_p06.helpers import ASSET, BASE, INSTRUMENT, response_dataset


def passing_placebos(effect: Decimal):
    zeroes = tuple(Decimal("0") for _ in range(19))
    return (
        evaluate_placebo_distribution(
            kind=PlaceboKind.EVENT_TIMESTAMP,
            observed_effect=effect,
            placebo_effects=zeroes,
        ),
        evaluate_placebo_distribution(
            kind=PlaceboKind.ASSET,
            observed_effect=effect,
            placebo_effects=zeroes,
        ),
        treatment_permutation_placebo(
            outcomes=tuple(Decimal("0") for _ in range(10))
            + tuple(Decimal("1") for _ in range(10)),
            treatments=tuple(False for _ in range(10)) + tuple(True for _ in range(10)),
            draws=99,
            seed=7,
        ),
    )


def passing_diagnostics(*, unresolved: tuple[str, ...] = ()):
    treated_path = (Decimal("0"), Decimal("0.1"), Decimal("0.2"))
    fit = pre_treatment_fit_report(
        treated_path=treated_path,
        counterfactual_path=treated_path,
    )
    trend = pretrend_report(
        treated_path=treated_path,
        counterfactual_path=treated_path,
    )
    balance = covariate_balance_report(
        covariate_names=("pre_return", "pre_vol"),
        treated_covariates=((Decimal("0"), Decimal("0")),),
        candidate_covariates=(
            (Decimal("-1"), Decimal("-1")),
            (Decimal("1"), Decimal("1")),
            (Decimal("2"), Decimal("2")),
        ),
        matched_covariates=(
            (Decimal("0"), Decimal("0")),
            (Decimal("0"), Decimal("0")),
            (Decimal("0"), Decimal("0")),
        ),
    )
    overlap = propensity_overlap_report(
        propensity_scores=(Decimal("0.4"), Decimal("0.45"), Decimal("0.55"), Decimal("0.6")),
        treatments=(False, False, True, True),
    )
    return assemble_causal_diagnostics(
        pre_treatment_fit=fit,
        pretrend=trend,
        covariate_balance=balance,
        propensity_overlap=overlap,
        placebo_tests=passing_placebos(Decimal("1")),
        control_count=3,
        unresolved_assumptions=unresolved,
    )


def point_estimate() -> CausalPointEstimate:
    return CausalPointEstimate(
        method=CausalMethod.MATCHED_EVENT_STUDY,
        estimand=CausalEstimand.ATT,
        effect=Decimal("1"),
        standard_error=Decimal("0.1"),
        confidence_lower=Decimal("0.8"),
        confidence_upper=Decimal("1.2"),
        treated_count=1,
        control_count=3,
        estimator_spec_sha256="a" * 64,
    )


def test_all_required_diagnostics_pass_but_development_cannot_claim_causality() -> None:
    diagnostics = passing_diagnostics()
    assert diagnostics.passed is True
    dataset = response_dataset()
    estimate = build_causal_effect_estimate(
        event_id=EventId("event-p06"),
        asset=ASSET,
        instrument_id=INSTRUMENT,
        horizon_seconds=14_400,
        point_estimate=point_estimate(),
        input_dataset_sha256=dataset.dataset_sha256,
        diagnostics=diagnostics,
        evidence_tier=EvidenceTier.DEVELOPMENT,
        available_at=dataset.as_of_time,
    )
    assert estimate.identification_status is IdentificationStatus.DEVELOPMENT_ONLY
    assert estimate.causal_claim_allowed is False
    assert estimate.order_submission_enabled is False
    assert estimate.live_trading_locked is True

    payload = estimate.model_dump(mode="json")
    payload["causal_claim_allowed"] = True
    with pytest.raises(ValidationError, match="causal claim gate"):
        type(estimate).model_validate_json(json.dumps(payload))


def test_unresolved_assumption_fails_diagnostics_and_causal_gate() -> None:
    diagnostics = passing_diagnostics(unresolved=("UNOBSERVED_CONFOUNDING",))
    assert diagnostics.passed is False
    assert diagnostics.reason_codes == ("UNRESOLVED_IDENTIFICATION_ASSUMPTIONS",)
    dataset = response_dataset()
    estimate = build_causal_effect_estimate(
        event_id=EventId("event-p06"),
        asset=ASSET,
        instrument_id=INSTRUMENT,
        horizon_seconds=14_400,
        point_estimate=point_estimate(),
        input_dataset_sha256=dataset.dataset_sha256,
        diagnostics=diagnostics,
        evidence_tier=EvidenceTier.FINAL_HOLDOUT,
        available_at=dataset.as_of_time,
    )
    assert estimate.identification_status is IdentificationStatus.INSUFFICIENT_IDENTIFICATION
    assert estimate.causal_claim_allowed is False


def test_bad_pretrend_and_placebo_fail_closed() -> None:
    fit = pre_treatment_fit_report(
        treated_path=(Decimal("0"), Decimal("0.1"), Decimal("0.2")),
        counterfactual_path=(Decimal("0"), Decimal("0.1"), Decimal("0.2")),
    )
    bad_trend = pretrend_report(
        treated_path=(Decimal("0"), Decimal("1"), Decimal("2")),
        counterfactual_path=(Decimal("0"), Decimal("0"), Decimal("0")),
    )
    balance = covariate_balance_report(
        covariate_names=("x",),
        treated_covariates=((Decimal("0"),),),
        candidate_covariates=((Decimal("-1"),), (Decimal("1"),)),
        matched_covariates=((Decimal("0"),), (Decimal("0"),)),
    )
    overlap = propensity_overlap_report(
        propensity_scores=(Decimal("0.4"), Decimal("0.45"), Decimal("0.55"), Decimal("0.6")),
        treatments=(False, False, True, True),
    )
    bad_placebo = evaluate_placebo_distribution(
        kind=PlaceboKind.EVENT_TIMESTAMP,
        observed_effect=Decimal("1"),
        placebo_effects=tuple(Decimal("2") for _ in range(19)),
    )
    placebos = list(passing_placebos(Decimal("1")))
    placebos[0] = bad_placebo
    diagnostics = assemble_causal_diagnostics(
        pre_treatment_fit=fit,
        pretrend=bad_trend,
        covariate_balance=balance,
        propensity_overlap=overlap,
        placebo_tests=tuple(placebos),
        control_count=3,
    )
    assert diagnostics.passed is False
    assert diagnostics.reason_codes == ("PRE_TREND_FAILED", "PLACEBO_FAILED")


def test_missing_placebo_kind_is_rejected() -> None:
    diagnostics = passing_diagnostics()
    with pytest.raises(ValueError, match="every configured placebo kind"):
        assemble_causal_diagnostics(
            pre_treatment_fit=diagnostics.pre_treatment_fit,
            pretrend=diagnostics.pretrend,
            covariate_balance=diagnostics.covariate_balance,
            propensity_overlap=diagnostics.propensity_overlap,
            placebo_tests=diagnostics.placebo_tests[:-1],
            control_count=3,
        )


def test_pre_treatment_metrics_cannot_be_detached_from_raw_paths() -> None:
    report = passing_diagnostics().pre_treatment_fit
    payload = report.model_dump(mode="json")
    payload["treated_path"][1] = "9"
    with pytest.raises(ValidationError, match="pre-treatment fit metrics mismatch"):
        type(report).model_validate_json(json.dumps(payload))


def test_causal_diagnostic_policy_cannot_be_relaxed_in_payload() -> None:
    diagnostics = passing_diagnostics()
    payload = diagnostics.model_dump(mode="json")
    payload["policy"]["maximum_pre_treatment_nrmse"] = "999"
    payload["pre_treatment_fit"]["maximum_normalized_error"] = "999"
    with pytest.raises(ValidationError, match="AQ-CAUSAL-DIAGNOSTIC-POLICY-NOT-APPROVED"):
        type(diagnostics).model_validate_json(json.dumps(payload))


def test_future_nuisance_timestamp_cannot_be_hidden_by_model_copy() -> None:
    from aegisquant.research.causal import DoublyRobustObservation
    from tests.v5_p06.helpers import digest

    with pytest.raises(ValidationError, match="AQ-CAUSAL-NUISANCE-LOOKAHEAD"):
        DoublyRobustObservation(
            sample_id="future-nuisance",
            decision_time=BASE,
            nuisance_available_at=BASE + timedelta(seconds=1),
            nuisance_training_cutoff=BASE,
            outcome_available_at=BASE + timedelta(hours=1),
            treated=True,
            outcome=Decimal("1"),
            propensity_score=Decimal("0.5"),
            predicted_outcome_if_control=Decimal("0"),
            predicted_outcome_if_treated=Decimal("1"),
            nuisance_model_sha256=digest("future-nuisance"),
            feature_snapshot_sha256=digest("future-feature"),
        )


def test_future_nuisance_training_cutoff_is_rejected() -> None:
    from aegisquant.research.causal import DoublyRobustObservation
    from tests.v5_p06.helpers import digest

    with pytest.raises(ValidationError, match="AQ-CAUSAL-NUISANCE-TRAINING-LOOKAHEAD"):
        DoublyRobustObservation(
            sample_id="future-training",
            decision_time=BASE,
            nuisance_available_at=BASE,
            nuisance_training_cutoff=BASE + timedelta(seconds=1),
            outcome_available_at=BASE + timedelta(hours=1),
            treated=True,
            outcome=Decimal("1"),
            propensity_score=Decimal("0.5"),
            predicted_outcome_if_control=Decimal("0"),
            predicted_outcome_if_treated=Decimal("1"),
            nuisance_model_sha256=digest("future-training"),
            feature_snapshot_sha256=digest("future-training-feature"),
        )


def test_overlap_requires_both_treatment_groups() -> None:
    with pytest.raises(ValidationError, match="two treated and two controls"):
        propensity_overlap_report(
            propensity_scores=(Decimal("0.5"),) * 4,
            treatments=(True,) * 4,
        )
