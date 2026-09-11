"""Fail-closed candidate gating and equal-fold Forecast Council arena."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import AssetId
from aegisquant.domain.values import canonical_result
from aegisquant.research.budgets import ResourceBudget, ResourceRequest, evaluate_budget
from aegisquant.research.forecasting.contracts import (
    ArenaCandidateSummary,
    ArenaCellResult,
    CandidateGateDecision,
    CapabilityMatrix,
    CapabilityStatus,
    CouncilHorizon,
    FoldEvaluationState,
    ForecastMetrics,
    ForecastModality,
    ForecastModelClass,
    LicenseStatus,
    MarketRegime,
    ModelArenaReport,
    ModelArenaSpec,
    ModelCapability,
    OosFoldEvaluation,
    PredictionMode,
    VisionAblationReport,
    capability_matrix_sha256,
    capability_sha256,
)


def evaluate_candidate_gate(
    *,
    capability: ModelCapability,
    budget: ResourceBudget,
    request: ResourceRequest,
    dependency_available: bool,
    weights_verified: bool,
) -> CandidateGateDecision:
    """Allow research evaluation only when capability, license, budget and artifacts pass."""

    candidate = ModelCapability.model_validate_json(capability.model_dump_json())
    approved_budget = ResourceBudget.model_validate_json(budget.model_dump_json())
    requested_budget = ResourceRequest.model_validate_json(request.model_dump_json())
    block_reasons: set[str] = set()
    restrictions: set[str] = set()
    if candidate.status is not CapabilityStatus.RUNNABLE_LOCAL:
        block_reasons.add(f"AQ-FORECAST-CAPABILITY-{candidate.status.value}")
    if candidate.license_status in {LicenseStatus.UNVERIFIED, LicenseStatus.PROHIBITED}:
        block_reasons.add("AQ-FORECAST-LICENSE-NOT-APPROVED")
    if not dependency_available:
        block_reasons.add("AQ-FORECAST-DEPENDENCY-UNAVAILABLE")
    if candidate.weights_required and not weights_verified:
        block_reasons.add("AQ-FORECAST-WEIGHTS-NOT-VERIFIED")
    budget_decision = evaluate_budget(budget=approved_budget, request=requested_budget)
    block_reasons.update(budget_decision.reason_codes)
    if PredictionMode.ZERO_SHOT in candidate.prediction_modes:
        restrictions.add("AQ-FORECAST-ZERO-SHOT-NO-PROMOTION")
    if candidate.license_status is LicenseStatus.RESEARCH_ONLY:
        restrictions.add("AQ-FORECAST-RESEARCH-ONLY-LICENSE")
    return CandidateGateDecision(
        candidate_id=candidate.candidate_id,
        capability_sha256=capability_sha256(candidate),
        budget_sha256=canonical_sha256(approved_budget.model_dump(mode="json")),
        request_sha256=canonical_sha256(requested_budget.model_dump(mode="json")),
        budget=approved_budget,
        request=requested_budget,
        dependency_available=dependency_available,
        weights_verified=weights_verified,
        allowed_to_evaluate=not block_reasons,
        block_reasons=tuple(sorted(block_reasons)),
        restriction_codes=tuple(sorted(restrictions)),
        alpha_promotion_eligible=False,
    )


def evaluate_vision_ablation(
    *,
    asset_id: AssetId,
    horizon: CouncilHorizon,
    regime: MarketRegime,
    numeric_only_loss: Decimal,
    vision_only_loss: Decimal,
    numeric_vision_loss: Decimal,
    minimum_absolute_improvement: Decimal,
) -> VisionAblationReport:
    """Retain optional vision only when held-out loss improves by the frozen floor."""

    best_vision = min(vision_only_loss, numeric_vision_loss)
    retain = numeric_only_loss - best_vision >= minimum_absolute_improvement
    selected = ForecastModality.NUMERIC_ONLY
    if retain:
        selected = (
            ForecastModality.VISION_ONLY
            if vision_only_loss <= numeric_vision_loss
            else ForecastModality.NUMERIC_VISION
        )
    return VisionAblationReport(
        asset_id=asset_id,
        horizon=horizon,
        regime=regime,
        numeric_only_loss=numeric_only_loss,
        vision_only_loss=vision_only_loss,
        numeric_vision_loss=numeric_vision_loss,
        minimum_absolute_improvement=minimum_absolute_improvement,
        retain_vision=retain,
        selected_modality=selected,
        reason_code=("VISION_OOS_INCREMENT_PASSED" if retain else "VISION_NO_OOS_INCREMENT"),
        alpha_promotion_eligible=False,
    )


def _fold_signature(fold: OosFoldEvaluation) -> tuple[object, ...]:
    return (
        fold.fold_id,
        fold.split_sha256,
        fold.dataset_manifest_sha256,
        fold.calibration_artifact_sha256,
        fold.training_end,
        fold.calibration_end,
        fold.test_start,
        fold.test_end,
        fold.training_sample_ids,
        fold.calibration_sample_ids,
        fold.test_sample_ids,
    )


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return canonical_result(sum(values, Decimal("0")) / Decimal(len(values)))


def _mean_metrics(folds: tuple[OosFoldEvaluation, ...]) -> ForecastMetrics:
    metrics = tuple(fold.metrics for fold in folds)
    if any(item is None for item in metrics):
        raise ValueError("cannot aggregate a non-evaluated forecast fold")
    concrete = tuple(item for item in metrics if item is not None)
    return ForecastMetrics(
        primary_loss=_mean(tuple(item.primary_loss for item in concrete)),
        direction_accuracy=_mean(tuple(item.direction_accuracy for item in concrete)),
        mean_absolute_error=_mean(tuple(item.mean_absolute_error for item in concrete)),
        root_mean_squared_error=_mean(tuple(item.root_mean_squared_error for item in concrete)),
        crps=_mean(tuple(item.crps for item in concrete)),
        pinball_loss=_mean(tuple(item.pinball_loss for item in concrete)),
        brier_score=_mean(tuple(item.brier_score for item in concrete)),
        interval_coverage=_mean(tuple(item.interval_coverage for item in concrete)),
        tail_recall=_mean(tuple(item.tail_recall for item in concrete)),
        net_return_after_cost=_mean(tuple(item.net_return_after_cost for item in concrete)),
    )


def run_model_arena(
    *,
    spec: ModelArenaSpec,
    capability_matrix: CapabilityMatrix,
    gate_decisions: tuple[CandidateGateDecision, ...],
    evaluations: tuple[OosFoldEvaluation, ...],
    vision_ablations: tuple[VisionAblationReport, ...] = (),
) -> ModelArenaReport:
    """Select one research champion per asset/horizon/regime on identical OOS folds."""

    arena_spec = ModelArenaSpec.model_validate_json(spec.model_dump_json())
    matrix = CapabilityMatrix.model_validate_json(capability_matrix.model_dump_json())
    decisions = tuple(
        CandidateGateDecision.model_validate_json(item.model_dump_json()) for item in gate_decisions
    )
    folds = tuple(
        OosFoldEvaluation.model_validate_json(item.model_dump_json()) for item in evaluations
    )
    prediction_artifact_hashes = tuple(item.prediction_artifact_sha256 for item in folds)
    if len(set(prediction_artifact_hashes)) != len(prediction_artifact_hashes):
        raise ValueError("AQ-FORECAST-ARENA-PREDICTION-ARTIFACT-REUSED")
    ablations = tuple(
        VisionAblationReport.model_validate_json(item.model_dump_json())
        for item in vision_ablations
    )
    if not folds:
        raise ValueError("model arena requires OOS fold evaluations")
    capability_by_id = {item.candidate_id: item for item in matrix.candidates}
    decision_by_id = {item.candidate_id: item for item in decisions}
    if len(decision_by_id) != len(decisions):
        raise ValueError("model arena candidate gate decisions must be unique")
    ablation_by_cell = {(item.asset_id, item.horizon, item.regime): item for item in ablations}
    if len(ablation_by_cell) != len(ablations):
        raise ValueError("model arena vision ablations must be unique per cell")

    by_cell: dict[tuple[AssetId, CouncilHorizon, MarketRegime], list[OosFoldEvaluation]] = (
        defaultdict(list)
    )
    for fold in folds:
        try:
            capability = capability_by_id[fold.candidate_id]
            decision = decision_by_id[fold.candidate_id]
        except KeyError as error:
            raise ValueError("model arena evaluation lacks capability or gate decision") from error
        if not decision.allowed_to_evaluate:
            raise ValueError("model arena cannot evaluate a gate-blocked candidate")
        if decision.capability_sha256 != capability_sha256(capability):
            raise ValueError("AQ-FORECAST-ARENA-GATE-CAPABILITY-MISMATCH")
        expected_decision = evaluate_candidate_gate(
            capability=capability,
            budget=decision.budget,
            request=decision.request,
            dependency_available=decision.dependency_available,
            weights_verified=decision.weights_verified,
        )
        if decision != expected_decision:
            raise ValueError("AQ-FORECAST-ARENA-GATE-DECISION-MISMATCH")
        if fold.model_capability_sha256 != capability_sha256(capability):
            raise ValueError("AQ-FORECAST-ARENA-FOLD-CAPABILITY-MISMATCH")
        if fold.evaluation_available_at > arena_spec.evaluation_cutoff:
            raise ValueError("AQ-FORECAST-ARENA-FUTURE-EVALUATION")
        if (
            fold.horizon not in capability.supported_horizons
            or fold.regime not in capability.supported_regimes
            or fold.prediction_mode not in capability.prediction_modes
        ):
            raise ValueError("model arena evaluation exceeds candidate capability")
        by_cell[(fold.asset_id, fold.horizon, fold.regime)].append(fold)

    cell_results: list[ArenaCellResult] = []
    for cell_key in sorted(by_cell, key=lambda item: tuple(str(value) for value in item)):
        cell_folds = by_cell[cell_key]
        by_candidate: dict[str, list[OosFoldEvaluation]] = defaultdict(list)
        for fold in cell_folds:
            by_candidate[fold.candidate_id].append(fold)
        if arena_spec.baseline_candidate_id not in by_candidate or len(by_candidate) < 2:
            raise ValueError("model arena cell requires baseline and at least one challenger")
        baseline_folds = tuple(
            sorted(by_candidate[arena_spec.baseline_candidate_id], key=lambda item: item.fold_id)
        )
        if len(baseline_folds) != arena_spec.expected_fold_count or len(
            {item.fold_id for item in baseline_folds}
        ) != len(baseline_folds):
            raise ValueError("model arena baseline fold count is invalid")
        baseline_signature = tuple(_fold_signature(item) for item in baseline_folds)
        summaries: list[ArenaCandidateSummary] = []
        for candidate_id in sorted(by_candidate):
            candidate_folds = tuple(
                sorted(by_candidate[candidate_id], key=lambda item: item.fold_id)
            )
            if len(candidate_folds) != arena_spec.expected_fold_count or len(
                {item.fold_id for item in candidate_folds}
            ) != len(candidate_folds):
                raise ValueError("model arena candidate fold count is invalid")
            if tuple(_fold_signature(item) for item in candidate_folds) != baseline_signature:
                raise ValueError("AQ-FORECAST-ARENA-UNEQUAL-OOS-FOLDS")
            modes = {item.prediction_mode for item in candidate_folds}
            if len(modes) != 1:
                raise ValueError("model arena candidate prediction modes differ across folds")
            capability = capability_by_id[candidate_id]
            exclusion_reasons: set[str] = set()
            if any(item.state is not FoldEvaluationState.EVALUATED for item in candidate_folds):
                exclusion_reasons.update(
                    item.abstain_or_failure_reason or "AQ-FORECAST-FOLD-NOT-EVALUATED"
                    for item in candidate_folds
                    if item.state is not FoldEvaluationState.EVALUATED
                )
            if capability.model_class is ForecastModelClass.VISION:
                ablation = ablation_by_cell.get(cell_key)
                if ablation is None or not ablation.retain_vision:
                    exclusion_reasons.add("AQ-FORECAST-VISION-NO-OOS-INCREMENT")
            aggregate = None if exclusion_reasons else _mean_metrics(candidate_folds)
            summaries.append(
                ArenaCandidateSummary(
                    candidate_id=candidate_id,
                    model_class=capability.model_class,
                    prediction_mode=next(iter(modes)),
                    fold_ids=tuple(item.fold_id for item in candidate_folds),
                    mean_primary_loss=None if aggregate is None else aggregate.primary_loss,
                    mean_direction_accuracy=(
                        None if aggregate is None else aggregate.direction_accuracy
                    ),
                    mean_crps=None if aggregate is None else aggregate.crps,
                    mean_brier_score=None if aggregate is None else aggregate.brier_score,
                    mean_interval_coverage=(
                        None if aggregate is None else aggregate.interval_coverage
                    ),
                    mean_tail_recall=None if aggregate is None else aggregate.tail_recall,
                    mean_net_return_after_cost=(
                        None if aggregate is None else aggregate.net_return_after_cost
                    ),
                    eligible_for_selection=not exclusion_reasons,
                    exclusion_reasons=tuple(sorted(exclusion_reasons)),
                    alpha_promotion_eligible=False,
                )
            )
        summary_by_id = {item.candidate_id: item for item in summaries}
        baseline = summary_by_id[arena_spec.baseline_candidate_id]
        if not baseline.eligible_for_selection or baseline.mean_primary_loss is None:
            raise ValueError("model arena baseline must be fully evaluated")
        eligible = tuple(item for item in summaries if item.eligible_for_selection)
        best = min(
            eligible,
            key=lambda item: (
                item.mean_primary_loss
                if item.mean_primary_loss is not None
                else Decimal("Infinity"),
                item.candidate_id,
            ),
        )
        if (
            best.candidate_id != baseline.candidate_id
            and best.mean_primary_loss is not None
            and baseline.mean_primary_loss - best.mean_primary_loss
            < arena_spec.minimum_absolute_improvement
        ):
            best = baseline
        asset_id, horizon, regime = cell_key
        cell_results.append(
            ArenaCellResult(
                asset_id=asset_id,
                horizon=horizon,
                regime=regime,
                baseline_candidate_id=baseline.candidate_id,
                research_champion_candidate_id=best.candidate_id,
                candidates=tuple(summaries),
                equal_oos_folds=True,
                selection_scope="asset_x_horizon_x_regime",
                alpha_promotion_eligible=False,
            )
        )
    return ModelArenaReport(
        capability_matrix_sha256=capability_matrix_sha256(matrix),
        spec=arena_spec,
        cells=tuple(cell_results),
        fair_comparison=True,
        no_single_universal_model_assumption=True,
        zero_shot_is_promotion=False,
        failures_preserved=True,
        alpha_promotion_eligible=False,
        order_submission_enabled=False,
        live_trading_locked=True,
    )
