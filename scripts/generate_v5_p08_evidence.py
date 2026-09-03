"""Generate deterministic V5-P08 truth-aware event forecast evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.research.forecasting import (
    EventAblationArm,
    EventConditionSnapshot,
    EventIncrement,
    FoldEvaluationState,
    compute_event_increment,
    create_event_ablation_evaluation,
    create_event_condition_snapshot,
    evaluate_event_forecast_ablation,
)
from tests.v5_p05.test_canonical_events import AS_OF, canonical
from tests.v5_p08.helpers import (
    DEFAULT_ABLATION_LOSSES,
    ablation_evaluations,
    ablation_spec,
    comparison_lineage,
    digest,
    event_condition,
    forecast_pair,
    metrics,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "v5" / "P08" / "EVENT_FORECAST_EVIDENCE.json"


def _rejected(operation: Callable[[], object], expected_code: str) -> bool:
    try:
        operation()
    except (TypeError, ValueError) as error:
        return expected_code in str(error)
    return False


def _validate_json(model: type[EventConditionSnapshot], payload: dict[str, object]) -> object:
    return model.model_validate_json(json.dumps(payload))


def _forged_snapshot_payload() -> dict[str, object]:
    payload = event_condition().model_dump(mode="json")
    features = payload["features"]
    if not isinstance(features, dict):
        raise TypeError("event feature payload must be a mapping")
    features["truth_probability_at_t"] = "0.10"
    payload["snapshot_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "snapshot_sha256"}
    )
    return payload


def _forged_increment_payload(increment: EventIncrement) -> dict[str, object]:
    payload = increment.model_dump(mode="json")
    by_horizon = payload["by_horizon"]
    if not isinstance(by_horizon, dict):
        raise TypeError("event increment payload must contain a horizon mapping")
    by_horizon["delta_expected_return"] = "0.50"
    payload["increment_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "increment_sha256"}
    )
    return payload


def build_payload() -> dict[str, object]:
    market_only, event_conditioned = forecast_pair()
    increment = compute_event_increment(
        market_only=market_only,
        event_conditioned=event_conditioned,
    )
    condition = event_condition()
    evaluations = ablation_evaluations()
    negative_ablation = evaluate_event_forecast_ablation(
        spec=ablation_spec(),
        event_condition=condition,
        evaluations=evaluations,
    )
    passing_losses = dict(DEFAULT_ABLATION_LOSSES)
    passing_losses[EventAblationArm.TRUTH_PERMUTED] = Decimal("0.25")
    passing_ablation = evaluate_event_forecast_ablation(
        spec=ablation_spec(),
        event_condition=condition,
        evaluations=ablation_evaluations(losses=passing_losses),
    )
    rumor_condition = event_condition(status=EventClusterStatus.RUMOR)
    _, rumor_forecast = forecast_pair(
        condition=rumor_condition,
        event_should_abstain=True,
    )

    unequal_folds = tuple(
        item
        for item in evaluations
        if not (item.arm is EventAblationArm.EVENT_ONLY and item.lineage.fold_id == "fold-2")
    )
    reused_predictions = list(evaluations)
    first, second = reused_predictions[:2]
    reused_predictions[1] = create_event_ablation_evaluation(
        arm=second.arm,
        lineage=second.lineage,
        event_condition_snapshot_sha256=second.event_condition_snapshot_sha256,
        permutation_plan_sha256=second.permutation_plan_sha256,
        prediction_artifact_sha256=first.prediction_artifact_sha256,
        state=second.state,
        metrics=second.metrics,
        abstain_or_failure_reason=second.abstain_or_failure_reason,
    )
    _, other_fold_event = forecast_pair(fold_number=2)
    negative_controls = {
        "future_event_revision_rejected": _rejected(
            lambda: create_event_condition_snapshot(
                canonical_event=canonical(),
                instrument_id=condition.instrument_id,
                asset_id=condition.asset_id,
                decision_time=AS_OF - timedelta(seconds=1),
                asset_relationship_score=Decimal("0.9"),
                relationship_snapshot_sha256=digest("relationship"),
            ),
            "LOOKAHEAD",
        ),
        "self_consistent_truth_feature_splice_rejected": _rejected(
            lambda: _validate_json(EventConditionSnapshot, _forged_snapshot_payload()),
            "FEATURE-BINDING-MISMATCH",
        ),
        "forecast_lineage_splice_rejected": _rejected(
            lambda: compute_event_increment(
                market_only=market_only,
                event_conditioned=other_fold_event,
            ),
            "LINEAGE-MISMATCH",
        ),
        "self_consistent_increment_delta_forgery_rejected": _rejected(
            lambda: EventIncrement.model_validate_json(
                json.dumps(_forged_increment_payload(increment))
            ),
            "RECOMPUTATION-MISMATCH",
        ),
        "unequal_oos_folds_rejected": _rejected(
            lambda: evaluate_event_forecast_ablation(
                spec=ablation_spec(),
                event_condition=condition,
                evaluations=unequal_folds,
            ),
            "UNEQUAL-OOS-FOLDS",
        ),
        "prediction_artifact_reuse_rejected": _rejected(
            lambda: evaluate_event_forecast_ablation(
                spec=ablation_spec(),
                event_condition=condition,
                evaluations=tuple(reused_predictions),
            ),
            "PREDICTION-REUSE",
        ),
        "permutation_without_precommitted_plan_rejected": _rejected(
            lambda: create_event_ablation_evaluation(
                arm=EventAblationArm.TRUTH_PERMUTED,
                lineage=comparison_lineage(),
                event_condition_snapshot_sha256=condition.snapshot_sha256,
                permutation_plan_sha256=None,
                prediction_artifact_sha256=digest("prediction"),
                state=FoldEvaluationState.EVALUATED,
                metrics=metrics(Decimal("0.3")),
                abstain_or_failure_reason=None,
            ),
            "PERMUTATION-PLAN-MISMATCH",
        ),
        "rumor_directional_forecast_without_abstention_rejected": _rejected(
            lambda: forecast_pair(condition=rumor_condition),
            "DIRECTIONAL-DENIAL-MUST-ABSTAIN",
        ),
    }

    event_features = condition.features.model_dump(mode="json")
    ablation_result = negative_ablation.results[0]
    required_feature_names = {
        "truth_probability_at_t",
        "source_quality_at_t",
        "independent_evidence_count",
        "evidence_dependency_score",
        "novelty_at_t",
        "market_reflection_at_t",
        "surprise_at_t",
        "event_type",
        "narrative_independent_source_count",
    }
    source_scale_offenders = tuple(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "aegisquant").rglob("*.py")
        if "HORIZON_SCALE =" in path.read_text(encoding="utf-8")
    )
    checks = {
        "market_and_event_forecasts_share_exact_oos_inputs": (
            market_only.lineage == event_conditioned.lineage
            and market_only.inputs.market_state_tensor
            == event_conditioned.inputs.market_state_tensor
            and market_only.inputs.calibrations == event_conditioned.inputs.calibrations
            and market_only.inputs.capability == event_conditioned.inputs.capability
        ),
        "truth_aware_event_features_are_complete_and_pit_bound": (
            required_feature_names <= set(event_features)
            and condition.canonical_event.available_at <= condition.decision_time
            and condition.snapshot_sha256 == event_conditioned.event_condition.snapshot_sha256
        ),
        "event_increment_is_recomputed_for_return_vol_tail_and_liquidity": (
            increment.by_horizon.delta_expected_return == Decimal("0.005")
            and increment.by_horizon.delta_realized_volatility == Decimal("0.02")
            and increment.by_horizon.delta_tail_risk_probability == Decimal("0.03")
            and increment.by_horizon.delta_liquidity == Decimal("-10")
        ),
        "ablation_includes_all_modes_permutations_and_placebos": (
            set(ablation_result.mean_primary_loss_by_arm) == set(EventAblationArm)
            and ablation_result.event_only_and_risk_only_reported
            and negative_ablation.truth_and_event_permutations_reported
        ),
        "truth_permutation_negative_result_is_preserved": (
            ablation_result.market_event_beats_market_only
            and not ablation_result.truth_permutation_degrades
            and not ablation_result.event_increment_gate_passed_in_fixture
            and negative_ablation.fixture_supported_horizons == ()
        ),
        "fixture_gate_requires_every_permutation_to_degrade": (
            passing_ablation.results[0].event_increment_gate_passed_in_fixture
            and bool(passing_ablation.fixture_supported_horizons)
            and passing_ablation.alpha_promotion_eligible is False
        ),
        "rumor_is_risk_overlay_only_and_directionally_abstains": (
            rumor_condition.risk_overlay_only
            and not rumor_condition.directional_candidate_allowed
            and rumor_forecast.inputs.forecast.should_abstain
            and not rumor_forecast.order_submission_enabled
        ),
        "production_source_has_no_fixed_horizon_scale_table": not source_scale_offenders,
        "all_outputs_remain_development_non_trading": (
            market_only.alpha_promotion_eligible is False
            and event_conditioned.alpha_promotion_eligible is False
            and increment.real_world_increment_claimed is False
            and negative_ablation.real_world_event_increment_claimed is False
            and negative_ablation.live_trading_locked
            and not negative_ablation.order_submission_enabled
        ),
        "negative_controls_fail_closed": all(negative_controls.values()),
    }
    if not all(checks.values()):
        raise RuntimeError(f"V5-P08 evidence checks failed: {checks}")

    return {
        "schema_version": "v5-p08-truth-aware-event-forecast-evidence-v1",
        "phase": "V5-P08",
        "fixture_kind": "DETERMINISTIC_CONTRACT_FIXTURE",
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "real_world_forecast_accuracy_claimed": False,
        "real_world_event_increment_claimed": False,
        "causal_effect_claimed": False,
        "final_holdout_opened": False,
        "live_trading_locked": True,
        "order_submission_enabled": False,
        "fixed_horizon_scale_used": False,
        "market_only_forecast": market_only.model_dump(mode="json"),
        "event_conditioned_forecast": event_conditioned.model_dump(mode="json"),
        "event_increment": increment.model_dump(mode="json"),
        "rumor_event_condition": rumor_condition.model_dump(mode="json"),
        "rumor_event_forecast": rumor_forecast.model_dump(mode="json"),
        "negative_ablation_report": negative_ablation.model_dump(mode="json"),
        "all_permutations_degrade_fixture_report": passing_ablation.model_dump(mode="json"),
        "negative_controls": negative_controls,
        "fixed_horizon_scale_source_offenders": list(source_scale_offenders),
        "checks": checks,
        "acceptance_traceability": {
            "market_only_event_conditioned_and_increment_contracts": [
                "tests/v5_p08/test_event_forecasts.py::test_market_and_event_forecasts_share_exact_oos_inputs",
                "tests/v5_p08/test_event_forecasts.py::test_event_increment_is_recomputed_for_each_forecast_target",
            ],
            "truth_pit_rumor_and_splice_boundaries": [
                "tests/v5_p08/test_event_forecasts.py::test_event_condition_snapshot_rejects_self_consistent_truth_feature_splice",
                "tests/v5_p08/test_event_forecasts.py::test_rumor_is_risk_overlay_only_and_directional_forecast_must_abstain",
            ],
            "ablation_and_permutation_gates": [
                "tests/v5_p08/test_event_ablation.py::test_ablation_reports_all_four_modes_and_all_placebos_by_horizon",
                "tests/v5_p08/test_event_ablation.py::test_ablation_fixture_gate_requires_every_permutation_to_degrade",
            ],
            "fixed_scale_retirement": [
                "tests/v5_p08/test_event_forecasts.py::test_production_source_has_no_fixed_horizon_scale_table",
            ],
        },
        "limitations": [
            "All metrics are deterministic contract fixtures; no real public market data is evaluated in V5-P08.",
            "Content hashes prove integrity and cross-binding, not the external truth of a split or prediction; the frozen phase manifest is the trust anchor.",
            "The fixture intentionally records that truth permutation did not materially degrade loss, so event alpha is not established.",
            "A passing synthetic permutation fixture is only a validator test and never authorizes alpha promotion.",
            "Final holdout, forward paper/shadow/testnet gates, order submission, and live trading remain closed.",
        ],
        "result": "PASS_WITH_RECORDED_NEGATIVE_RESULT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"V5-P08 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P08 truth-aware event forecast evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P08 truth-aware event forecast evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
