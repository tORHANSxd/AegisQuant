"""Deterministic DEVELOPMENT fixtures for the V5-P10 decision boundary."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.decision import (
    CostCalibrationState,
    DirectionalForecastDistribution,
    DirectionalForecastScenario,
    ExecutionCostDistribution,
    ExecutionCostModelV2,
    ExecutionCostScenario,
    MakerQueueMode,
    NetEdgeDistribution,
    NetEdgePolicy,
    NetEdgeThresholdSource,
    PositionDirection,
    RiskOverlayPolicy,
    create_directional_forecast_distribution,
    create_execution_cost_distribution,
    create_execution_cost_model_v2,
    create_net_edge_policy,
    create_risk_overlay_policy,
    directional_signal_id,
    evaluate_net_edge,
)
from aegisquant.domain.identifiers import (
    AccountId,
    AssetId,
    InstrumentId,
    ProposalId,
    StrategyId,
    VenueId,
)
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.truth import TruthState
from aegisquant.intelligence.canonical_events import build_canonical_event
from aegisquant.portfolio.models import (
    ExposureConstraint,
    ExposureDimension,
    FactorRisk,
    PortfolioConstructionPolicy,
    PortfolioProposal,
    RiskBudget,
    RiskRegime,
    SignalInput,
)
from aegisquant.portfolio.optimizer import build_portfolio_proposal
from aegisquant.portfolio.risk_estimation import estimate_covariance
from aegisquant.research.forecasting import (
    AdaptiveConformalPolicy,
    CalibrationMethod,
    CouncilDisagreementPolicy,
    CouncilHorizon,
    CouncilMemberSignal,
    DynamicStackingPolicy,
    EventConditionSnapshot,
    ForecastGovernanceReport,
    IntervalCoverageObservation,
    MarketRegime,
    ReasoningInputKind,
    SkepticFinding,
    SkepticSeverity,
    WeightEvidenceSource,
    build_forecast_governance_report,
    compute_event_increment,
    create_council_signal_snapshot,
    create_event_condition_snapshot,
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
from aegisquant.risk.engine import build_risk_snapshot, evaluate_portfolio_proposal
from aegisquant.risk.models import RiskDecision, RiskPosition
from aegisquant.risk.policy import (
    PreTradeLimits,
    RecoveryCondition,
    RiskPolicy,
    SignedRiskPolicy,
    risk_policy_payload,
    risk_policy_sha256,
)
from tests.p11_helpers import SIGNER_KEY_ID, fixture_private_key, trusted_public_keys
from tests.v5_p05.test_canonical_events import (
    AS_OF,
    BASE,
    cluster,
    diffusion,
    reflection,
    surprise,
    truth,
)
from tests.v5_p08.helpers import forecast_pair

ASSET = AssetId("BTC")
INSTRUMENT = InstrumentId("BTCUSDT-PERP")
SLEEVE = "event-alpha"
ACCOUNT = AccountId("paper-p10")
STRATEGY = StrategyId("v5-p10-event")
VENUE = VenueId("paper-venue")
USDT = AssetId("USDT")
HORIZON = CouncilHorizon.THIRTY_MINUTES
REGIME = MarketRegime.NEWS_SHOCK
DECISION_TIME = AS_OF + timedelta(seconds=2)


def digest(label: str) -> str:
    return canonical_sha256({"fixture": label})


def event_condition(
    *,
    status: EventClusterStatus = EventClusterStatus.CONFIRMED,
    truth_state: TruthState = TruthState.VERIFIED_PRIMARY,
    truth_probability: Decimal = Decimal("0.995"),
    severity: Decimal = Decimal("0.90"),
    reflection_strength: Decimal = Decimal("0.40"),
) -> EventConditionSnapshot:
    value_snapshot, event_surprise = surprise(at=BASE)
    assessment = truth(state=truth_state, at=BASE).model_copy(
        update={"claim_truth_probability": truth_probability}
    )
    event = build_canonical_event(
        cluster=cluster(status=status, at=BASE),
        truth_assessment=assessment,
        narrative_diffusion=diffusion(at=BASE),
        market_reflection=reflection(reflection_strength, at=BASE),
        event_value_snapshot=value_snapshot,
        event_surprise=event_surprise,
        as_of_time=AS_OF,
        jurisdiction="US",
        affected_assets=("asset:BTC",),
        novelty=Decimal("0.80"),
        severity=severity,
        persistence=Decimal("0.50"),
        transmission_channels=("rates", "liquidity"),
    )
    return create_event_condition_snapshot(
        canonical_event=event,
        instrument_id=INSTRUMENT,
        asset_id=ASSET,
        decision_time=AS_OF,
        asset_relationship_score=Decimal("0.90"),
        relationship_snapshot_sha256=digest("p10-event-relationship"),
    )


def governance(
    *,
    truth_state: TruthState = TruthState.VERIFIED_PRIMARY,
    ood_score: Decimal = Decimal("0.10"),
    data_quality: Decimal = Decimal("0.95"),
    council_returns: tuple[Decimal, Decimal] = (Decimal("0.010"), Decimal("0.012")),
) -> ForecastGovernanceReport:
    model_ids = ("baseline", "supervised")
    signals = tuple(
        CouncilMemberSignal(
            candidate_id=model_id,
            forecast_sha256=digest(f"p10-forecast-{model_id}"),
            expected_return=expected_return,
            available_at=AS_OF - timedelta(seconds=20),
        )
        for model_id, expected_return in zip(model_ids, council_returns, strict=True)
    )
    council = create_council_signal_snapshot(
        asset_id=ASSET,
        horizon=HORIZON,
        regime=REGIME,
        decision_time=AS_OF,
        signals=signals,
    )
    disagreement = evaluate_council_disagreement(
        snapshot=council,
        policy=CouncilDisagreementPolicy(maximum_expected_return_range=Decimal("0.02")),
    )
    weights = create_statistical_weight_proposal(
        asset_id=ASSET,
        horizon=HORIZON,
        regime=REGIME,
        training_cutoff=AS_OF - timedelta(days=2),
        available_at=AS_OF - timedelta(minutes=1),
        previous_weights=StackingWeights(
            weights={"baseline": Decimal("0.50"), "supervised": Decimal("0.50")},
            maximum_weight=Decimal("0.70"),
        ),
        proposed_weights=StackingWeights(
            weights={"baseline": Decimal("0.40"), "supervised": Decimal("0.60")},
            maximum_weight=Decimal("0.70"),
        ),
        evidence_sha256_by_source={
            WeightEvidenceSource.VALIDATION: digest("p10-validation"),
            WeightEvidenceSource.CALIBRATION: digest("p10-calibration"),
        },
        split_sha256=digest("p10-stacking-split"),
    )
    routing_snapshot = create_regime_routing_snapshot(
        asset_id=ASSET,
        horizon=HORIZON,
        regime=REGIME,
        observed_at=AS_OF - timedelta(seconds=30),
        available_at=AS_OF - timedelta(seconds=20),
        decision_time=AS_OF,
        data_quality=data_quality,
        truth_state=truth_state,
        ood_score=ood_score,
        model_reliability_by_id={
            "baseline": Decimal("0.90"),
            "supervised": Decimal("0.85"),
        },
    )
    route = route_dynamic_stacking(
        snapshot=routing_snapshot,
        proposal=weights,
        policy=DynamicStackingPolicy(
            maximum_single_model_weight=Decimal("0.70"),
            maximum_weight_step=Decimal("0.10"),
            maximum_ood_score=Decimal("1"),
            minimum_data_quality=Decimal("0.70"),
            minimum_model_reliability=Decimal("0.60"),
        ),
    )
    realized = (
        Decimal("0"),
        Decimal("0.05"),
        Decimal("-0.05"),
        Decimal("0.09"),
        Decimal("0.20"),
    )
    observations = tuple(
        IntervalCoverageObservation(
            sample_id=f"p10-coverage-{index}",
            predicted_lower=Decimal("-0.10"),
            predicted_median=Decimal("0"),
            predicted_upper=Decimal("0.10"),
            realized_value=value,
            predicted_at=AS_OF - timedelta(minutes=10 - index),
            outcome_available_at=AS_OF - timedelta(minutes=9 - index),
        )
        for index, value in enumerate(realized)
    )
    window = create_interval_coverage_window(
        asset_id=ASSET,
        horizon=HORIZON,
        regime=REGIME,
        model_revision_sha256=digest("p10-ensemble"),
        dataset_manifest_sha256=digest("p10-coverage-dataset"),
        calibration_artifact_sha256=digest("p10-base-calibration"),
        window_start=AS_OF - timedelta(minutes=12),
        window_end=AS_OF - timedelta(minutes=1),
        decision_time=AS_OF,
        observations=observations,
    )
    calibration = evaluate_adaptive_conformal(
        window=window,
        policy=AdaptiveConformalPolicy(
            method=CalibrationMethod.DISTRIBUTION_AWARE_CONFORMAL,
            target_coverage=Decimal("0.80"),
            warning_shortfall=Decimal("0.10"),
            critical_shortfall=Decimal("0.20"),
            minimum_sample_count=5,
            maximum_window_age_seconds=Decimal("120"),
            maximum_adjustment_step=Decimal("0.05"),
        ),
    )
    inputs = {kind: digest(f"p10-reasoning-{kind.value}") for kind in ReasoningInputKind}
    inputs[ReasoningInputKind.MODEL_FORECASTS] = council.snapshot_sha256
    inputs[ReasoningInputKind.MARKET_REGIME] = route.snapshot.snapshot_sha256
    inputs[ReasoningInputKind.OOD] = route.snapshot.snapshot_sha256
    inputs[ReasoningInputKind.CALIBRATION] = calibration.report_sha256
    context = create_reasoning_context(
        decision_time=AS_OF,
        input_artifact_sha256s=inputs,
        meta_reasoner_prompt_sha256=digest("p10-meta-prompt"),
        meta_reasoner_model_revision_sha256=digest("p10-meta-model"),
        skeptic_prompt_sha256=digest("p10-skeptic-prompt"),
        skeptic_model_revision_sha256=digest("p10-skeptic-model"),
    )
    meta = create_meta_reasoner_recommendation(
        context_sha256=context.context_sha256,
        prompt_sha256=context.meta_reasoner_prompt_sha256,
        model_revision_sha256=context.meta_reasoner_model_revision_sha256,
        generated_at=AS_OF - timedelta(seconds=10),
        available_at=AS_OF - timedelta(seconds=5),
        conflict_codes=(),
        skeptic_questions=("Is the event already priced?",),
        recommended_model_weight_cap=Decimal("0.70"),
        recommend_abstain=False,
        explanation="Structured DEVELOPMENT fixture.",
    )
    skeptic = create_independent_skeptic_assessment(
        context_sha256=context.context_sha256,
        prompt_sha256=context.skeptic_prompt_sha256,
        model_revision_sha256=context.skeptic_model_revision_sha256,
        generated_at=AS_OF - timedelta(seconds=9),
        available_at=AS_OF - timedelta(seconds=4),
        findings=(
            SkepticFinding(
                code="PRICE_IN_AND_BETA_CHECKED",
                severity=SkepticSeverity.LOW,
                blocks_new_risk=False,
                explanation="Independent DEVELOPMENT check.",
            ),
        ),
    )
    return build_forecast_governance_report(
        context=context,
        meta_reasoner=meta,
        skeptic=skeptic,
        disagreement=disagreement,
        regime_route=route,
        calibration=calibration,
    )


def forecast_distribution(
    *,
    condition: EventConditionSnapshot | None = None,
    governed: ForecastGovernanceReport | None = None,
    event_should_abstain: bool = False,
) -> DirectionalForecastDistribution:
    resolved_condition = condition or event_condition()
    market_only, event_conditioned = forecast_pair(
        horizon=HORIZON,
        condition=resolved_condition,
        event_should_abstain=event_should_abstain,
    )
    increment = compute_event_increment(
        market_only=market_only,
        event_conditioned=event_conditioned,
    )
    scenarios = (
        DirectionalForecastScenario(
            scenario_id="scenario-01", probability=Decimal("0.10"), gross_edge=Decimal("-0.005")
        ),
        DirectionalForecastScenario(
            scenario_id="scenario-02", probability=Decimal("0.20"), gross_edge=Decimal("0.010")
        ),
        DirectionalForecastScenario(
            scenario_id="scenario-03", probability=Decimal("0.30"), gross_edge=Decimal("0.015")
        ),
        DirectionalForecastScenario(
            scenario_id="scenario-04", probability=Decimal("0.40"), gross_edge=Decimal("0.0225")
        ),
    )
    return create_directional_forecast_distribution(
        governance=governed or governance(),
        event_increment=increment,
        direction=PositionDirection.LONG,
        sleeve_id=SLEEVE,
        scenarios=scenarios,
    )


def cost_model(
    *,
    confidence: Decimal = Decimal("0.95"),
    state: CostCalibrationState = CostCalibrationState.WITHIN_TOLERANCE,
) -> ExecutionCostModelV2:
    has_tca = state is not CostCalibrationState.UNVERIFIED
    return create_execution_cost_model_v2(
        version="p10-cost-v2-development",
        queue_mode=MakerQueueMode.CONSERVATIVE_QUEUE,
        replay_inputs=None,
        calibration_state=state,
        tca_artifact_sha256=digest("p10-development-tca") if has_tca else None,
        tca_sample_count=100 if has_tca else 0,
        cost_confidence=confidence,
    )


def cost_scenario(
    scenario_id: str,
    probability: Decimal,
    *,
    component_cost: Decimal = Decimal("0.0002"),
) -> ExecutionCostScenario:
    return ExecutionCostScenario(
        scenario_id=scenario_id,
        probability=probability,
        fee=component_cost,
        spread=component_cost,
        slippage=component_cost,
        market_impact=component_cost,
        queue_probability=Decimal("0.40"),
        maker_adverse_selection=component_cost,
        latency_cost=component_cost,
        funding=component_cost,
        borrow=component_cost,
        settlement=component_cost,
        liquidation_risk=component_cost,
        total_cost=component_cost * Decimal("10"),
    )


def cost_distribution(
    *,
    model: ExecutionCostModelV2 | None = None,
    component_cost: Decimal = Decimal("0.0002"),
) -> ExecutionCostDistribution:
    probabilities = (Decimal("0.10"), Decimal("0.20"), Decimal("0.30"), Decimal("0.40"))
    scenarios = tuple(
        cost_scenario(f"scenario-0{index}", probability, component_cost=component_cost)
        for index, probability in enumerate(probabilities, start=1)
    )
    return create_execution_cost_distribution(
        model=model or cost_model(),
        asset_id=ASSET,
        instrument_id=INSTRUMENT,
        horizon=HORIZON,
        sleeve_id=SLEEVE,
        decision_time=AS_OF,
        available_at=AS_OF - timedelta(seconds=1),
        scenarios=scenarios,
    )


def net_edge_policy(**updates: object) -> NetEdgePolicy:
    values: dict[str, object] = {
        "version": "p10-bootstrap-v1",
        "asset_id": ASSET,
        "horizon": HORIZON,
        "sleeve_id": SLEEVE,
        "threshold_source": NetEdgeThresholdSource.BOOTSTRAP,
        "oos_evidence_sha256": None,
        "minimum_probability_positive": Decimal("0.60"),
        "confidence_level": Decimal("0.80"),
        "economic_floor": Decimal("0.001"),
        "minimum_net_edge_cost_ratio": Decimal("2"),
        "minimum_truth_probability": Decimal("0.99"),
        "maximum_contradiction_probability": Decimal("0.05"),
        "maximum_manipulation_probability": Decimal("0.05"),
        "minimum_novelty": Decimal("0.70"),
        "maximum_market_reflection": Decimal("0.79"),
        "maximum_forecast_range": Decimal("0.02"),
        "maximum_ood_score": Decimal("1"),
        "minimum_data_quality": Decimal("0.70"),
        "minimum_event_increment_magnitude": Decimal("0.001"),
        "minimum_cost_confidence": Decimal("0.80"),
    }
    values.update(updates)
    return create_net_edge_policy(**values)  # type: ignore[arg-type]


def net_edge(
    *,
    forecast: DirectionalForecastDistribution | None = None,
    costs: ExecutionCostDistribution | None = None,
    policy: NetEdgePolicy | None = None,
) -> NetEdgeDistribution:
    return evaluate_net_edge(
        forecast=forecast or forecast_distribution(),
        costs=costs or cost_distribution(),
        policy=policy or net_edge_policy(),
    )


def overlay_policy() -> RiskOverlayPolicy:
    return create_risk_overlay_policy(
        version="p10-overlay-v1",
        minimum_truth_probability=Decimal("0.60"),
        minimum_severity=Decimal("0.80"),
        target_exposure_scale=Decimal("0.50"),
    )


def portfolio(
    forecast: DirectionalForecastDistribution,
    *,
    current_weight: Decimal = Decimal("0"),
    raw_score: Decimal = Decimal("0.20"),
) -> PortfolioProposal:
    signal = SignalInput(
        signal_id=directional_signal_id(forecast),
        asset_id=ASSET,
        instrument_id=INSTRUMENT,
        strategy_id=STRATEGY,
        account_id=ACCOUNT,
        sleeve_id=SLEEVE,
        venue_id=VENUE,
        stablecoin_id=USDT,
        correlation_cluster_id="btc",
        raw_score=raw_score,
        confidence=Decimal("0.90"),
        expected_return=forecast.expected_gross_edge,
        current_weight=current_weight,
        average_daily_notional=Decimal("1000000"),
        impact_coefficient_bps=Decimal("10"),
    )
    covariance = estimate_covariance(
        asset_ids=(ASSET,),
        sample_covariance=((Decimal("0.04"),),),
        shrinkage=Decimal("0.50"),
        factors=(
            FactorRisk(
                factor_id="market",
                variance=Decimal("0.01"),
                exposures={"BTC": Decimal("1")},
            ),
        ),
        regime=RiskRegime.STRESSED,
        regime_multiplier=Decimal("1.5"),
        observed_at=AS_OF - timedelta(seconds=2),
        available_at=AS_OF - timedelta(seconds=1),
    )
    policy = PortfolioConstructionPolicy(
        version="p10-portfolio-v1",
        no_trade_zone=Decimal("0.001"),
        uncertainty_penalty=Decimal("0.20"),
        volatility_target=Decimal("0.25"),
        maximum_gross_weight=Decimal("0.50"),
        maximum_turnover=Decimal("0.40"),
        maximum_participation=Decimal("0.10"),
        maximum_impact_bps=Decimal("20"),
        risk_budgets=(RiskBudget(asset_id=ASSET, maximum_risk_share=Decimal("0.50")),),
        exposure_constraints=(
            ExposureConstraint(
                dimension=ExposureDimension.ASSET,
                key="BTC",
                maximum_absolute_weight=Decimal("0.50"),
            ),
        ),
    )
    return build_portfolio_proposal(
        proposal_id=ProposalId(f"p10-{current_weight}-{raw_score}"),
        signals=(signal,),
        covariance=covariance,
        policy=policy,
        portfolio_nav=Decimal("100000"),
        as_of_time=AS_OF,
        created_at=AS_OF + timedelta(seconds=1),
        validity_seconds=120,
    )


def risk_decision(
    proposal: PortfolioProposal,
    *,
    major_event_clear: bool = True,
) -> RiskDecision:
    positions = tuple(
        RiskPosition(
            instrument_id=leg.instrument_id,
            asset_id=leg.asset_id,
            strategy_id=leg.strategy_id,
            account_id=leg.account_id,
            signed_weight=leg.current_weight,
        )
        for leg in proposal.legs
    )
    snapshot = build_risk_snapshot(
        snapshot_id=f"p10-snapshot-{major_event_clear}",
        as_of_time=AS_OF,
        available_at=AS_OF + timedelta(seconds=1),
        data_last_available_at=AS_OF,
        model_last_available_at=AS_OF,
        positions=positions,
        daily_pnl_fraction=Decimal("0"),
        drawdown_fraction=Decimal("0"),
        margin_utilization=Decimal("0.20"),
        liquidity_score=Decimal("0.90"),
        venue_operational=True,
        security_clear=True,
        major_event_clear=major_event_clear,
        ledger_reconciled=True,
    )
    policy = RiskPolicy(
        policy_id="p10-risk-policy",
        version="p10-risk-v1",
        effective_at=AS_OF - timedelta(days=1),
        expires_at=AS_OF + timedelta(days=1),
        snapshot_max_age_seconds=30,
        caution_target_scale=Decimal("0.50"),
        maximum_daily_loss_fraction=Decimal("0.05"),
        maximum_drawdown_fraction=Decimal("0.10"),
        maximum_margin_utilization=Decimal("0.80"),
        minimum_liquidity_score=Decimal("0.20"),
        maximum_rumor_reduction_fraction=Decimal("0.25"),
        pre_trade_limits=PreTradeLimits(
            maximum_order_weight=Decimal("0.40"),
            maximum_asset_gross_weight=Decimal("0.50"),
            maximum_strategy_gross_weight=Decimal("0.50"),
            maximum_account_gross_weight=Decimal("0.50"),
        ),
        recovery_conditions=tuple(RecoveryCondition),
    )
    signed = SignedRiskPolicy(
        policy=policy,
        policy_sha256=risk_policy_sha256(policy),
        signer_key_id=SIGNER_KEY_ID,
        signature_hex=fixture_private_key().sign(risk_policy_payload(policy)).hex(),
    )
    return evaluate_portfolio_proposal(
        proposal=proposal,
        snapshot=snapshot,
        signed_policy=signed,
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
