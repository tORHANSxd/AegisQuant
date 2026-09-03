"""Deterministic V5-P08 fixtures shared by tests and evidence generation."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

from aegisquant.domain.identifiers import ArtifactId, AssetId, InstrumentId
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.truth import TruthState
from aegisquant.research.forecasting import (
    PERMUTED_EVENT_ABLATION_ARMS,
    REQUIRED_EVENT_ABLATION_ARMS,
    BarrierHitProbabilities,
    CalibrationMethod,
    CouncilHorizon,
    DirectionProbabilitiesV2,
    EventAblationArm,
    EventAblationEvaluation,
    EventAblationSpec,
    EventConditionedForecast,
    EventConditionSnapshot,
    EventForecastComparisonLineage,
    FoldEvaluationState,
    ForecastDistributionV2,
    ForecastInputBinding,
    ForecastMetrics,
    ForecastQuantiles,
    ForecastUncertaintyV2,
    HorizonForecast,
    MarketOnlyForecast,
    MarketRegime,
    MarketStateTensor,
    capability_sha256,
    create_calibration_artifact,
    create_event_ablation_evaluation,
    create_event_condition_snapshot,
    create_event_conditioned_forecast,
    create_event_forecast_comparison_lineage,
    create_forecast_envelope,
    create_forecast_input_binding,
    create_market_only_forecast,
    create_market_state_tensor,
    default_capability_matrix,
)
from tests.v5_p05.test_canonical_events import AS_OF, canonical


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def event_condition(
    *, status: EventClusterStatus = EventClusterStatus.CONFIRMED
) -> EventConditionSnapshot:
    return create_event_condition_snapshot(
        canonical_event=canonical(
            state=(
                TruthState.RUMOR
                if status is EventClusterStatus.RUMOR
                else TruthState.VERIFIED_PRIMARY
            ),
            status=status,
        ),
        instrument_id=InstrumentId("BTCUSDT-PERP"),
        asset_id=AssetId("BTC"),
        decision_time=AS_OF,
        asset_relationship_score=Decimal("0.9"),
        relationship_snapshot_sha256=digest("btc-event-relationship"),
    )


def market_tensor(*, omit_feature: str | None = None) -> MarketStateTensor:
    feature_names = (
        "return_1m",
        "realized_volatility",
        "spread_bps",
        "depth",
        "funding",
        "basis",
        "open_interest",
        "liquidations",
        "cross_asset_return",
    )
    full_rows = (
        ("-0.01", "0.10", "2.0", "100", "0.001", "0.002", "1000", "5", "-0.02"),
        ("0.00", "0.11", "2.1", "101", "0.001", "0.002", "1010", "4", "-0.01"),
        ("0.01", "0.12", "1.9", "102", "0.002", "0.003", "1020", "3", "0.00"),
        ("0.02", "0.13", "1.8", "103", "0.002", "0.003", "1030", "2", "0.01"),
    )
    indexes = tuple(index for index, feature in enumerate(feature_names) if feature != omit_feature)
    selected_names = tuple(feature_names[index] for index in indexes)
    values = tuple(tuple(Decimal(row[index]) for index in indexes) for row in full_rows)
    observations = tuple(AS_OF - timedelta(minutes=value) for value in (4, 3, 2, 1))
    return create_market_state_tensor(
        tensor_id=ArtifactId(f"p08-market-tensor-{omit_feature or 'complete'}"),
        instrument_id=InstrumentId("BTCUSDT-PERP"),
        asset_id=AssetId("BTC"),
        window_start=observations[0],
        decision_time=AS_OF,
        observed_at=observations,
        available_at=observations,
        feature_names=selected_names,
        values=values,
        source_dataset_ids=("public-derivatives", "public-orderbook", "public-trades"),
        dataset_manifest_sha256=digest("p08-market-dataset"),
        feature_snapshot_sha256=digest(f"p08-market-features-{omit_feature or 'complete'}"),
    )


def comparison_lineage(
    *,
    horizon: CouncilHorizon = CouncilHorizon.THIRTY_MINUTES,
    fold_number: int = 1,
    split_label: str | None = None,
) -> EventForecastComparisonLineage:
    prefix = f"{horizon.value}-fold-{fold_number}"
    split_sha256 = digest(split_label or f"p08-split-{prefix}")
    return create_event_forecast_comparison_lineage(
        asset_id=AssetId("BTC"),
        instrument_id=InstrumentId("BTCUSDT-PERP"),
        horizon=horizon,
        regime=MarketRegime.NEWS_SHOCK,
        fold_id=f"fold-{fold_number}",
        split_sha256=split_sha256,
        label_dataset_manifest_sha256=digest(f"p08-labels-{horizon.value}"),
        resource_budget_sha256=digest(f"p08-budget-{horizon.value}"),
        decision_time=AS_OF,
        training_end=AS_OF - timedelta(days=20 + fold_number),
        calibration_end=AS_OF - timedelta(days=5 + fold_number),
        test_start=AS_OF - timedelta(days=2),
        test_end=AS_OF + timedelta(hours=1),
        evaluation_available_at=AS_OF + timedelta(hours=2),
        purge_seconds=3600,
        embargo_seconds=3600,
        training_sample_ids=(f"{prefix}-train-1", f"{prefix}-train-2"),
        calibration_sample_ids=(f"{prefix}-cal-1", f"{prefix}-cal-2"),
        test_sample_ids=(f"{prefix}-test-1", f"{prefix}-test-2"),
    )


def quantiles(center: Decimal) -> ForecastQuantiles:
    return ForecastQuantiles(
        q01=center - Decimal("0.09"),
        q05=center - Decimal("0.05"),
        q10=center - Decimal("0.04"),
        q25=center - Decimal("0.02"),
        q50=center,
        q75=center + Decimal("0.02"),
        q90=center + Decimal("0.04"),
        q95=center + Decimal("0.05"),
        q99=center + Decimal("0.09"),
    )


def horizon_forecast(
    *,
    horizon: CouncilHorizon,
    mean: Decimal,
    up_probability: Decimal,
    volatility: Decimal,
    tail_risk: Decimal,
    liquidity: Decimal,
    spread: Decimal,
    slippage: Decimal,
    abstain_probability: Decimal,
) -> HorizonForecast:
    return HorizonForecast(
        horizon=horizon,
        return_distribution=ForecastDistributionV2(
            mean=mean,
            standard_deviation=Decimal("0.03"),
            quantiles=quantiles(mean),
        ),
        direction_probabilities=DirectionProbabilitiesV2(
            up=up_probability,
            flat=Decimal("0.20"),
            down=Decimal("0.80") - up_probability,
        ),
        realized_volatility_distribution=ForecastDistributionV2(
            mean=volatility,
            standard_deviation=Decimal("0.02"),
            quantiles=quantiles(volatility),
        ),
        future_high_low_range=Decimal("0.04"),
        maximum_favorable_excursion=Decimal("0.03"),
        maximum_adverse_excursion=Decimal("-0.02"),
        barrier_hit_probabilities=BarrierHitProbabilities(
            upside=Decimal("0.40"), downside=Decimal("0.30")
        ),
        tail_risk_probability=tail_risk,
        liquidity_forecast=liquidity,
        spread_forecast=spread,
        slippage_forecast=slippage,
        uncertainty=ForecastUncertaintyV2(
            epistemic=Decimal("0.01"),
            aleatoric=Decimal("0.02"),
            ensemble_disagreement=Decimal("0.01"),
        ),
        abstain_probability=abstain_probability,
    )


def forecast_pair(
    *,
    horizon: CouncilHorizon = CouncilHorizon.THIRTY_MINUTES,
    fold_number: int = 1,
    condition: EventConditionSnapshot | None = None,
    tensor: MarketStateTensor | None = None,
    event_should_abstain: bool = False,
) -> tuple[MarketOnlyForecast, EventConditionedForecast]:
    resolved_condition = condition or event_condition()
    resolved_tensor = tensor or market_tensor()
    lineage = comparison_lineage(horizon=horizon, fold_number=fold_number)
    capability = next(
        item
        for item in default_capability_matrix(as_of_time=AS_OF).candidates
        if item.candidate_id == "linear-baseline"
    )
    calibration = create_calibration_artifact(
        calibration_id=ArtifactId(f"p08-calibration-{horizon.value}-{fold_number}"),
        method=CalibrationMethod.ADAPTIVE_CONFORMAL,
        asset_id=AssetId("BTC"),
        horizon=horizon,
        regime=MarketRegime.NEWS_SHOCK,
        training_cutoff=AS_OF - timedelta(days=30),
        fitted_at=AS_OF - timedelta(days=10),
        available_at=AS_OF - timedelta(days=9),
        calibration_sample_ids=lineage.calibration_sample_ids,
        forbidden_test_sample_ids=lineage.test_sample_ids,
        split_sha256=lineage.split_sha256,
    )
    market_horizon = horizon_forecast(
        horizon=horizon,
        mean=Decimal("0.010"),
        up_probability=Decimal("0.45"),
        volatility=Decimal("0.10"),
        tail_risk=Decimal("0.05"),
        liquidity=Decimal("100"),
        spread=Decimal("2"),
        slippage=Decimal("3"),
        abstain_probability=Decimal("0.10"),
    )
    event_horizon = horizon_forecast(
        horizon=horizon,
        mean=Decimal("0.015"),
        up_probability=Decimal("0.50"),
        volatility=Decimal("0.12"),
        tail_risk=Decimal("0.08"),
        liquidity=Decimal("90"),
        spread=Decimal("3"),
        slippage=Decimal("4"),
        abstain_probability=Decimal("0.12"),
    )

    def bound(kind: str, horizon_value: HorizonForecast, *, abstain: bool) -> ForecastInputBinding:
        reasons = ("EVENT_DIRECTIONAL_GATE_DENIED",) if abstain else ()
        forecast = create_forecast_envelope(
            forecast_id=ArtifactId(f"p08-{kind}-{horizon.value}-{fold_number}"),
            model_id=capability.candidate_id,
            model_revision=capability.model_revision,
            model_capability_sha256=capability_sha256(capability),
            market_state_tensor_sha256=resolved_tensor.tensor_sha256,
            dataset_manifest_sha256=resolved_tensor.dataset_manifest_sha256,
            calibration_artifact_sha256_by_horizon={horizon: calibration.artifact_sha256},
            instrument_id=resolved_tensor.instrument_id,
            asset_id=resolved_tensor.asset_id,
            as_of_time=resolved_tensor.decision_time,
            regime=MarketRegime.NEWS_SHOCK,
            prediction_mode=capability.prediction_modes[0],
            horizons=(horizon_value,),
            should_abstain=abstain,
            abstain_reasons=reasons,
        )
        return create_forecast_input_binding(
            forecast=forecast,
            market_state_tensor=resolved_tensor,
            calibrations=(calibration,),
            capability=capability,
        )

    market_inputs = bound("market-only", market_horizon, abstain=False)
    event_inputs = bound("market-event", event_horizon, abstain=event_should_abstain)
    return (
        create_market_only_forecast(inputs=market_inputs, lineage=lineage),
        create_event_conditioned_forecast(
            inputs=event_inputs,
            lineage=lineage,
            event_condition=resolved_condition,
        ),
    )


def metrics(loss: Decimal, *, net_return: Decimal | None = None) -> ForecastMetrics:
    return ForecastMetrics(
        primary_loss=loss,
        direction_accuracy=Decimal("0.55"),
        mean_absolute_error=loss,
        root_mean_squared_error=loss + Decimal("0.01"),
        crps=loss,
        pinball_loss=loss / Decimal("2"),
        brier_score=Decimal("0.20"),
        interval_coverage=Decimal("0.90"),
        tail_recall=Decimal("0.60"),
        net_return_after_cost=net_return if net_return is not None else Decimal("0"),
    )


DEFAULT_ABLATION_LOSSES = {
    EventAblationArm.MARKET_ONLY: Decimal("0.30"),
    EventAblationArm.EVENT_ONLY: Decimal("0.28"),
    EventAblationArm.MARKET_EVENT: Decimal("0.20"),
    EventAblationArm.RISK_ONLY: Decimal("0.35"),
    EventAblationArm.TRUTH_PERMUTED: Decimal("0.205"),
    EventAblationArm.EVENT_PERMUTED: Decimal("0.30"),
    EventAblationArm.TEXT_PERMUTED: Decimal("0.31"),
    EventAblationArm.TIMESTAMP_PLACEBO: Decimal("0.32"),
    EventAblationArm.ASSET_PLACEBO: Decimal("0.29"),
}


def ablation_spec() -> EventAblationSpec:
    return EventAblationSpec(
        expected_fold_count=2,
        minimum_market_event_loss_improvement=Decimal("0.02"),
        minimum_permutation_loss_degradation=Decimal("0.02"),
        evaluation_cutoff=AS_OF + timedelta(hours=3),
        required_arms=REQUIRED_EVENT_ABLATION_ARMS,
        fixed_horizon_scale_allowed=False,
        final_holdout_opened=False,
    )


def ablation_evaluations(
    *,
    horizon: CouncilHorizon = CouncilHorizon.THIRTY_MINUTES,
    losses: dict[EventAblationArm, Decimal] | None = None,
    failed_arm: EventAblationArm | None = None,
) -> tuple[EventAblationEvaluation, ...]:
    resolved_losses = losses or DEFAULT_ABLATION_LOSSES
    snapshot_sha256 = event_condition().snapshot_sha256
    evaluations: list[EventAblationEvaluation] = []
    for arm in REQUIRED_EVENT_ABLATION_ARMS:
        for fold_number in (1, 2):
            failed = arm is failed_arm and fold_number == 2
            evaluations.append(
                create_event_ablation_evaluation(
                    arm=arm,
                    lineage=comparison_lineage(
                        horizon=horizon,
                        fold_number=fold_number,
                    ),
                    event_condition_snapshot_sha256=(
                        None if arm is EventAblationArm.MARKET_ONLY else snapshot_sha256
                    ),
                    permutation_plan_sha256=(
                        digest(f"p08-permutation-{arm.value}-{fold_number}")
                        if arm in PERMUTED_EVENT_ABLATION_ARMS
                        else None
                    ),
                    prediction_artifact_sha256=digest(
                        f"p08-prediction-{horizon.value}-{arm.value}-{fold_number}"
                    ),
                    state=(FoldEvaluationState.FAILED if failed else FoldEvaluationState.EVALUATED),
                    metrics=(None if failed else metrics(resolved_losses[arm])),
                    abstain_or_failure_reason=("SIMULATED_TIMEOUT" if failed else None),
                )
            )
    return tuple(evaluations)
