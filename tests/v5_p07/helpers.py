"""Deterministic fixtures for V5-P07 tests and evidence generation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.domain.identifiers import ArtifactId, AssetId, InstrumentId
from aegisquant.research.budgets import ResourceBudget, ResourceRequest
from aegisquant.research.forecasting import (
    BarrierHitProbabilities,
    CalibrationArtifact,
    CalibrationMethod,
    CandidateGateDecision,
    CouncilHorizon,
    DirectionProbabilitiesV2,
    FoldEvaluationState,
    ForecastDistributionV2,
    ForecastEnvelope,
    ForecastMetrics,
    ForecastQuantiles,
    ForecastUncertaintyV2,
    HorizonForecast,
    MarketRegime,
    MarketStateTensor,
    ModelCapability,
    OosFoldEvaluation,
    PredictionMode,
    capability_sha256,
    create_calibration_artifact,
    create_forecast_envelope,
    create_market_state_tensor,
    default_capability_matrix,
    evaluate_candidate_gate,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def instant(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def market_tensor(
    *, asset: str = "BTC", decision_time: datetime | None = None
) -> MarketStateTensor:
    decision = decision_time or datetime(2026, 2, 1, tzinfo=UTC)
    observations = tuple(decision - timedelta(minutes=value) for value in (4, 3, 2, 1))
    return create_market_state_tensor(
        tensor_id=ArtifactId(f"tensor-{asset.casefold()}"),
        instrument_id=InstrumentId(f"{asset}USDT-PERP"),
        asset_id=AssetId(asset),
        window_start=observations[0],
        decision_time=decision,
        observed_at=observations,
        available_at=observations,
        feature_names=("return_1m", "spread_bps", "depth"),
        values=(
            (Decimal("-0.01"), Decimal("2"), Decimal("100")),
            (Decimal("0.00"), Decimal("2.1"), Decimal("101")),
            (Decimal("0.01"), None, Decimal("102")),
            (Decimal("0.02"), Decimal("1.9"), Decimal("103")),
        ),
        source_dataset_ids=("public-orderbook", "public-trades"),
        dataset_manifest_sha256=digest(f"dataset-{asset}"),
        feature_snapshot_sha256=digest(f"features-{asset}"),
    )


def calibration(
    *,
    asset: str = "BTC",
    horizon: CouncilHorizon = CouncilHorizon.THIRTY_MINUTES,
    regime: MarketRegime = MarketRegime.TREND,
    available_at: datetime | None = None,
) -> CalibrationArtifact:
    return create_calibration_artifact(
        calibration_id=ArtifactId(f"cal-{asset.casefold()}-{horizon.value}"),
        method=CalibrationMethod.ADAPTIVE_CONFORMAL,
        asset_id=AssetId(asset),
        horizon=horizon,
        regime=regime,
        training_cutoff=instant(10),
        fitted_at=instant(11),
        available_at=available_at or instant(12),
        calibration_sample_ids=(f"{asset}-cal-1", f"{asset}-cal-2"),
        forbidden_test_sample_ids=(f"{asset}-test-1", f"{asset}-test-2"),
        split_sha256=digest(f"split-{asset}-{horizon.value}"),
    )


def quantiles(base: str = "0") -> ForecastQuantiles:
    center = Decimal(base)
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
    horizon: CouncilHorizon = CouncilHorizon.THIRTY_MINUTES,
) -> HorizonForecast:
    return HorizonForecast(
        horizon=horizon,
        return_distribution=ForecastDistributionV2(
            mean=Decimal("0.01"),
            standard_deviation=Decimal("0.03"),
            quantiles=quantiles(),
        ),
        direction_probabilities=DirectionProbabilitiesV2(
            up=Decimal("0.45"), flat=Decimal("0.20"), down=Decimal("0.35")
        ),
        realized_volatility_distribution=ForecastDistributionV2(
            mean=Decimal("0.10"),
            standard_deviation=Decimal("0.02"),
            quantiles=quantiles("0.10"),
        ),
        future_high_low_range=Decimal("0.04"),
        maximum_favorable_excursion=Decimal("0.03"),
        maximum_adverse_excursion=Decimal("-0.02"),
        barrier_hit_probabilities=BarrierHitProbabilities(
            upside=Decimal("0.40"), downside=Decimal("0.30")
        ),
        tail_risk_probability=Decimal("0.05"),
        liquidity_forecast=Decimal("100"),
        spread_forecast=Decimal("2"),
        slippage_forecast=Decimal("3"),
        uncertainty=ForecastUncertaintyV2(
            epistemic=Decimal("0.01"),
            aleatoric=Decimal("0.02"),
            ensemble_disagreement=Decimal("0.01"),
        ),
        abstain_probability=Decimal("0.10"),
    )


def capability(candidate_id: str) -> ModelCapability:
    matrix = default_capability_matrix(as_of_time=instant(20))
    return next(item for item in matrix.candidates if item.candidate_id == candidate_id)


def forecast_envelope(
    *,
    tensor: MarketStateTensor | None = None,
    artifact: CalibrationArtifact | None = None,
    candidate: ModelCapability | None = None,
    horizon: CouncilHorizon = CouncilHorizon.THIRTY_MINUTES,
    model_capability_sha256: str | None = None,
    market_state_tensor_sha256: str | None = None,
    calibration_artifact_sha256: str | None = None,
) -> ForecastEnvelope:
    resolved_tensor = tensor or market_tensor()
    resolved_calibration = artifact or calibration(horizon=horizon)
    resolved_candidate = candidate or capability("linear-baseline")
    return create_forecast_envelope(
        forecast_id=ArtifactId("forecast-development"),
        model_id=resolved_candidate.candidate_id,
        model_revision=resolved_candidate.model_revision,
        model_capability_sha256=(model_capability_sha256 or capability_sha256(resolved_candidate)),
        market_state_tensor_sha256=(market_state_tensor_sha256 or resolved_tensor.tensor_sha256),
        dataset_manifest_sha256=resolved_tensor.dataset_manifest_sha256,
        calibration_artifact_sha256_by_horizon={
            horizon: calibration_artifact_sha256 or resolved_calibration.artifact_sha256
        },
        instrument_id=resolved_tensor.instrument_id,
        asset_id=resolved_tensor.asset_id,
        as_of_time=resolved_tensor.decision_time,
        regime=resolved_calibration.regime,
        prediction_mode=resolved_candidate.prediction_modes[0],
        horizons=(horizon_forecast(horizon),),
        should_abstain=False,
        abstain_reasons=(),
    )


def budget() -> ResourceBudget:
    return ResourceBudget(
        max_trials=4,
        max_train_seconds=Decimal("60"),
        max_inference_latency_ms=Decimal("100"),
        max_ram_mb=Decimal("2048"),
        max_gpu_memory_mb=Decimal("0"),
        max_x_calls=0,
        max_news_calls=0,
        max_cloud_cost_usd=Decimal("0"),
    )


def request() -> ResourceRequest:
    return ResourceRequest(
        trials=1,
        train_seconds=Decimal("10"),
        inference_latency_ms=Decimal("10"),
        ram_mb=Decimal("512"),
    )


def gate(candidate_id: str) -> CandidateGateDecision:
    return evaluate_candidate_gate(
        capability=capability(candidate_id),
        budget=budget(),
        request=request(),
        dependency_available=True,
        weights_verified=True,
    )


def metrics(loss: str, *, net_return: str = "0") -> ForecastMetrics:
    value = Decimal(loss)
    return ForecastMetrics(
        primary_loss=value,
        direction_accuracy=Decimal("0.55"),
        mean_absolute_error=value,
        root_mean_squared_error=value + Decimal("0.01"),
        crps=value,
        pinball_loss=value / Decimal("2"),
        brier_score=Decimal("0.20"),
        interval_coverage=Decimal("0.90"),
        tail_recall=Decimal("0.60"),
        net_return_after_cost=Decimal(net_return),
    )


def fold(
    *,
    candidate_id: str,
    fold_number: int,
    loss: str,
    asset: str = "BTC",
    horizon: CouncilHorizon = CouncilHorizon.THIRTY_MINUTES,
    regime: MarketRegime = MarketRegime.TREND,
    mode: PredictionMode | None = None,
    state: FoldEvaluationState = FoldEvaluationState.EVALUATED,
    failure_reason: str | None = None,
    model_capability: ModelCapability | None = None,
) -> OosFoldEvaluation:
    offset = (fold_number - 1) * 5
    prefix = f"{asset}-{horizon.value}-{regime.value}-f{fold_number}"
    resolved_capability = model_capability or capability(candidate_id)
    return OosFoldEvaluation(
        candidate_id=candidate_id,
        asset_id=AssetId(asset),
        horizon=horizon,
        regime=regime,
        fold_id=f"fold-{fold_number}",
        split_sha256=digest(f"split-{prefix}"),
        model_capability_sha256=capability_sha256(resolved_capability),
        dataset_manifest_sha256=digest(f"dataset-{asset}-{horizon.value}-{regime.value}"),
        calibration_artifact_sha256=digest(f"calibration-{prefix}"),
        prediction_artifact_sha256=digest(f"prediction-{candidate_id}-{prefix}"),
        training_end=instant(1 + offset),
        calibration_end=instant(2 + offset),
        test_start=instant(3 + offset),
        test_end=instant(4 + offset),
        evaluation_available_at=instant(5 + offset),
        training_sample_ids=(f"{prefix}-train-1", f"{prefix}-train-2"),
        calibration_sample_ids=(f"{prefix}-cal-1", f"{prefix}-cal-2"),
        test_sample_ids=(f"{prefix}-test-1", f"{prefix}-test-2"),
        prediction_mode=mode or resolved_capability.prediction_modes[0],
        state=state,
        metrics=metrics(loss) if state is FoldEvaluationState.EVALUATED else None,
        abstain_or_failure_reason=(
            None
            if state is FoldEvaluationState.EVALUATED
            else failure_reason or "SIMULATED_FAILURE"
        ),
        final_holdout_opened=False,
    )
