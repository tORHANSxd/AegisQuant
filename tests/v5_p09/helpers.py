"""Deterministic V5-P09 contract fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import AssetId
from aegisquant.domain.truth import TruthState
from aegisquant.research.forecasting import (
    AdaptiveConformalPolicy,
    AdaptiveConformalReport,
    CalibrationMethod,
    CouncilDisagreementPolicy,
    CouncilDisagreementReport,
    CouncilHorizon,
    CouncilMemberSignal,
    CouncilSignalSnapshot,
    DynamicStackingPolicy,
    ForecastGovernanceReport,
    IndependentSkepticAssessment,
    IntervalCoverageObservation,
    IntervalCoverageWindow,
    MarketRegime,
    MetaReasonerRecommendation,
    ReasoningContext,
    ReasoningInputKind,
    RegimeRoutingDecision,
    RegimeRoutingSnapshot,
    SkepticFinding,
    SkepticSeverity,
    StatisticalWeightProposal,
    WeightEvidenceSource,
    build_forecast_governance_report,
    create_council_signal_snapshot,
    create_independent_skeptic_assessment,
    create_interval_coverage_window,
    create_meta_reasoner_recommendation,
    create_reasoning_context,
    create_regime_routing_snapshot,
    create_statistical_weight_proposal,
    evaluate_adaptive_conformal,
    evaluate_council_disagreement,
    route_dynamic_stacking,
)
from aegisquant.research.models.ensemble import StackingWeights

NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
ASSET = AssetId("BTC")
MODEL_IDS = ("baseline", "supervised")


def digest(label: str) -> str:
    return canonical_sha256({"fixture": label})


def signal_snapshot(
    *,
    returns: tuple[Decimal, Decimal] = (Decimal("0.010"), Decimal("0.012")),
    regime: MarketRegime = MarketRegime.TREND,
) -> CouncilSignalSnapshot:
    return create_council_signal_snapshot(
        asset_id=ASSET,
        horizon=CouncilHorizon.FIVE_MINUTES,
        regime=regime,
        decision_time=NOW,
        signals=tuple(
            CouncilMemberSignal(
                candidate_id=model_id,
                forecast_sha256=digest(f"forecast-{model_id}-{regime.value}"),
                expected_return=value,
                available_at=NOW - timedelta(seconds=20),
            )
            for model_id, value in zip(MODEL_IDS, returns, strict=True)
        ),
    )


def disagreement_report(
    *,
    snapshot: CouncilSignalSnapshot | None = None,
    maximum_range: Decimal = Decimal("0.02"),
) -> CouncilDisagreementReport:
    return evaluate_council_disagreement(
        snapshot=snapshot or signal_snapshot(),
        policy=CouncilDisagreementPolicy(maximum_expected_return_range=maximum_range),
    )


def stacking_policy(
    *,
    maximum_single_model_weight: Decimal = Decimal("0.70"),
    maximum_weight_step: Decimal = Decimal("0.05"),
) -> DynamicStackingPolicy:
    return DynamicStackingPolicy(
        maximum_single_model_weight=maximum_single_model_weight,
        maximum_weight_step=maximum_weight_step,
        maximum_ood_score=Decimal("1"),
        minimum_data_quality=Decimal("0.70"),
        minimum_model_reliability=Decimal("0.60"),
    )


def weight_proposal(
    *,
    regime: MarketRegime = MarketRegime.TREND,
    available_at: datetime = NOW - timedelta(seconds=30),
    evidence: dict[WeightEvidenceSource, str] | None = None,
) -> StatisticalWeightProposal:
    return create_statistical_weight_proposal(
        asset_id=ASSET,
        horizon=CouncilHorizon.FIVE_MINUTES,
        regime=regime,
        training_cutoff=NOW - timedelta(days=1),
        available_at=available_at,
        previous_weights=StackingWeights(
            weights={"baseline": Decimal("0.50"), "supervised": Decimal("0.50")},
            maximum_weight=Decimal("0.70"),
        ),
        proposed_weights=StackingWeights(
            weights={"baseline": Decimal("0.40"), "supervised": Decimal("0.60")},
            maximum_weight=Decimal("0.70"),
        ),
        evidence_sha256_by_source=(
            evidence
            if evidence is not None
            else {
                WeightEvidenceSource.VALIDATION: digest("validation"),
                WeightEvidenceSource.CALIBRATION: digest("calibration"),
            }
        ),
        split_sha256=digest("stacking-split"),
    )


def routing_snapshot(
    *,
    regime: MarketRegime = MarketRegime.TREND,
    ood_score: Decimal = Decimal("0.1"),
    data_quality: Decimal = Decimal("0.95"),
    truth_state: TruthState = TruthState.VERIFIED_MULTI_SOURCE,
    available_at: datetime = NOW - timedelta(seconds=15),
    reliability: dict[str, Decimal] | None = None,
) -> RegimeRoutingSnapshot:
    return create_regime_routing_snapshot(
        asset_id=ASSET,
        horizon=CouncilHorizon.FIVE_MINUTES,
        regime=regime,
        observed_at=NOW - timedelta(seconds=20),
        available_at=available_at,
        decision_time=NOW,
        data_quality=data_quality,
        truth_state=truth_state,
        ood_score=ood_score,
        model_reliability_by_id=reliability
        or {"baseline": Decimal("0.90"), "supervised": Decimal("0.85")},
    )


def route_decision(
    *,
    snapshot: RegimeRoutingSnapshot | None = None,
    proposal: StatisticalWeightProposal | None = None,
) -> RegimeRoutingDecision:
    return route_dynamic_stacking(
        snapshot=snapshot or routing_snapshot(),
        proposal=proposal or weight_proposal(),
        policy=stacking_policy(),
    )


def coverage_observations(
    *,
    realized: tuple[Decimal, ...] = (
        Decimal("0"),
        Decimal("0.05"),
        Decimal("-0.05"),
        Decimal("0.09"),
        Decimal("0.20"),
    ),
) -> tuple[IntervalCoverageObservation, ...]:
    return tuple(
        IntervalCoverageObservation(
            sample_id=f"coverage-{index}",
            predicted_lower=Decimal("-0.10"),
            predicted_median=Decimal("0"),
            predicted_upper=Decimal("0.10"),
            realized_value=value,
            predicted_at=NOW - timedelta(minutes=10 - index),
            outcome_available_at=NOW - timedelta(minutes=9 - index),
        )
        for index, value in enumerate(realized)
    )


def coverage_window(
    *,
    observations: tuple[IntervalCoverageObservation, ...] | None = None,
    decision_time: datetime = NOW,
    regime: MarketRegime = MarketRegime.TREND,
) -> IntervalCoverageWindow:
    return create_interval_coverage_window(
        asset_id=ASSET,
        horizon=CouncilHorizon.FIVE_MINUTES,
        regime=regime,
        model_revision_sha256=digest("ensemble-model"),
        dataset_manifest_sha256=digest("coverage-dataset"),
        calibration_artifact_sha256=digest("base-calibration"),
        window_start=NOW - timedelta(minutes=12),
        window_end=NOW - timedelta(minutes=1),
        decision_time=decision_time,
        observations=observations or coverage_observations(),
    )


def conformal_policy(
    *,
    minimum_sample_count: int = 5,
    maximum_window_age_seconds: Decimal = Decimal("120"),
) -> AdaptiveConformalPolicy:
    return AdaptiveConformalPolicy(
        method=CalibrationMethod.DISTRIBUTION_AWARE_CONFORMAL,
        target_coverage=Decimal("0.80"),
        warning_shortfall=Decimal("0.10"),
        critical_shortfall=Decimal("0.20"),
        minimum_sample_count=minimum_sample_count,
        maximum_window_age_seconds=maximum_window_age_seconds,
        maximum_adjustment_step=Decimal("0.05"),
    )


def conformal_report(
    *,
    window: IntervalCoverageWindow | None = None,
    policy: AdaptiveConformalPolicy | None = None,
) -> AdaptiveConformalReport:
    return evaluate_adaptive_conformal(
        window=window or coverage_window(),
        policy=policy or conformal_policy(),
    )


def reasoning_context(
    *,
    disagreement: CouncilDisagreementReport | None = None,
    route: RegimeRoutingDecision | None = None,
    calibration: AdaptiveConformalReport | None = None,
    meta_reasoner_prompt_sha256: str | None = None,
    meta_reasoner_model_revision_sha256: str | None = None,
    skeptic_prompt_sha256: str | None = None,
    skeptic_model_revision_sha256: str | None = None,
) -> ReasoningContext:
    disagreement = disagreement or disagreement_report()
    route = route or route_decision()
    calibration = calibration or conformal_report()
    inputs = {kind: digest(f"reasoning-{kind.value}") for kind in ReasoningInputKind}
    inputs[ReasoningInputKind.MODEL_FORECASTS] = disagreement.snapshot.snapshot_sha256
    inputs[ReasoningInputKind.MARKET_REGIME] = route.snapshot.snapshot_sha256
    inputs[ReasoningInputKind.OOD] = route.snapshot.snapshot_sha256
    inputs[ReasoningInputKind.CALIBRATION] = calibration.report_sha256
    return create_reasoning_context(
        decision_time=NOW,
        input_artifact_sha256s=inputs,
        meta_reasoner_prompt_sha256=meta_reasoner_prompt_sha256 or digest("meta-prompt"),
        meta_reasoner_model_revision_sha256=meta_reasoner_model_revision_sha256
        or digest("meta-model"),
        skeptic_prompt_sha256=skeptic_prompt_sha256 or digest("skeptic-prompt"),
        skeptic_model_revision_sha256=skeptic_model_revision_sha256 or digest("skeptic-model"),
    )


def meta_recommendation(
    context: ReasoningContext,
    *,
    recommend_abstain: bool = False,
    weight_cap: Decimal = Decimal("0.70"),
    prompt_sha256: str | None = None,
    model_revision_sha256: str | None = None,
) -> MetaReasonerRecommendation:
    return create_meta_reasoner_recommendation(
        context_sha256=context.context_sha256,
        prompt_sha256=prompt_sha256 or context.meta_reasoner_prompt_sha256,
        model_revision_sha256=model_revision_sha256 or context.meta_reasoner_model_revision_sha256,
        generated_at=NOW - timedelta(seconds=10),
        available_at=NOW - timedelta(seconds=5),
        conflict_codes=(),
        skeptic_questions=("Could this be beta rather than event alpha?",),
        recommended_model_weight_cap=weight_cap,
        recommend_abstain=recommend_abstain,
        explanation="Structured advisory output only.",
    )


def skeptic_assessment(
    context: ReasoningContext,
    *,
    blocks_new_risk: bool = False,
    severity: SkepticSeverity = SkepticSeverity.LOW,
    prompt_sha256: str | None = None,
    model_revision_sha256: str | None = None,
) -> IndependentSkepticAssessment:
    return create_independent_skeptic_assessment(
        context_sha256=context.context_sha256,
        prompt_sha256=prompt_sha256 or context.skeptic_prompt_sha256,
        model_revision_sha256=model_revision_sha256 or context.skeptic_model_revision_sha256,
        generated_at=NOW - timedelta(seconds=9),
        available_at=NOW - timedelta(seconds=4),
        findings=(
            SkepticFinding(
                code="BETA_CONFOUNDING_CHECKED",
                severity=severity,
                blocks_new_risk=blocks_new_risk,
                explanation="Independent path checked beta confounding.",
            ),
        ),
    )


def governance_report(
    *,
    disagreement: CouncilDisagreementReport | None = None,
    route: RegimeRoutingDecision | None = None,
    calibration: AdaptiveConformalReport | None = None,
    recommend_abstain: bool = False,
    skeptic_blocks: bool = False,
    skeptic_severity: SkepticSeverity = SkepticSeverity.LOW,
) -> ForecastGovernanceReport:
    disagreement = disagreement or disagreement_report()
    route = route or route_decision()
    calibration = calibration or conformal_report()
    context = reasoning_context(
        disagreement=disagreement,
        route=route,
        calibration=calibration,
    )
    return build_forecast_governance_report(
        context=context,
        meta_reasoner=meta_recommendation(context, recommend_abstain=recommend_abstain),
        skeptic=skeptic_assessment(
            context,
            blocks_new_risk=skeptic_blocks,
            severity=skeptic_severity,
        ),
        disagreement=disagreement,
        regime_route=route,
        calibration=calibration,
    )
