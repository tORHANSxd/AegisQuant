"""Generate deterministic V5-P07 Forecast Council 2.0 contract evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from aegisquant.domain.identifiers import AssetId
from aegisquant.research.forecasting import (
    CalibrationArtifact,
    CapabilityStatus,
    CouncilHorizon,
    FoldEvaluationState,
    ForecastEnvelope,
    ForecastModelClass,
    ForecastQuantiles,
    MarketRegime,
    ModelArenaSpec,
    capability_matrix_sha256,
    default_capability_matrix,
    evaluate_candidate_gate,
    evaluate_vision_ablation,
    run_model_arena,
    validate_market_state_tensor,
)
from tests.v5_p07.helpers import (
    budget,
    calibration,
    capability,
    fold,
    forecast_envelope,
    gate,
    instant,
    market_tensor,
    request,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "v5" / "P07" / "FORECAST_COUNCIL_EVIDENCE.json"


def _rejected(operation: Callable[[], object], expected_code: str) -> bool:
    try:
        operation()
    except (TypeError, ValueError) as error:
        return expected_code in str(error)
    return False


def _arena_evaluations():
    return (
        fold(candidate_id="linear-baseline", fold_number=1, loss="0.10"),
        fold(candidate_id="linear-baseline", fold_number=2, loss="0.10"),
        fold(candidate_id="tcn-candidate", fold_number=1, loss="0.05"),
        fold(candidate_id="tcn-candidate", fold_number=2, loss="0.06"),
        fold(
            candidate_id="multi-scale-patch-transformer-candidate",
            fold_number=1,
            loss="0",
            state=FoldEvaluationState.FAILED,
            failure_reason="SIMULATED_OOM",
        ),
        fold(
            candidate_id="multi-scale-patch-transformer-candidate",
            fold_number=2,
            loss="0",
            state=FoldEvaluationState.FAILED,
            failure_reason="SIMULATED_OOM",
        ),
        fold(
            candidate_id="linear-baseline",
            fold_number=1,
            loss="0.08",
            asset="ETH",
            horizon=CouncilHorizon.FOUR_HOURS,
            regime=MarketRegime.VOL_EXPANSION,
        ),
        fold(
            candidate_id="linear-baseline",
            fold_number=2,
            loss="0.08",
            asset="ETH",
            horizon=CouncilHorizon.FOUR_HOURS,
            regime=MarketRegime.VOL_EXPANSION,
        ),
        fold(
            candidate_id="tcn-candidate",
            fold_number=1,
            loss="0.095",
            asset="ETH",
            horizon=CouncilHorizon.FOUR_HOURS,
            regime=MarketRegime.VOL_EXPANSION,
        ),
        fold(
            candidate_id="tcn-candidate",
            fold_number=2,
            loss="0.095",
            asset="ETH",
            horizon=CouncilHorizon.FOUR_HOURS,
            regime=MarketRegime.VOL_EXPANSION,
        ),
    )


def build_payload() -> dict[str, object]:
    matrix = default_capability_matrix(as_of_time=instant(20))
    tensor = market_tensor()
    calibration_artifact = calibration()
    forecast = forecast_envelope(tensor=tensor, artifact=calibration_artifact)
    allowed_gates = (
        gate("linear-baseline"),
        gate("tcn-candidate"),
        gate("multi-scale-patch-transformer-candidate"),
    )
    blocked_gate = evaluate_candidate_gate(
        capability=capability("chronos-2-candidate"),
        budget=budget(),
        request=request(),
        dependency_available=False,
        weights_verified=False,
    )
    spec = ModelArenaSpec(
        baseline_candidate_id="linear-baseline",
        expected_fold_count=2,
        minimum_absolute_improvement=Decimal("0.01"),
        evaluation_cutoff=instant(20),
    )
    evaluations = _arena_evaluations()
    vision_ablation = evaluate_vision_ablation(
        asset_id=AssetId("BTC"),
        horizon=CouncilHorizon.THIRTY_MINUTES,
        regime=MarketRegime.TREND,
        numeric_only_loss=Decimal("0.10"),
        vision_only_loss=Decimal("0.13"),
        numeric_vision_loss=Decimal("0.095"),
        minimum_absolute_improvement=Decimal("0.01"),
    )
    arena = run_model_arena(
        spec=spec,
        capability_matrix=matrix,
        gate_decisions=allowed_gates,
        evaluations=evaluations,
        vision_ablations=(vision_ablation,),
    )

    unequal_folds = list(evaluations[:4])
    unequal_folds[2] = unequal_folds[2].model_copy(
        update={"test_sample_ids": ("future-a", "future-b")}
    )
    forged_gate = allowed_gates[1].model_copy(update={"capability_sha256": "f" * 64})
    future_tensor = tensor.model_copy(
        update={
            "available_at": (
                *tensor.available_at[:-1],
                tensor.decision_time + timedelta(seconds=1),
            )
        }
    )
    leaking_calibration = calibration_artifact.model_copy(
        update={"calibration_sample_ids": calibration_artifact.forbidden_test_sample_ids}
    )
    changed_horizon = forecast.horizons[0].model_copy(
        update={"tail_risk_probability": Decimal("0.90")}
    )
    forged_forecast = forecast.model_copy(update={"horizons": (changed_horizon,)})
    forged_allowed_gate = blocked_gate.model_copy(
        update={"allowed_to_evaluate": True, "block_reasons": ()}
    )
    blocked_attack_evaluations = (
        fold(candidate_id="linear-baseline", fold_number=1, loss="0.10"),
        fold(candidate_id="linear-baseline", fold_number=2, loss="0.10"),
        fold(candidate_id="chronos-2-candidate", fold_number=1, loss="0.05"),
        fold(candidate_id="chronos-2-candidate", fold_number=2, loss="0.05"),
    )
    future_evaluations = list(evaluations[:4])
    future_evaluations[2] = future_evaluations[2].model_copy(
        update={"evaluation_available_at": instant(21)}
    )
    negative_controls = {
        "future_market_input_rejected": _rejected(
            lambda: validate_market_state_tensor(future_tensor),
            "AQ-FORECAST-MARKET-TENSOR-LOOKAHEAD",
        ),
        "calibration_test_leakage_rejected": _rejected(
            lambda: CalibrationArtifact.model_validate_json(leaking_calibration.model_dump_json()),
            "AQ-FORECAST-CALIBRATION-TEST-LEAKAGE",
        ),
        "unequal_oos_fold_rejected": _rejected(
            lambda: run_model_arena(
                spec=spec,
                capability_matrix=matrix,
                gate_decisions=allowed_gates[:2],
                evaluations=tuple(unequal_folds),
            ),
            "AQ-FORECAST-ARENA-UNEQUAL-OOS-FOLDS",
        ),
        "capability_lineage_splice_rejected": _rejected(
            lambda: run_model_arena(
                spec=spec,
                capability_matrix=matrix,
                gate_decisions=(allowed_gates[0], forged_gate),
                evaluations=evaluations[:4],
            ),
            "AQ-FORECAST-ARENA-GATE-CAPABILITY-MISMATCH",
        ),
        "self_consistent_gate_boolean_forgery_rejected": _rejected(
            lambda: run_model_arena(
                spec=spec,
                capability_matrix=matrix,
                gate_decisions=(allowed_gates[0], forged_allowed_gate),
                evaluations=blocked_attack_evaluations,
            ),
            "AQ-FORECAST-ARENA-GATE-DECISION-MISMATCH",
        ),
        "future_fold_evaluation_rejected": _rejected(
            lambda: run_model_arena(
                spec=spec,
                capability_matrix=matrix,
                gate_decisions=allowed_gates[:2],
                evaluations=tuple(future_evaluations),
            ),
            "AQ-FORECAST-ARENA-FUTURE-EVALUATION",
        ),
        "forecast_content_copy_attack_rejected": _rejected(
            lambda: ForecastEnvelope.model_validate_json(forged_forecast.model_dump_json()),
            "AQ-FORECAST-ENVELOPE-HASH-MISMATCH",
        ),
    }

    foundation_families = {
        item.family
        for item in matrix.candidates
        if item.model_class is ForecastModelClass.FOUNDATION
    }
    arena_champions = {cell.research_champion_candidate_id for cell in arena.cells}
    failed_candidate = next(
        candidate
        for cell in arena.cells
        for candidate in cell.candidates
        if candidate.candidate_id == "multi-scale-patch-transformer-candidate"
    )
    horizon_payload = forecast.horizons[0].model_dump(mode="json")
    checks = {
        "capability_matrix_has_required_families_classes_and_unique_candidates": (
            len(matrix.candidates) == len({item.candidate_id for item in matrix.candidates}) == 24
            and foundation_families == {"TIMESFM_2_5", "CHRONOS_2", "MOIRAI_2", "TOTO_2_0"}
            and set(ForecastModelClass) <= {item.model_class for item in matrix.candidates}
        ),
        "all_candidates_are_non_production": all(
            item.production_allowed is False for item in matrix.candidates
        ),
        "runnable_candidate_gate_passes_finite_budget": all(
            item.allowed_to_evaluate for item in allowed_gates
        ),
        "blocked_candidate_gate_fails_closed": (
            blocked_gate.allowed_to_evaluate is False
            and capability("chronos-2-candidate").status is CapabilityStatus.ADAPTER_ONLY
            and bool(blocked_gate.block_reasons)
        ),
        "market_tensor_is_pit_rectangular_and_content_addressed": (
            all(available <= tensor.decision_time for available in tensor.available_at)
            and all(len(row) == len(tensor.feature_names) for row in tensor.values)
            and len(tensor.tensor_sha256) == 64
        ),
        "calibration_is_pit_and_test_disjoint": (
            calibration_artifact.available_at <= tensor.decision_time
            and not set(calibration_artifact.calibration_sample_ids)
            & set(calibration_artifact.forbidden_test_sample_ids)
        ),
        "forecast_contains_full_distribution_tail_cost_and_uncertainty": (
            set(ForecastQuantiles.model_fields)
            <= set(horizon_payload["return_distribution"]["quantiles"])
            and {
                "direction_probabilities",
                "realized_volatility_distribution",
                "future_high_low_range",
                "maximum_favorable_excursion",
                "maximum_adverse_excursion",
                "barrier_hit_probabilities",
                "tail_risk_probability",
                "liquidity_forecast",
                "spread_forecast",
                "slippage_forecast",
                "uncertainty",
                "abstain_probability",
            }
            <= set(horizon_payload)
        ),
        "forecast_lineage_binds_tensor_calibration_and_capability": (
            forecast.market_state_tensor_sha256 == tensor.tensor_sha256
            and forecast.dataset_manifest_sha256 == tensor.dataset_manifest_sha256
            and forecast.calibration_artifact_sha256_by_horizon[CouncilHorizon.THIRTY_MINUTES]
            == calibration_artifact.artifact_sha256
            and len(forecast.model_capability_sha256) == 64
        ),
        "model_arena_uses_equal_oos_folds_and_per_cell_selection": (
            arena.fair_comparison
            and all(cell.equal_oos_folds for cell in arena.cells)
            and arena_champions == {"linear-baseline", "tcn-candidate"}
        ),
        "failed_candidates_are_preserved_but_never_selected": (
            failed_candidate.eligible_for_selection is False
            and failed_candidate.exclusion_reasons == ("SIMULATED_OOM",)
            and all(
                cell.research_champion_candidate_id != failed_candidate.candidate_id
                for cell in arena.cells
            )
        ),
        "vision_requires_material_oos_increment": (
            vision_ablation.retain_vision is False
            and vision_ablation.reason_code == "VISION_NO_OOS_INCREMENT"
        ),
        "all_outputs_remain_development_non_trading": (
            forecast.alpha_promotion_eligible is False
            and forecast.order_submission_enabled is False
            and forecast.live_trading_locked is True
            and arena.alpha_promotion_eligible is False
            and arena.zero_shot_is_promotion is False
            and matrix.zero_shot_promotion_allowed is False
        ),
        "negative_controls_fail_closed": all(negative_controls.values()),
    }
    if not all(checks.values()):
        raise RuntimeError(f"V5-P07 evidence checks failed: {checks}")

    return {
        "schema_version": "v5-p07-forecast-council-evidence-v1",
        "phase": "V5-P07",
        "fixture_kind": "DETERMINISTIC_CONTRACT_FIXTURE",
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "real_world_forecast_accuracy_claimed": False,
        "zero_shot_is_promotion": False,
        "external_model_weights_downloaded": False,
        "final_holdout_opened": False,
        "live_trading_locked": True,
        "order_submission_enabled": False,
        "capability_matrix_sha256": capability_matrix_sha256(matrix),
        "capability_matrix": matrix.model_dump(mode="json"),
        "candidate_gates": [
            *(item.model_dump(mode="json") for item in allowed_gates),
            blocked_gate.model_dump(mode="json"),
        ],
        "market_state_tensor": tensor.model_dump(mode="json"),
        "calibration_artifacts": [calibration_artifact.model_dump(mode="json")],
        "forecast_envelopes": [forecast.model_dump(mode="json")],
        "oos_fold_evaluations": [item.model_dump(mode="json") for item in evaluations],
        "model_arena": arena.model_dump(mode="json"),
        "vision_ablations": [vision_ablation.model_dump(mode="json")],
        "negative_controls": negative_controls,
        "checks": checks,
        "acceptance_traceability": {
            "market_state_and_full_forecast_contract": [
                "tests/v5_p07/test_market_state_and_forecasts.py::test_market_state_tensor_is_pit_rectangular_and_content_addressed",
                "tests/v5_p07/test_market_state_and_forecasts.py::test_forecast_binds_tensor_calibration_and_model_capability",
            ],
            "capability_matrix_and_candidate_gates": [
                "tests/v5_p07/test_capability_matrix.py::test_capability_matrix_covers_required_families_classes_horizons_and_regimes",
                "tests/v5_p07/test_capability_matrix.py::test_unverified_license_dependency_and_weight_each_fail_closed",
            ],
            "equal_oos_model_arena_and_lineage": [
                "tests/v5_p07/test_model_arena.py::test_model_arena_uses_equal_folds_and_selects_per_cell_not_universally",
                "tests/v5_p07/test_model_arena.py::test_model_arena_rejects_lineage_splicing_and_prediction_reuse",
            ],
            "zero_shot_and_vision_boundaries": [
                "tests/v5_p07/test_model_arena.py::test_zero_shot_can_win_research_arena_but_never_becomes_promotion",
                "tests/v5_p07/test_model_arena.py::test_vision_without_oos_increment_is_eliminated",
            ],
        },
        "limitations": [
            "All metrics are deterministic contract fixtures; no real public market data is evaluated here.",
            "Catalogued foundation, supervised, microstructure, and vision families are candidates, not installed or production-ready models.",
            "Zero-shot results, research champions, and synthetic OOS metrics do not authorize alpha promotion.",
            "P08, not P07, owns event-conditioned forecast increment and event-vs-market ablation.",
            "Final holdout, forward paper/shadow/testnet gates, order submission, and live trading remain closed.",
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
            raise SystemExit(f"V5-P07 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P07 Forecast Council evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P07 Forecast Council evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
