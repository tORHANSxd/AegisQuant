"""Generate or verify deterministic V5-P06 causal-layer evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.identifiers import ArtifactId, AssetId, EventId, InstrumentId
from aegisquant.research.causal import (
    DEFAULT_CAUSAL_DIAGNOSTIC_POLICY,
    DoublyRobustObservation,
    DoublyRobustSpec,
    EventResponseRow,
    EventStudySpec,
    HistoricalState,
    MatchingSpec,
    PlaceboKind,
    SyntheticControlSpec,
    assemble_causal_diagnostics,
    build_causal_effect_estimate,
    build_event_response_dataset,
    covariate_balance_report,
    estimate_aipw,
    estimate_matched_event_study,
    evaluate_placebo_distribution,
    fit_synthetic_control,
    match_historical_states,
    pre_treatment_fit_report,
    pretrend_report,
    propensity_overlap_report,
    treatment_permutation_placebo,
)

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "reports/v5/P06/CAUSAL_LAYER_EVIDENCE.json"
BASE_TIME: Final = datetime(2026, 1, 1, tzinfo=UTC)
ASSET: Final = AssetId("asset:BTC")
INSTRUMENT: Final = InstrumentId("BINANCE:SPOT:BTCUSDT")


def _digest(label: str) -> str:
    return canonical_sha256({"v5_p06_fixture": label})


def _response_row(index: int) -> EventResponseRow:
    decision = BASE_TIME + timedelta(days=index * 8)
    actual = Decimal("3.5") + Decimal(index) / Decimal("10")
    expected = Decimal("3.0")
    return EventResponseRow(
        event_id=EventId(f"event:p06:{index}"),
        event_revision_id=ArtifactId(_digest(f"event-revision:{index}")),
        canonical_event_sha256=_digest(f"canonical-event:{index}"),
        event_type="MACRO_RELEASE",
        asset=ASSET,
        instrument_id=INSTRUMENT,
        decision_time=decision,
        event_available_at=decision - timedelta(seconds=1),
        feature_available_at=decision,
        label_start_time=decision + timedelta(minutes=1),
        label_end_time=decision + timedelta(days=7),
        outcome_available_at=decision + timedelta(days=7, minutes=1),
        truth_probability_at_t=Decimal("0.97"),
        source_quality_at_t=Decimal("0.93"),
        novelty_at_t=Decimal("0.80"),
        market_reflection_at_t=Decimal("0.35"),
        actual=actual,
        expected=expected,
        surprise=actual - expected,
        regime="NEWS_SHOCK",
        pre_event_returns=(Decimal("-0.01"), Decimal("0"), Decimal("0.01")),
        pre_event_vol=Decimal("0.02"),
        spread=Decimal("0.0002"),
        depth=Decimal("1000000"),
        funding=Decimal("0.0001"),
        basis=Decimal("0.001"),
        open_interest=Decimal("5000000"),
        liquidations=Decimal("25000"),
        cross_asset_state=(Decimal("0.1"), Decimal("-0.1")),
        narrative_state=(Decimal("0.6"), Decimal("0.4")),
        return_5m=Decimal("0.001"),
        return_30m=Decimal("0.004"),
        return_4h=Decimal("0.009"),
        return_1d=Decimal("0.012"),
        return_7d=Decimal("0.018"),
        vol_delta=Decimal("0.003"),
        liquidity_delta=Decimal("-0.02"),
        tail_event=False,
        maximum_favorable_excursion=Decimal("0.025"),
        maximum_adverse_excursion=Decimal("-0.006"),
        source_dataset_ids=("official-events", "public-market"),
        feature_snapshot_sha256=_digest(f"feature:{index}"),
        label_sha256=_digest(f"label:{index}"),
        universe_snapshot_sha256=_digest(f"universe:{index}"),
    )


def _historical_state(
    state_id: str,
    *,
    decision_time: datetime,
    covariates: tuple[Decimal, Decimal],
    pre_path: tuple[Decimal, Decimal, Decimal],
    outcome: Decimal,
) -> HistoricalState:
    return HistoricalState(
        state_id=state_id,
        asset=ASSET,
        instrument_id=INSTRUMENT,
        regime="NEWS_SHOCK",
        decision_time=decision_time,
        feature_available_at=decision_time,
        outcome_available_at=decision_time + timedelta(hours=1),
        covariate_names=("pre_return", "pre_vol"),
        covariates=covariates,
        pre_treatment_outcomes=pre_path,
        outcome=outcome,
        source_sha256=_digest(f"state:{state_id}"),
    )


def _passing_placebos(effect: Decimal):
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


def build_payload() -> dict[str, object]:
    rows = tuple(_response_row(index) for index in range(4))
    dataset = build_event_response_dataset(
        dataset_id="p06-event-response-development",
        evidence_tier=EvidenceTier.DEVELOPMENT,
        as_of_time=rows[-1].outcome_available_at,
        created_at=rows[-1].outcome_available_at + timedelta(seconds=1),
        rows=rows,
        feature_definition_hashes=(_digest("feature-definition"),),
        label_definition_hashes=(_digest("label-definition"),),
        cost_policy_sha256=_digest("cost-policy"),
    )

    treated = _historical_state(
        "treated",
        decision_time=BASE_TIME + timedelta(days=10),
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("0"), Decimal("0.5"), Decimal("1")),
        outcome=Decimal("3"),
    )
    controls = (
        _historical_state(
            "control-a",
            decision_time=BASE_TIME,
            covariates=(Decimal("0"), Decimal("0")),
            pre_path=(Decimal("0"), Decimal("0.5"), Decimal("1")),
            outcome=Decimal("1.5"),
        ),
        _historical_state(
            "control-b",
            decision_time=BASE_TIME + timedelta(days=1),
            covariates=(Decimal("0.1"), Decimal("0.1")),
            pre_path=(Decimal("0.1"), Decimal("0.6"), Decimal("1.1")),
            outcome=Decimal("1.6"),
        ),
        _historical_state(
            "control-c",
            decision_time=BASE_TIME + timedelta(days=2),
            covariates=(Decimal("-0.1"), Decimal("-0.1")),
            pre_path=(Decimal("-0.1"), Decimal("0.4"), Decimal("0.9")),
            outcome=Decimal("1.4"),
        ),
    )
    matching_spec = MatchingSpec(spec_id="nearest-v1", matched_count=3, caliper=Decimal("2"))
    matched = match_historical_states(
        treated=treated,
        candidates=tuple(reversed(controls)),
        spec=matching_spec,
        as_of_time=treated.outcome_available_at,
    )
    matched_estimate = estimate_matched_event_study(
        treated=treated,
        controls=controls,
        matched=matched,
        matching_spec=matching_spec,
        spec=EventStudySpec(spec_id="did-v1"),
    )

    donor_a = _historical_state(
        "donor-a",
        decision_time=BASE_TIME,
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("1"), Decimal("2"), Decimal("3")),
        outcome=Decimal("4"),
    )
    donor_b = _historical_state(
        "donor-b",
        decision_time=BASE_TIME + timedelta(days=1),
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("3"), Decimal("2"), Decimal("1")),
        outcome=Decimal("0"),
    )
    synthetic_treated = _historical_state(
        "treated-synthetic",
        decision_time=BASE_TIME + timedelta(days=10),
        covariates=(Decimal("0"), Decimal("0")),
        pre_path=(Decimal("1.5"), Decimal("2"), Decimal("2.5")),
        outcome=Decimal("4"),
    )
    synthetic = fit_synthetic_control(
        treated=synthetic_treated,
        donors=(donor_b, donor_a),
        spec=SyntheticControlSpec(spec_id="simplex-v1"),
        as_of_time=synthetic_treated.outcome_available_at,
    )

    nuisance_observations = tuple(
        DoublyRobustObservation(
            sample_id=f"sample-{index}",
            decision_time=BASE_TIME + timedelta(days=index),
            nuisance_available_at=BASE_TIME + timedelta(days=index, seconds=-1),
            nuisance_training_cutoff=BASE_TIME + timedelta(days=index, seconds=-2),
            outcome_available_at=BASE_TIME + timedelta(days=index, hours=1),
            treated=index >= 2,
            outcome=Decimal("1") if index >= 2 else Decimal("0"),
            propensity_score=Decimal("0.5"),
            predicted_outcome_if_control=Decimal("0"),
            predicted_outcome_if_treated=Decimal("1"),
            nuisance_model_sha256=_digest("nuisance-model"),
            feature_snapshot_sha256=_digest(f"nuisance-feature:{index}"),
        )
        for index in range(4)
    )
    aipw = estimate_aipw(
        observations=nuisance_observations,
        spec=DoublyRobustSpec(spec_id="aipw-v1"),
    )

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
    placebos = _passing_placebos(matched_estimate.effect)
    diagnostics = assemble_causal_diagnostics(
        pre_treatment_fit=fit,
        pretrend=trend,
        covariate_balance=balance,
        propensity_overlap=overlap,
        placebo_tests=placebos,
        control_count=3,
    )
    estimate = build_causal_effect_estimate(
        event_id=rows[0].event_id,
        asset=ASSET,
        instrument_id=INSTRUMENT,
        horizon_seconds=14_400,
        point_estimate=matched_estimate,
        input_dataset_sha256=dataset.dataset_sha256,
        diagnostics=diagnostics,
        evidence_tier=EvidenceTier.DEVELOPMENT,
        available_at=dataset.as_of_time,
    )

    failed_trend = pretrend_report(
        treated_path=(Decimal("0"), Decimal("1"), Decimal("2")),
        counterfactual_path=(Decimal("0"), Decimal("0"), Decimal("0")),
    )
    failed_diagnostics = assemble_causal_diagnostics(
        pre_treatment_fit=fit,
        pretrend=failed_trend,
        covariate_balance=balance,
        propensity_overlap=overlap,
        placebo_tests=placebos,
        control_count=3,
    )
    failed_estimate = build_causal_effect_estimate(
        event_id=rows[0].event_id,
        asset=ASSET,
        instrument_id=INSTRUMENT,
        horizon_seconds=14_400,
        point_estimate=matched_estimate,
        input_dataset_sha256=dataset.dataset_sha256,
        diagnostics=failed_diagnostics,
        evidence_tier=EvidenceTier.FINAL_HOLDOUT,
        available_at=dataset.as_of_time,
    )

    checks = {
        "event_response_dataset_is_pit_revision_aware_and_content_addressed": (
            dataset.point_in_time
            and dataset.revision_aware
            and not dataset.shuffle
            and len(dataset.rows) == 4
            and all(row.outcome_available_at <= dataset.as_of_time for row in dataset.rows)
        ),
        "matched_controls_are_historical_deterministic_and_normalized": (
            tuple(item.state_id for item in matched.matched_controls)
            == ("control-a", "control-b", "control-c")
            and sum((item.weight for item in matched.matched_controls), Decimal("0")) == 1
        ),
        "synthetic_control_converges_with_passing_pre_treatment_fit": (
            synthetic.converged and synthetic.pre_treatment_fit.passed
        ),
        "aipw_uses_pit_nuisance_predictions": (
            aipw.effect == Decimal("1")
            and all(
                item.nuisance_available_at <= item.decision_time for item in nuisance_observations
            )
        ),
        "all_required_causal_diagnostics_pass": (
            diagnostics.passed
            and {item.kind for item in diagnostics.placebo_tests} == set(PlaceboKind)
        ),
        "development_evidence_never_claims_causality": (
            not estimate.causal_claim_allowed
            and estimate.identification_status.value == "DEVELOPMENT_ONLY"
        ),
        "bad_pretrend_blocks_even_final_holdout_claim": (
            not failed_diagnostics.passed
            and "PRE_TREND_FAILED" in failed_diagnostics.reason_codes
            and not failed_estimate.causal_claim_allowed
        ),
        "all_outputs_remain_non_trading": (
            estimate.live_trading_locked
            and not estimate.order_submission_enabled
            and not estimate.alpha_promotion_eligible
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"V5-P06 causal evidence checks failed: {checks}")

    return {
        "schema_version": "1.0.0",
        "phase": "V5-P06",
        "evidence_tier": EvidenceTier.DEVELOPMENT.value,
        "alpha_promotion_eligible": False,
        "real_world_forecast_accuracy_claimed": False,
        "causal_claim_allowed": False,
        "live_trading_locked": True,
        "order_submission_enabled": False,
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "dataset_sha256": dataset.dataset_sha256,
            "row_count": len(dataset.rows),
            "row_hashes": [{"row_sha256": row.row_sha256} for row in dataset.rows],
            "as_of_time": dataset.as_of_time.isoformat().replace("+00:00", "Z"),
            "source_dataset_ids": list(dataset.source_dataset_ids),
        },
        "matching": matched.model_dump(mode="json"),
        "matched_event_study": matched_estimate.model_dump(mode="json"),
        "synthetic_control": synthetic.model_dump(mode="json"),
        "doubly_robust_aipw": aipw.model_dump(mode="json"),
        "diagnostic_policy": DEFAULT_CAUSAL_DIAGNOSTIC_POLICY.model_dump(mode="json"),
        "diagnostics": diagnostics.model_dump(mode="json"),
        "causal_effect_gate": estimate.model_dump(mode="json"),
        "negative_control": {
            "diagnostics": failed_diagnostics.model_dump(mode="json"),
            "effect_gate": failed_estimate.model_dump(mode="json"),
        },
        "claim_boundaries": {
            "correlation": "DESCRIPTIVE_ONLY_NOT_CAUSAL",
            "predictive_increment": "NOT_EVALUATED_IN_P06",
            "causal_effect": "DEVELOPMENT_ONLY_NO_REAL_WORLD_CLAIM",
        },
        "checks": checks,
        "acceptance_traceability": {
            "pre_treatment_fit_report": [
                "tests/v5_p06/test_causal_estimators.py::test_synthetic_control_recovers_known_counterfactual",
                "tests/v5_p06/test_causal_diagnostics.py::test_pre_treatment_metrics_cannot_be_detached_from_raw_paths",
            ],
            "event_timestamp_placebo": [
                "tests/v5_p06/test_causal_diagnostics.py::test_all_required_diagnostics_pass_but_development_cannot_claim_causality",
            ],
            "asset_placebo": [
                "tests/v5_p06/test_causal_diagnostics.py::test_missing_placebo_kind_is_rejected",
            ],
            "permutation_tests": [
                "tests/v5_p06/test_causal_diagnostics.py::test_bad_pretrend_and_placebo_fail_closed",
            ],
            "causal_claim_only_when_diagnostics_pass": [
                "tests/v5_p06/test_causal_diagnostics.py::test_unresolved_assumption_fails_diagnostics_and_causal_gate",
                "tests/v5_p06/test_causal_diagnostics.py::test_causal_diagnostic_policy_cannot_be_relaxed_in_payload",
            ],
            "canonical_event_and_pit_binding": [
                "tests/v5_p06/test_event_response_dataset.py::test_event_response_row_factory_binds_one_canonical_revision",
                "tests/v5_p06/test_event_response_dataset.py::test_dataset_rejects_one_revision_id_bound_to_different_events",
            ],
        },
        "limitations": [
            "All estimates are deterministic DEVELOPMENT fixtures, not real public market evidence.",
            "Matching, synthetic control, and AIPW identify effects only under untestable design assumptions.",
            "A passing diagnostic bundle does not promote DEVELOPMENT evidence into a causal claim.",
            "Predictive increment, economic value after costs, and real-world forecast accuracy remain untested.",
            "No trading, order submission, account connection, or alpha promotion path is enabled.",
        ],
        "result": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"V5-P06 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P06 causal-layer evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P06 causal-layer evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
