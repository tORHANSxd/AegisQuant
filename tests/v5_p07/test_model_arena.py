"""Equal-fold model arena, per-cell champion, failure, and vision tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.research.forecasting import (
    ArenaCellResult,
    CapabilityMatrix,
    CapabilityStatus,
    CouncilHorizon,
    FoldEvaluationState,
    LicenseStatus,
    MarketRegime,
    ModelArenaReport,
    ModelArenaSpec,
    ModelCapability,
    OosFoldEvaluation,
    PredictionMode,
    default_capability_matrix,
    evaluate_candidate_gate,
    evaluate_vision_ablation,
    run_model_arena,
)
from tests.v5_p07.helpers import budget, capability, fold, gate, instant, request


def arena_spec() -> ModelArenaSpec:
    return ModelArenaSpec(
        baseline_candidate_id="linear-baseline",
        expected_fold_count=2,
        minimum_absolute_improvement=Decimal("0.01"),
        evaluation_cutoff=instant(20),
    )


def two_cell_evaluations() -> tuple[OosFoldEvaluation, ...]:
    return (
        fold(candidate_id="linear-baseline", fold_number=1, loss="0.10"),
        fold(candidate_id="linear-baseline", fold_number=2, loss="0.10"),
        fold(candidate_id="tcn-candidate", fold_number=1, loss="0.07"),
        fold(candidate_id="tcn-candidate", fold_number=2, loss="0.08"),
        fold(
            candidate_id="linear-baseline",
            fold_number=1,
            loss="0.10",
            asset="ETH",
            horizon=CouncilHorizon.FOUR_HOURS,
            regime=MarketRegime.VOL_EXPANSION,
        ),
        fold(
            candidate_id="linear-baseline",
            fold_number=2,
            loss="0.10",
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


def test_model_arena_uses_equal_folds_and_selects_per_cell_not_universally() -> None:
    report = run_model_arena(
        spec=arena_spec(),
        capability_matrix=default_capability_matrix(as_of_time=instant(20)),
        gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
        evaluations=two_cell_evaluations(),
    )
    champions = {
        (str(cell.asset_id), cell.horizon, cell.regime): cell.research_champion_candidate_id
        for cell in report.cells
    }
    assert champions[("BTC", CouncilHorizon.THIRTY_MINUTES, MarketRegime.TREND)] == "tcn-candidate"
    assert (
        champions[("ETH", CouncilHorizon.FOUR_HOURS, MarketRegime.VOL_EXPANSION)]
        == "linear-baseline"
    )
    assert all(cell.equal_oos_folds for cell in report.cells)
    assert report.no_single_universal_model_assumption is True
    assert report.alpha_promotion_eligible is False


def test_model_arena_rejects_different_test_samples_or_split_hash() -> None:
    evaluations = list(two_cell_evaluations()[:4])
    evaluations[2] = evaluations[2].model_copy(
        update={"test_sample_ids": ("foreign-test-1", "foreign-test-2")}
    )
    with pytest.raises(ValueError, match="UNEQUAL-OOS-FOLDS"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=default_capability_matrix(as_of_time=instant(20)),
            gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
            evaluations=tuple(evaluations),
        )
    evaluations = list(two_cell_evaluations()[:4])
    evaluations[2] = evaluations[2].model_copy(update={"split_sha256": "f" * 64})
    with pytest.raises(ValueError, match="UNEQUAL-OOS-FOLDS"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=default_capability_matrix(as_of_time=instant(20)),
            gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
            evaluations=tuple(evaluations),
        )


def test_model_arena_rejects_lineage_splicing_and_prediction_reuse() -> None:
    evaluations = two_cell_evaluations()[:4]
    forged_gate = gate("tcn-candidate").model_copy(update={"capability_sha256": "f" * 64})
    with pytest.raises(ValueError, match="GATE-CAPABILITY-MISMATCH"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=default_capability_matrix(as_of_time=instant(20)),
            gate_decisions=(gate("linear-baseline"), forged_gate),
            evaluations=evaluations,
        )

    forged_fold = evaluations[2].model_copy(update={"model_capability_sha256": "f" * 64})
    with pytest.raises(ValueError, match="FOLD-CAPABILITY-MISMATCH"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=default_capability_matrix(as_of_time=instant(20)),
            gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
            evaluations=(*evaluations[:2], forged_fold, evaluations[3]),
        )

    reused_prediction = evaluations[2].model_copy(
        update={"prediction_artifact_sha256": evaluations[0].prediction_artifact_sha256}
    )
    with pytest.raises(ValueError, match="PREDICTION-ARTIFACT-REUSED"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=default_capability_matrix(as_of_time=instant(20)),
            gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
            evaluations=(*evaluations[:2], reused_prediction, evaluations[3]),
        )


def test_model_arena_recomputes_gate_and_rejects_future_evaluation() -> None:
    matrix = default_capability_matrix(as_of_time=instant(20))
    blocked = evaluate_candidate_gate(
        capability=capability("chronos-2-candidate"),
        budget=budget(),
        request=request(),
        dependency_available=True,
        weights_verified=True,
    )
    forged_allowed = blocked.model_copy(update={"allowed_to_evaluate": True, "block_reasons": ()})
    with pytest.raises(ValueError, match="GATE-DECISION-MISMATCH"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=matrix,
            gate_decisions=(gate("linear-baseline"), forged_allowed),
            evaluations=(
                fold(candidate_id="linear-baseline", fold_number=1, loss="0.10"),
                fold(candidate_id="linear-baseline", fold_number=2, loss="0.10"),
                fold(candidate_id="chronos-2-candidate", fold_number=1, loss="0.05"),
                fold(candidate_id="chronos-2-candidate", fold_number=2, loss="0.05"),
            ),
        )

    evaluations = list(two_cell_evaluations()[:4])
    evaluations[2] = evaluations[2].model_copy(update={"evaluation_available_at": instant(21)})
    with pytest.raises(ValueError, match="FUTURE-EVALUATION"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=matrix,
            gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
            evaluations=tuple(evaluations),
        )


def test_model_arena_rejects_missing_fold_and_gate_blocked_evaluation() -> None:
    with pytest.raises(ValueError, match="fold count"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=default_capability_matrix(as_of_time=instant(20)),
            gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
            evaluations=two_cell_evaluations()[:3],
        )
    blocked = evaluate_candidate_gate(
        capability=capability("chronos-2-candidate"),
        budget=budget(),
        request=request(),
        dependency_available=True,
        weights_verified=True,
    )
    with pytest.raises(ValueError, match="gate-blocked"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=default_capability_matrix(as_of_time=instant(20)),
            gate_decisions=(gate("linear-baseline"), blocked),
            evaluations=(
                fold(candidate_id="linear-baseline", fold_number=1, loss="0.10"),
                fold(candidate_id="linear-baseline", fold_number=2, loss="0.10"),
                fold(
                    candidate_id="chronos-2-candidate",
                    fold_number=1,
                    loss="0.05",
                    mode=PredictionMode.ZERO_SHOT,
                ),
                fold(
                    candidate_id="chronos-2-candidate",
                    fold_number=2,
                    loss="0.05",
                    mode=PredictionMode.ZERO_SHOT,
                ),
            ),
        )


def test_failed_candidate_is_preserved_but_never_selected() -> None:
    failed_id = "multi-scale-patch-transformer-candidate"
    evaluations = (
        *two_cell_evaluations()[:4],
        fold(
            candidate_id=failed_id,
            fold_number=1,
            loss="0",
            state=FoldEvaluationState.FAILED,
            failure_reason="SIMULATED_OOM",
        ),
        fold(
            candidate_id=failed_id,
            fold_number=2,
            loss="0",
            state=FoldEvaluationState.FAILED,
            failure_reason="SIMULATED_OOM",
        ),
    )
    report = run_model_arena(
        spec=arena_spec(),
        capability_matrix=default_capability_matrix(as_of_time=instant(20)),
        gate_decisions=(gate("linear-baseline"), gate("tcn-candidate"), gate(failed_id)),
        evaluations=evaluations,
    )
    failed = next(item for item in report.cells[0].candidates if item.candidate_id == failed_id)
    assert failed.eligible_for_selection is False
    assert failed.exclusion_reasons == ("SIMULATED_OOM",)
    assert report.failures_preserved is True


def _matrix_with_runnable(candidate_id: str) -> tuple[CapabilityMatrix, ModelCapability]:
    matrix = default_capability_matrix(as_of_time=instant(20))
    original = next(item for item in matrix.candidates if item.candidate_id == candidate_id)
    runnable = ModelCapability.model_validate(
        {
            **original.model_dump(mode="python"),
            "status": CapabilityStatus.RUNNABLE_LOCAL,
            "license_status": LicenseStatus.VERIFIED_PERMISSIVE,
            "code_license": "TEST_FIXTURE_APPROVED",
            "weights_license": "TEST_FIXTURE_APPROVED",
        }
    )
    candidates = tuple(
        runnable if item.candidate_id == candidate_id else item for item in matrix.candidates
    )
    return CapabilityMatrix(as_of_time=matrix.as_of_time, candidates=candidates), runnable


def test_zero_shot_can_win_research_arena_but_never_becomes_promotion() -> None:
    matrix, chronos = _matrix_with_runnable("chronos-2-candidate")
    decision = evaluate_candidate_gate(
        capability=chronos,
        budget=budget(),
        request=request(),
        dependency_available=True,
        weights_verified=True,
    )
    report = run_model_arena(
        spec=arena_spec(),
        capability_matrix=matrix,
        gate_decisions=(gate("linear-baseline"), decision),
        evaluations=(
            fold(candidate_id="linear-baseline", fold_number=1, loss="0.10"),
            fold(candidate_id="linear-baseline", fold_number=2, loss="0.10"),
            fold(
                candidate_id="chronos-2-candidate",
                fold_number=1,
                loss="0.05",
                mode=PredictionMode.ZERO_SHOT,
                model_capability=chronos,
            ),
            fold(
                candidate_id="chronos-2-candidate",
                fold_number=2,
                loss="0.05",
                mode=PredictionMode.ZERO_SHOT,
                model_capability=chronos,
            ),
        ),
    )
    assert report.cells[0].research_champion_candidate_id == "chronos-2-candidate"
    assert report.zero_shot_is_promotion is False
    assert all(not item.alpha_promotion_eligible for item in report.cells[0].candidates)


def test_vision_without_oos_increment_is_eliminated() -> None:
    matrix, vision = _matrix_with_runnable("vit-vision-candidate")
    vision_gate = evaluate_candidate_gate(
        capability=vision,
        budget=budget(),
        request=request(),
        dependency_available=True,
        weights_verified=True,
    )
    ablation = evaluate_vision_ablation(
        asset_id=fold(candidate_id="linear-baseline", fold_number=1, loss="0.10").asset_id,
        horizon=CouncilHorizon.THIRTY_MINUTES,
        regime=MarketRegime.TREND,
        numeric_only_loss=Decimal("0.10"),
        vision_only_loss=Decimal("0.13"),
        numeric_vision_loss=Decimal("0.095"),
        minimum_absolute_improvement=Decimal("0.01"),
    )
    report = run_model_arena(
        spec=arena_spec(),
        capability_matrix=matrix,
        gate_decisions=(gate("linear-baseline"), vision_gate),
        evaluations=(
            fold(candidate_id="linear-baseline", fold_number=1, loss="0.10"),
            fold(candidate_id="linear-baseline", fold_number=2, loss="0.10"),
            fold(
                candidate_id="vit-vision-candidate",
                fold_number=1,
                loss="0.095",
                model_capability=vision,
            ),
            fold(
                candidate_id="vit-vision-candidate",
                fold_number=2,
                loss="0.095",
                model_capability=vision,
            ),
        ),
        vision_ablations=(ablation,),
    )
    vision_summary = next(
        item for item in report.cells[0].candidates if item.candidate_id == vision.candidate_id
    )
    assert ablation.retain_vision is False
    assert vision_summary.eligible_for_selection is False
    assert report.cells[0].research_champion_candidate_id == "linear-baseline"


def test_vision_is_retained_only_after_material_oos_increment() -> None:
    report = evaluate_vision_ablation(
        asset_id=fold(candidate_id="linear-baseline", fold_number=1, loss="0.10").asset_id,
        horizon=CouncilHorizon.THIRTY_MINUTES,
        regime=MarketRegime.TREND,
        numeric_only_loss=Decimal("0.10"),
        vision_only_loss=Decimal("0.11"),
        numeric_vision_loss=Decimal("0.07"),
        minimum_absolute_improvement=Decimal("0.01"),
    )
    assert report.retain_vision is True
    assert report.selected_modality.value == "NUMERIC_VISION"


def test_oos_fold_rejects_time_and_sample_leakage() -> None:
    valid = fold(candidate_id="linear-baseline", fold_number=1, loss="0.10")
    time_attack = valid.model_copy(update={"test_start": valid.calibration_end})
    with pytest.raises(ValidationError, match="OOS-TIME-LEAKAGE"):
        OosFoldEvaluation.model_validate_json(time_attack.model_dump_json())
    sample_attack = valid.model_copy(
        update={"test_sample_ids": (valid.training_sample_ids[0], "other")}
    )
    with pytest.raises(ValidationError, match="OOS-SAMPLE-LEAKAGE"):
        OosFoldEvaluation.model_validate_json(sample_attack.model_dump_json())


def test_model_arena_rejects_unsupported_horizon_and_prediction_mode() -> None:
    evaluations = (
        fold(
            candidate_id="linear-baseline",
            fold_number=1,
            loss="0.10",
            horizon=CouncilHorizon.FIVE_SECONDS,
        ),
        fold(
            candidate_id="linear-baseline",
            fold_number=2,
            loss="0.10",
            horizon=CouncilHorizon.FIVE_SECONDS,
        ),
        fold(
            candidate_id="tcn-candidate",
            fold_number=1,
            loss="0.05",
            horizon=CouncilHorizon.FIVE_SECONDS,
        ),
        fold(
            candidate_id="tcn-candidate",
            fold_number=2,
            loss="0.05",
            horizon=CouncilHorizon.FIVE_SECONDS,
        ),
    )
    with pytest.raises(ValueError, match="exceeds candidate capability"):
        run_model_arena(
            spec=arena_spec(),
            capability_matrix=default_capability_matrix(as_of_time=instant(20)),
            gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
            evaluations=evaluations,
        )


def test_arena_report_revalidation_rejects_missing_champion_and_duplicate_cell() -> None:
    report = run_model_arena(
        spec=arena_spec(),
        capability_matrix=default_capability_matrix(as_of_time=instant(20)),
        gate_decisions=(gate("linear-baseline"), gate("tcn-candidate")),
        evaluations=two_cell_evaluations(),
    )
    cell = report.cells[0]
    champion_attack = cell.model_copy(update={"research_champion_candidate_id": "missing"})
    with pytest.raises(ValidationError, match="champion"):
        ArenaCellResult.model_validate_json(champion_attack.model_dump_json())
    duplicate_attack = report.model_copy(update={"cells": (cell, cell)})
    with pytest.raises(ValidationError, match="cells must be unique"):
        ModelArenaReport.model_validate_json(duplicate_attack.model_dump_json())
