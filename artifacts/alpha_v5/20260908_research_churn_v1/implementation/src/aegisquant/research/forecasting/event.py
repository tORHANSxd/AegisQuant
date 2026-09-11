"""Truth-aware event counterfactual contracts for V5-P08 research."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.identifiers import AssetId, InstrumentId
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    UnitInterval,
    canonical_result,
)
from aegisquant.intelligence.canonical_events import (
    CanonicalEvent,
    EventDirectionalGate,
    build_event_directional_gate,
)
from aegisquant.research.forecasting.contracts import (
    CalibrationArtifact,
    CouncilHorizon,
    FoldEvaluationState,
    ForecastEnvelope,
    ForecastMetrics,
    MarketRegime,
    MarketStateTensor,
    ModelCapability,
    bind_forecast_inputs,
)

REQUIRED_EVENT_FORECAST_MARKET_FEATURES = frozenset(
    {
        "return_1m",
        "realized_volatility",
        "spread_bps",
        "depth",
        "funding",
        "basis",
        "open_interest",
        "liquidations",
        "cross_asset_return",
    }
)


class TruthAwareEventFeatures(DomainModel):
    """Decision-time event features derived from one canonical event revision."""

    event_type: str = Field(min_length=1)
    event_stage: EventClusterStatus
    entity_ids: Annotated[tuple[str, ...], Field(min_length=1)]
    affected_assets: Annotated[tuple[str, ...], Field(min_length=1)]
    truth_probability_at_t: UnitInterval
    source_quality_at_t: UnitInterval
    independent_evidence_count: int = Field(ge=0)
    evidence_dependency_score: UnitInterval
    contradiction_probability: UnitInterval
    manipulation_probability: UnitInterval
    novelty_at_t: UnitInterval
    severity_at_t: UnitInterval
    persistence_at_t: UnitInterval
    market_reflection_at_t: UnitInterval | None
    actual_at_t: FiniteDecimal | None
    expected_at_t: FiniteDecimal | None
    surprise_at_t: FiniteDecimal | None
    narrative_propagation_stage: str = Field(min_length=1)
    narrative_independent_source_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_features(self) -> Self:
        for values in (self.entity_ids, self.affected_assets):
            if values != tuple(sorted(set(values))) or any(not value.strip() for value in values):
                raise ValueError("event feature identities must be sorted, unique, and non-blank")
        event_values = (self.actual_at_t, self.expected_at_t, self.surprise_at_t)
        if any(value is None for value in event_values) and any(
            value is not None for value in event_values
        ):
            raise ValueError("event actual, expected, and surprise must be present together")
        if (
            self.actual_at_t is not None
            and self.expected_at_t is not None
            and self.surprise_at_t != canonical_result(self.actual_at_t - self.expected_at_t)
        ):
            raise ValueError("AQ-EVENT-FORECAST-SURPRISE-MISMATCH")
        return self


def _event_features(event: CanonicalEvent) -> TruthAwareEventFeatures:
    truth = event.truth_assessment
    return TruthAwareEventFeatures(
        event_type=event.event_type,
        event_stage=event.event_stage,
        entity_ids=event.entities,
        affected_assets=event.affected_assets,
        truth_probability_at_t=truth.claim_truth_probability,
        source_quality_at_t=min(
            truth.source_identity_probability,
            truth.content_integrity_probability,
            truth.evidence_independence_probability,
        ),
        independent_evidence_count=truth.independent_evidence_count,
        evidence_dependency_score=truth.evidence_dependency_score,
        contradiction_probability=truth.contradiction_probability,
        manipulation_probability=truth.manipulation_probability,
        novelty_at_t=event.novelty,
        severity_at_t=event.severity,
        persistence_at_t=event.persistence,
        market_reflection_at_t=event.market_reflection.market_reflection_score,
        actual_at_t=event.actual_value,
        expected_at_t=event.expected_value,
        surprise_at_t=event.surprise_value,
        narrative_propagation_stage=event.narrative_diffusion.propagation_stage.value,
        narrative_independent_source_count=event.narrative_diffusion.independent_source_count,
    )


class EventConditionSnapshot(DomainModel):
    """Content-addressed event and truth state visible at one forecast decision."""

    canonical_event: CanonicalEvent
    directional_gate: EventDirectionalGate
    features: TruthAwareEventFeatures
    instrument_id: InstrumentId
    asset_id: AssetId
    decision_time: UtcDateTime
    asset_relationship_score: UnitInterval
    relationship_snapshot_sha256: str
    directional_candidate_allowed: bool
    risk_overlay_only: bool
    fixed_horizon_scale_used: Literal[False] = False
    snapshot_sha256: str

    @field_validator("relationship_snapshot_sha256", "snapshot_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event condition lineage hash")

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        event = CanonicalEvent.model_validate_json(self.canonical_event.model_dump_json())
        gate = EventDirectionalGate.model_validate_json(self.directional_gate.model_dump_json())
        if event.available_at > self.decision_time:
            raise ValueError("AQ-EVENT-FORECAST-EVENT-LOOKAHEAD")
        if (
            event.truth_assessment.available_at > self.decision_time
            or event.narrative_diffusion.as_of_time > self.decision_time
            or event.market_reflection.as_of_time > self.decision_time
        ):
            raise ValueError("AQ-EVENT-FORECAST-CONTEXT-LOOKAHEAD")
        expected_gate = build_event_directional_gate(event=event, as_of_time=self.decision_time)
        if gate != expected_gate:
            raise ValueError("AQ-EVENT-FORECAST-DIRECTIONAL-GATE-MISMATCH")
        if self.features != _event_features(event):
            raise ValueError("AQ-EVENT-FORECAST-FEATURE-BINDING-MISMATCH")
        asset_names = {str(self.asset_id), f"asset:{self.asset_id}"}
        if not asset_names.intersection(set(event.affected_assets) | set(event.entities)):
            raise ValueError("AQ-EVENT-FORECAST-ASSET-RELATIONSHIP-MISSING")
        if self.asset_relationship_score <= 0:
            raise ValueError("event-conditioned forecast requires a positive asset relationship")
        if (
            self.directional_candidate_allowed != gate.directional_candidate_allowed
            or self.risk_overlay_only == gate.directional_candidate_allowed
        ):
            raise ValueError("AQ-EVENT-FORECAST-GATE-STATE-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_sha256"}))
        if self.snapshot_sha256 != expected_hash:
            raise ValueError("AQ-EVENT-FORECAST-SNAPSHOT-HASH-MISMATCH")
        return self


def create_event_condition_snapshot(
    *,
    canonical_event: CanonicalEvent,
    instrument_id: InstrumentId,
    asset_id: AssetId,
    decision_time: UtcDateTime,
    asset_relationship_score: Decimal,
    relationship_snapshot_sha256: str,
) -> EventConditionSnapshot:
    """Bind one canonical event revision and its gate to decision-time features."""

    event = CanonicalEvent.model_validate_json(canonical_event.model_dump_json())
    gate = build_event_directional_gate(event=event, as_of_time=decision_time)
    data = {
        "canonical_event": event,
        "directional_gate": gate,
        "features": _event_features(event),
        "instrument_id": instrument_id,
        "asset_id": asset_id,
        "decision_time": decision_time,
        "asset_relationship_score": asset_relationship_score,
        "relationship_snapshot_sha256": relationship_snapshot_sha256,
        "directional_candidate_allowed": gate.directional_candidate_allowed,
        "risk_overlay_only": not gate.directional_candidate_allowed,
        "fixed_horizon_scale_used": False,
    }
    candidate = EventConditionSnapshot.model_construct(
        canonical_event=event,
        directional_gate=gate,
        features=_event_features(event),
        instrument_id=instrument_id,
        asset_id=asset_id,
        decision_time=decision_time,
        asset_relationship_score=asset_relationship_score,
        relationship_snapshot_sha256=relationship_snapshot_sha256,
        directional_candidate_allowed=gate.directional_candidate_allowed,
        risk_overlay_only=not gate.directional_candidate_allowed,
        fixed_horizon_scale_used=False,
        snapshot_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"snapshot_sha256"}))
    return EventConditionSnapshot.model_validate({**data, "snapshot_sha256": digest})


class ForecastInputBinding(DomainModel):
    """A self-validating P07 forecast with all referenced input objects."""

    forecast: ForecastEnvelope
    market_state_tensor: MarketStateTensor
    calibrations: Annotated[tuple[CalibrationArtifact, ...], Field(min_length=1)]
    capability: ModelCapability
    binding_sha256: str

    @field_validator("binding_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="bound forecast input hash")

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        bind_forecast_inputs(
            forecast=self.forecast,
            tensor=self.market_state_tensor,
            calibrations=self.calibrations,
            capability=self.capability,
        )
        if tuple(item.horizon for item in self.calibrations) != tuple(
            sorted((item.horizon for item in self.calibrations), key=lambda item: item.value)
        ):
            raise ValueError("forecast input calibrations must be ordered by horizon")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected_hash:
            raise ValueError("AQ-EVENT-FORECAST-INPUT-BINDING-HASH-MISMATCH")
        return self


def create_forecast_input_binding(
    *,
    forecast: ForecastEnvelope,
    market_state_tensor: MarketStateTensor,
    calibrations: tuple[CalibrationArtifact, ...],
    capability: ModelCapability,
) -> ForecastInputBinding:
    ordered_calibrations = tuple(sorted(calibrations, key=lambda item: item.horizon.value))
    data = {
        "forecast": forecast,
        "market_state_tensor": market_state_tensor,
        "calibrations": ordered_calibrations,
        "capability": capability,
    }
    candidate = ForecastInputBinding.model_construct(
        forecast=forecast,
        market_state_tensor=market_state_tensor,
        calibrations=ordered_calibrations,
        capability=capability,
        binding_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"binding_sha256"}))
    return ForecastInputBinding.model_validate({**data, "binding_sha256": digest})


class EventForecastComparisonLineage(DomainModel):
    """Exact OOS sample, split, and budget identity shared by every ablation arm."""

    asset_id: AssetId
    instrument_id: InstrumentId
    horizon: CouncilHorizon
    regime: MarketRegime
    fold_id: str = Field(min_length=1)
    split_sha256: str
    label_dataset_manifest_sha256: str
    resource_budget_sha256: str
    decision_time: UtcDateTime
    training_end: UtcDateTime
    calibration_end: UtcDateTime
    test_start: UtcDateTime
    test_end: UtcDateTime
    evaluation_available_at: UtcDateTime
    purge_seconds: int = Field(ge=1)
    embargo_seconds: int = Field(ge=1)
    training_sample_ids: Annotated[tuple[str, ...], Field(min_length=2)]
    calibration_sample_ids: Annotated[tuple[str, ...], Field(min_length=2)]
    test_sample_ids: Annotated[tuple[str, ...], Field(min_length=2)]
    final_holdout_opened: Literal[False] = False
    lineage_sha256: str

    @field_validator(
        "split_sha256",
        "label_dataset_manifest_sha256",
        "resource_budget_sha256",
        "lineage_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event forecast comparison lineage hash")

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        if not (
            self.training_end
            < self.calibration_end
            < self.test_start
            <= self.decision_time
            <= self.test_end
            <= self.evaluation_available_at
        ):
            raise ValueError("AQ-EVENT-FORECAST-COMPARISON-TIME-LEAKAGE")
        gap_seconds = (self.test_start - self.calibration_end).total_seconds()
        if gap_seconds < self.purge_seconds + self.embargo_seconds:
            raise ValueError("AQ-EVENT-FORECAST-PURGE-EMBARGO-VIOLATION")
        groups = (
            self.training_sample_ids,
            self.calibration_sample_ids,
            self.test_sample_ids,
        )
        if any(
            values != tuple(sorted(set(values))) or any(not value.strip() for value in values)
            for values in groups
        ):
            raise ValueError("event forecast sample ids must be sorted and unique")
        if (
            set(self.training_sample_ids) & set(self.calibration_sample_ids)
            or set(self.training_sample_ids) & set(self.test_sample_ids)
            or set(self.calibration_sample_ids) & set(self.test_sample_ids)
        ):
            raise ValueError("AQ-EVENT-FORECAST-COMPARISON-SAMPLE-LEAKAGE")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"lineage_sha256"}))
        if self.lineage_sha256 != expected_hash:
            raise ValueError("AQ-EVENT-FORECAST-COMPARISON-HASH-MISMATCH")
        return self


def create_event_forecast_comparison_lineage(
    *,
    asset_id: AssetId,
    instrument_id: InstrumentId,
    horizon: CouncilHorizon,
    regime: MarketRegime,
    fold_id: str,
    split_sha256: str,
    label_dataset_manifest_sha256: str,
    resource_budget_sha256: str,
    decision_time: UtcDateTime,
    training_end: UtcDateTime,
    calibration_end: UtcDateTime,
    test_start: UtcDateTime,
    test_end: UtcDateTime,
    evaluation_available_at: UtcDateTime,
    purge_seconds: int,
    embargo_seconds: int,
    training_sample_ids: tuple[str, ...],
    calibration_sample_ids: tuple[str, ...],
    test_sample_ids: tuple[str, ...],
) -> EventForecastComparisonLineage:
    ordered_training_ids = tuple(sorted(training_sample_ids))
    ordered_calibration_ids = tuple(sorted(calibration_sample_ids))
    ordered_test_ids = tuple(sorted(test_sample_ids))
    data = {
        "asset_id": asset_id,
        "instrument_id": instrument_id,
        "horizon": horizon,
        "regime": regime,
        "fold_id": fold_id,
        "split_sha256": split_sha256,
        "label_dataset_manifest_sha256": label_dataset_manifest_sha256,
        "resource_budget_sha256": resource_budget_sha256,
        "decision_time": decision_time,
        "training_end": training_end,
        "calibration_end": calibration_end,
        "test_start": test_start,
        "test_end": test_end,
        "evaluation_available_at": evaluation_available_at,
        "purge_seconds": purge_seconds,
        "embargo_seconds": embargo_seconds,
        "training_sample_ids": ordered_training_ids,
        "calibration_sample_ids": ordered_calibration_ids,
        "test_sample_ids": ordered_test_ids,
        "final_holdout_opened": False,
    }
    candidate = EventForecastComparisonLineage.model_construct(
        asset_id=asset_id,
        instrument_id=instrument_id,
        horizon=horizon,
        regime=regime,
        fold_id=fold_id,
        split_sha256=split_sha256,
        label_dataset_manifest_sha256=label_dataset_manifest_sha256,
        resource_budget_sha256=resource_budget_sha256,
        decision_time=decision_time,
        training_end=training_end,
        calibration_end=calibration_end,
        test_start=test_start,
        test_end=test_end,
        evaluation_available_at=evaluation_available_at,
        purge_seconds=purge_seconds,
        embargo_seconds=embargo_seconds,
        training_sample_ids=ordered_training_ids,
        calibration_sample_ids=ordered_calibration_ids,
        test_sample_ids=ordered_test_ids,
        final_holdout_opened=False,
        lineage_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"lineage_sha256"}))
    return EventForecastComparisonLineage.model_validate({**data, "lineage_sha256": digest})


def _validate_forecast_cell(
    inputs: ForecastInputBinding,
    lineage: EventForecastComparisonLineage,
) -> None:
    validated_inputs = ForecastInputBinding.model_validate_json(inputs.model_dump_json())
    validated_lineage = EventForecastComparisonLineage.model_validate_json(
        lineage.model_dump_json()
    )
    forecast = validated_inputs.forecast
    if len(forecast.horizons) != 1 or forecast.horizons[0].horizon is not lineage.horizon:
        raise ValueError("AQ-EVENT-FORECAST-ONE-HORIZON-CELL-REQUIRED")
    if (
        forecast.asset_id != validated_lineage.asset_id
        or forecast.instrument_id != validated_lineage.instrument_id
        or forecast.regime is not validated_lineage.regime
        or forecast.as_of_time != validated_lineage.decision_time
    ):
        raise ValueError("AQ-EVENT-FORECAST-CELL-IDENTITY-MISMATCH")
    missing = REQUIRED_EVENT_FORECAST_MARKET_FEATURES.difference(
        validated_inputs.market_state_tensor.feature_names
    )
    if missing:
        raise ValueError(f"AQ-EVENT-FORECAST-MARKET-FEATURES-MISSING:{','.join(sorted(missing))}")
    calibration = validated_inputs.calibrations[0]
    if calibration.split_sha256 != validated_lineage.split_sha256:
        raise ValueError("AQ-EVENT-FORECAST-CALIBRATION-SPLIT-MISMATCH")
    if set(calibration.forbidden_test_sample_ids) != set(validated_lineage.test_sample_ids):
        raise ValueError("AQ-EVENT-FORECAST-CALIBRATION-TEST-BINDING-MISMATCH")


class MarketOnlyForecast(DomainModel):
    inputs: ForecastInputBinding
    lineage: EventForecastComparisonLineage
    conditioning: Literal["MARKET_ONLY"] = "MARKET_ONLY"
    event_features_used: Literal[False] = False
    fixed_horizon_scale_used: Literal[False] = False
    artifact_sha256: str
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    alpha_promotion_eligible: Literal[False] = False

    @field_validator("artifact_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="market-only forecast artifact hash")

    @model_validator(mode="after")
    def validate_forecast(self) -> Self:
        _validate_forecast_cell(self.inputs, self.lineage)
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("AQ-EVENT-FORECAST-MARKET-ONLY-HASH-MISMATCH")
        return self


def create_market_only_forecast(
    *, inputs: ForecastInputBinding, lineage: EventForecastComparisonLineage
) -> MarketOnlyForecast:
    data = {
        "inputs": inputs,
        "lineage": lineage,
        "conditioning": "MARKET_ONLY",
        "event_features_used": False,
        "fixed_horizon_scale_used": False,
    }
    candidate = MarketOnlyForecast.model_construct(
        inputs=inputs,
        lineage=lineage,
        conditioning="MARKET_ONLY",
        event_features_used=False,
        fixed_horizon_scale_used=False,
        artifact_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"artifact_sha256"}))
    return MarketOnlyForecast.model_validate({**data, "artifact_sha256": digest})


class EventConditionedForecast(DomainModel):
    inputs: ForecastInputBinding
    lineage: EventForecastComparisonLineage
    event_condition: EventConditionSnapshot
    conditioning: Literal["MARKET_AND_EVENT"] = "MARKET_AND_EVENT"
    event_features_used: Literal[True] = True
    fixed_horizon_scale_used: Literal[False] = False
    artifact_sha256: str
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    alpha_promotion_eligible: Literal[False] = False
    action: Literal["RESEARCH_PROPOSAL_ONLY"] = "RESEARCH_PROPOSAL_ONLY"
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True

    @field_validator("artifact_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event-conditioned forecast artifact hash")

    @model_validator(mode="after")
    def validate_forecast(self) -> Self:
        _validate_forecast_cell(self.inputs, self.lineage)
        condition = EventConditionSnapshot.model_validate_json(
            self.event_condition.model_dump_json()
        )
        forecast = self.inputs.forecast
        if (
            condition.asset_id != forecast.asset_id
            or condition.instrument_id != forecast.instrument_id
            or condition.decision_time != forecast.as_of_time
        ):
            raise ValueError("AQ-EVENT-FORECAST-CONDITION-IDENTITY-MISMATCH")
        if not condition.directional_candidate_allowed and not forecast.should_abstain:
            raise ValueError("AQ-EVENT-FORECAST-DIRECTIONAL-DENIAL-MUST-ABSTAIN")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("AQ-EVENT-FORECAST-CONDITIONED-HASH-MISMATCH")
        return self


def create_event_conditioned_forecast(
    *,
    inputs: ForecastInputBinding,
    lineage: EventForecastComparisonLineage,
    event_condition: EventConditionSnapshot,
) -> EventConditionedForecast:
    data = {
        "inputs": inputs,
        "lineage": lineage,
        "event_condition": event_condition,
        "conditioning": "MARKET_AND_EVENT",
        "event_features_used": True,
        "fixed_horizon_scale_used": False,
    }
    candidate = EventConditionedForecast.model_construct(
        inputs=inputs,
        lineage=lineage,
        event_condition=event_condition,
        conditioning="MARKET_AND_EVENT",
        event_features_used=True,
        fixed_horizon_scale_used=False,
        artifact_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"artifact_sha256"}))
    return EventConditionedForecast.model_validate({**data, "artifact_sha256": digest})


class ForecastQuantileDelta(DomainModel):
    q01: FiniteDecimal
    q05: FiniteDecimal
    q10: FiniteDecimal
    q25: FiniteDecimal
    q50: FiniteDecimal
    q75: FiniteDecimal
    q90: FiniteDecimal
    q95: FiniteDecimal
    q99: FiniteDecimal


class HorizonEventIncrement(DomainModel):
    horizon: CouncilHorizon
    delta_expected_return: FiniteDecimal
    delta_return_quantiles: ForecastQuantileDelta
    delta_up_probability: FiniteDecimal
    delta_realized_volatility: FiniteDecimal
    delta_tail_risk_probability: FiniteDecimal
    delta_liquidity: FiniteDecimal
    delta_spread: FiniteDecimal
    delta_slippage: FiniteDecimal
    delta_abstain_probability: FiniteDecimal


def _delta(event_value: Decimal, market_value: Decimal) -> Decimal:
    return canonical_result(event_value - market_value)


def _derive_increment(
    market_only: MarketOnlyForecast,
    event_conditioned: EventConditionedForecast,
) -> HorizonEventIncrement:
    market = market_only.inputs.forecast.horizons[0]
    event = event_conditioned.inputs.forecast.horizons[0]
    market_quantiles = market.return_distribution.quantiles
    event_quantiles = event.return_distribution.quantiles
    return HorizonEventIncrement(
        horizon=market.horizon,
        delta_expected_return=_delta(
            event.return_distribution.mean, market.return_distribution.mean
        ),
        delta_return_quantiles=ForecastQuantileDelta(
            **{
                name: _delta(getattr(event_quantiles, name), getattr(market_quantiles, name))
                for name in ("q01", "q05", "q10", "q25", "q50", "q75", "q90", "q95", "q99")
            }
        ),
        delta_up_probability=_delta(
            event.direction_probabilities.up, market.direction_probabilities.up
        ),
        delta_realized_volatility=_delta(
            event.realized_volatility_distribution.mean,
            market.realized_volatility_distribution.mean,
        ),
        delta_tail_risk_probability=_delta(
            event.tail_risk_probability, market.tail_risk_probability
        ),
        delta_liquidity=_delta(event.liquidity_forecast, market.liquidity_forecast),
        delta_spread=_delta(event.spread_forecast, market.spread_forecast),
        delta_slippage=_delta(event.slippage_forecast, market.slippage_forecast),
        delta_abstain_probability=_delta(event.abstain_probability, market.abstain_probability),
    )


def _validate_forecast_pair(
    market_only: MarketOnlyForecast,
    event_conditioned: EventConditionedForecast,
) -> None:
    market = MarketOnlyForecast.model_validate_json(market_only.model_dump_json())
    event = EventConditionedForecast.model_validate_json(event_conditioned.model_dump_json())
    if market.lineage != event.lineage:
        raise ValueError("AQ-EVENT-INCREMENT-LINEAGE-MISMATCH")
    if (
        market.inputs.market_state_tensor != event.inputs.market_state_tensor
        or market.inputs.calibrations != event.inputs.calibrations
        or market.inputs.capability != event.inputs.capability
    ):
        raise ValueError("AQ-EVENT-INCREMENT-INPUT-BINDING-MISMATCH")
    market_forecast = market.inputs.forecast
    event_forecast = event.inputs.forecast
    if (
        market_forecast.model_id != event_forecast.model_id
        or market_forecast.model_revision != event_forecast.model_revision
        or market_forecast.model_capability_sha256 != event_forecast.model_capability_sha256
        or market_forecast.prediction_mode is not event_forecast.prediction_mode
    ):
        raise ValueError("AQ-EVENT-INCREMENT-MODEL-MISMATCH")
    if event.event_condition.snapshot_sha256 == market.artifact_sha256:
        raise ValueError("AQ-EVENT-INCREMENT-ARTIFACT-IDENTITY-COLLISION")


class EventIncrement(DomainModel):
    market_only: MarketOnlyForecast
    event_conditioned: EventConditionedForecast
    by_horizon: HorizonEventIncrement
    increment_sha256: str
    counterfactual_kind: Literal["MARKET_ONLY_VS_MARKET_AND_EVENT"] = (
        "MARKET_ONLY_VS_MARKET_AND_EVENT"
    )
    causal_effect_claimed: Literal[False] = False
    real_world_increment_claimed: Literal[False] = False
    alpha_promotion_eligible: Literal[False] = False

    @field_validator("increment_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event increment hash")

    @model_validator(mode="after")
    def validate_increment(self) -> Self:
        _validate_forecast_pair(self.market_only, self.event_conditioned)
        if self.by_horizon != _derive_increment(self.market_only, self.event_conditioned):
            raise ValueError("AQ-EVENT-INCREMENT-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"increment_sha256"}))
        if self.increment_sha256 != expected_hash:
            raise ValueError("AQ-EVENT-INCREMENT-HASH-MISMATCH")
        return self


def compute_event_increment(
    *,
    market_only: MarketOnlyForecast,
    event_conditioned: EventConditionedForecast,
) -> EventIncrement:
    _validate_forecast_pair(market_only, event_conditioned)
    by_horizon = _derive_increment(market_only, event_conditioned)
    data = {
        "market_only": market_only,
        "event_conditioned": event_conditioned,
        "by_horizon": by_horizon,
        "counterfactual_kind": "MARKET_ONLY_VS_MARKET_AND_EVENT",
        "causal_effect_claimed": False,
        "real_world_increment_claimed": False,
        "alpha_promotion_eligible": False,
    }
    candidate = EventIncrement.model_construct(
        market_only=market_only,
        event_conditioned=event_conditioned,
        by_horizon=by_horizon,
        counterfactual_kind="MARKET_ONLY_VS_MARKET_AND_EVENT",
        causal_effect_claimed=False,
        real_world_increment_claimed=False,
        alpha_promotion_eligible=False,
        increment_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"increment_sha256"}))
    return EventIncrement.model_validate({**data, "increment_sha256": digest})


class EventAblationArm(StrEnum):
    MARKET_ONLY = "MARKET_ONLY"
    EVENT_ONLY = "EVENT_ONLY"
    MARKET_EVENT = "MARKET_EVENT"
    RISK_ONLY = "RISK_ONLY"
    TRUTH_PERMUTED = "TRUTH_PERMUTED"
    EVENT_PERMUTED = "EVENT_PERMUTED"
    TEXT_PERMUTED = "TEXT_PERMUTED"
    TIMESTAMP_PLACEBO = "TIMESTAMP_PLACEBO"
    ASSET_PLACEBO = "ASSET_PLACEBO"


REQUIRED_EVENT_ABLATION_ARMS = tuple(EventAblationArm)
PERMUTED_EVENT_ABLATION_ARMS = frozenset(
    {
        EventAblationArm.TRUTH_PERMUTED,
        EventAblationArm.EVENT_PERMUTED,
        EventAblationArm.TEXT_PERMUTED,
        EventAblationArm.TIMESTAMP_PLACEBO,
        EventAblationArm.ASSET_PLACEBO,
    }
)


class EventAblationEvaluation(DomainModel):
    arm: EventAblationArm
    lineage: EventForecastComparisonLineage
    event_condition_snapshot_sha256: str | None
    permutation_plan_sha256: str | None
    prediction_artifact_sha256: str
    state: FoldEvaluationState
    metrics: ForecastMetrics | None = None
    abstain_or_failure_reason: str | None = None
    evaluation_sha256: str
    final_holdout_opened: Literal[False] = False

    @field_validator(
        "event_condition_snapshot_sha256",
        "permutation_plan_sha256",
        "prediction_artifact_sha256",
        "evaluation_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name="event ablation lineage hash")

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        if self.arm is EventAblationArm.MARKET_ONLY:
            if self.event_condition_snapshot_sha256 is not None:
                raise ValueError("market-only ablation cannot consume event features")
        elif self.event_condition_snapshot_sha256 is None:
            raise ValueError("event ablation arm requires an event snapshot binding")
        requires_permutation = self.arm in PERMUTED_EVENT_ABLATION_ARMS
        if requires_permutation != (self.permutation_plan_sha256 is not None):
            raise ValueError("AQ-EVENT-ABLATION-PERMUTATION-PLAN-MISMATCH")
        if self.state is FoldEvaluationState.EVALUATED:
            if self.metrics is None or self.abstain_or_failure_reason is not None:
                raise ValueError("evaluated event ablation requires metrics and no failure reason")
        elif self.metrics is not None or not self.abstain_or_failure_reason:
            raise ValueError("failed event ablation requires one reason and no metrics")
        expected_hash = canonical_sha256(
            self.model_dump(mode="json", exclude={"evaluation_sha256"})
        )
        if self.evaluation_sha256 != expected_hash:
            raise ValueError("AQ-EVENT-ABLATION-EVALUATION-HASH-MISMATCH")
        return self


def create_event_ablation_evaluation(
    *,
    arm: EventAblationArm,
    lineage: EventForecastComparisonLineage,
    event_condition_snapshot_sha256: str | None,
    permutation_plan_sha256: str | None,
    prediction_artifact_sha256: str,
    state: FoldEvaluationState,
    metrics: ForecastMetrics | None,
    abstain_or_failure_reason: str | None,
) -> EventAblationEvaluation:
    data = {
        "arm": arm,
        "lineage": lineage,
        "event_condition_snapshot_sha256": event_condition_snapshot_sha256,
        "permutation_plan_sha256": permutation_plan_sha256,
        "prediction_artifact_sha256": prediction_artifact_sha256,
        "state": state,
        "metrics": metrics,
        "abstain_or_failure_reason": abstain_or_failure_reason,
        "final_holdout_opened": False,
    }
    candidate = EventAblationEvaluation.model_construct(
        arm=arm,
        lineage=lineage,
        event_condition_snapshot_sha256=event_condition_snapshot_sha256,
        permutation_plan_sha256=permutation_plan_sha256,
        prediction_artifact_sha256=prediction_artifact_sha256,
        state=state,
        metrics=metrics,
        abstain_or_failure_reason=abstain_or_failure_reason,
        evaluation_sha256="0" * 64,
        final_holdout_opened=False,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"evaluation_sha256"}))
    return EventAblationEvaluation.model_validate({**data, "evaluation_sha256": digest})


class EventAblationSpec(DomainModel):
    expected_fold_count: int = Field(ge=2)
    minimum_market_event_loss_improvement: NonNegativeDecimal
    minimum_permutation_loss_degradation: NonNegativeDecimal
    evaluation_cutoff: UtcDateTime
    required_arms: tuple[EventAblationArm, ...] = REQUIRED_EVENT_ABLATION_ARMS
    fixed_horizon_scale_allowed: Literal[False] = False
    final_holdout_opened: Literal[False] = False

    @model_validator(mode="after")
    def validate_spec(self) -> Self:
        if self.required_arms != REQUIRED_EVENT_ABLATION_ARMS:
            raise ValueError("event ablation requires the complete fixed arm set")
        return self


class HorizonEventAblationResult(DomainModel):
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    mean_primary_loss_by_arm: dict[EventAblationArm, NonNegativeDecimal]
    mean_net_return_after_cost_by_arm: dict[EventAblationArm, FiniteDecimal]
    failed_arms: tuple[EventAblationArm, ...]
    market_event_beats_market_only: bool
    truth_permutation_degrades: bool
    event_permutation_degrades: bool
    text_permutation_degrades: bool
    timestamp_placebo_degrades: bool
    asset_placebo_degrades: bool
    event_only_and_risk_only_reported: Literal[True] = True
    event_increment_gate_passed_in_fixture: bool
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    real_world_increment_claimed: Literal[False] = False
    alpha_promotion_eligible: Literal[False] = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.failed_arms != tuple(sorted(set(self.failed_arms), key=lambda item: item.value)):
            raise ValueError("event ablation failed arms must be sorted and unique")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("event ablation reasons must be sorted and unique")
        checks = (
            self.market_event_beats_market_only,
            self.truth_permutation_degrades,
            self.event_permutation_degrades,
            self.text_permutation_degrades,
            self.timestamp_placebo_degrades,
            self.asset_placebo_degrades,
            not self.failed_arms,
        )
        if self.event_increment_gate_passed_in_fixture != all(checks):
            raise ValueError("event ablation gate is inconsistent with component checks")
        return self


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _loss_degrades(
    losses: dict[EventAblationArm, Decimal],
    arm: EventAblationArm,
    minimum_degradation: Decimal,
) -> bool:
    market_event = losses.get(EventAblationArm.MARKET_EVENT)
    permuted = losses.get(arm)
    return (
        market_event is not None
        and permuted is not None
        and permuted - market_event >= minimum_degradation
    )


def _derive_ablation_results(
    *,
    spec: EventAblationSpec,
    event_condition: EventConditionSnapshot,
    evaluations: tuple[EventAblationEvaluation, ...],
) -> tuple[tuple[HorizonEventAblationResult, ...], tuple[CouncilHorizon, ...]]:
    validated = tuple(
        EventAblationEvaluation.model_validate_json(item.model_dump_json()) for item in evaluations
    )
    if len({item.evaluation_sha256 for item in validated}) != len(validated):
        raise ValueError("AQ-EVENT-ABLATION-DUPLICATE-EVALUATION")
    if len({item.prediction_artifact_sha256 for item in validated}) != len(validated):
        raise ValueError("AQ-EVENT-ABLATION-PREDICTION-REUSE")
    if any(item.lineage.evaluation_available_at > spec.evaluation_cutoff for item in validated):
        raise ValueError("AQ-EVENT-ABLATION-FUTURE-EVALUATION")
    if any(
        item.arm is not EventAblationArm.MARKET_ONLY
        and item.event_condition_snapshot_sha256 != event_condition.snapshot_sha256
        for item in validated
    ):
        raise ValueError("AQ-EVENT-ABLATION-EVENT-SNAPSHOT-MISMATCH")

    grouped: dict[tuple[AssetId, CouncilHorizon, MarketRegime], list[EventAblationEvaluation]] = {}
    for item in validated:
        key = (item.lineage.asset_id, item.lineage.horizon, item.lineage.regime)
        grouped.setdefault(key, []).append(item)
    results: list[HorizonEventAblationResult] = []
    for (asset_id, horizon, regime), cell in sorted(
        grouped.items(), key=lambda item: (str(item[0][0]), item[0][1].value, item[0][2].value)
    ):
        keyed = {(item.arm, item.lineage.fold_id): item for item in cell}
        if len(keyed) != len(cell):
            raise ValueError("AQ-EVENT-ABLATION-DUPLICATE-ARM-FOLD")
        fold_ids_by_arm = {
            arm: tuple(sorted(fold_id for candidate_arm, fold_id in keyed if candidate_arm is arm))
            for arm in spec.required_arms
        }
        expected_folds = next(iter(fold_ids_by_arm.values()), ())
        if len(expected_folds) != spec.expected_fold_count or any(
            folds != expected_folds for folds in fold_ids_by_arm.values()
        ):
            raise ValueError("AQ-EVENT-ABLATION-UNEQUAL-OOS-FOLDS")
        for fold_id in expected_folds:
            lineages = {keyed[(arm, fold_id)].lineage.lineage_sha256 for arm in spec.required_arms}
            if len(lineages) != 1:
                raise ValueError("AQ-EVENT-ABLATION-LINEAGE-SPLICE")

        failed_arms = tuple(
            sorted(
                {
                    arm
                    for arm in spec.required_arms
                    if any(
                        keyed[(arm, fold_id)].state is not FoldEvaluationState.EVALUATED
                        for fold_id in expected_folds
                    )
                },
                key=lambda item: item.value,
            )
        )
        primary_losses: dict[EventAblationArm, Decimal] = {}
        net_returns: dict[EventAblationArm, Decimal] = {}
        for arm in spec.required_arms:
            metrics = tuple(keyed[(arm, fold_id)].metrics for fold_id in expected_folds)
            if all(metric is not None for metric in metrics):
                concrete = tuple(metric for metric in metrics if metric is not None)
                primary_losses[arm] = _mean(tuple(metric.primary_loss for metric in concrete))
                net_returns[arm] = _mean(tuple(metric.net_return_after_cost for metric in concrete))
        market_loss = primary_losses.get(EventAblationArm.MARKET_ONLY)
        combined_loss = primary_losses.get(EventAblationArm.MARKET_EVENT)
        market_event_beats = (
            market_loss is not None
            and combined_loss is not None
            and market_loss - combined_loss >= spec.minimum_market_event_loss_improvement
        )
        truth_degrades = _loss_degrades(
            primary_losses,
            EventAblationArm.TRUTH_PERMUTED,
            spec.minimum_permutation_loss_degradation,
        )
        event_degrades = _loss_degrades(
            primary_losses,
            EventAblationArm.EVENT_PERMUTED,
            spec.minimum_permutation_loss_degradation,
        )
        text_degrades = _loss_degrades(
            primary_losses,
            EventAblationArm.TEXT_PERMUTED,
            spec.minimum_permutation_loss_degradation,
        )
        timestamp_degrades = _loss_degrades(
            primary_losses,
            EventAblationArm.TIMESTAMP_PLACEBO,
            spec.minimum_permutation_loss_degradation,
        )
        asset_degrades = _loss_degrades(
            primary_losses,
            EventAblationArm.ASSET_PLACEBO,
            spec.minimum_permutation_loss_degradation,
        )
        checks = (
            market_event_beats,
            truth_degrades,
            event_degrades,
            text_degrades,
            timestamp_degrades,
            asset_degrades,
            not failed_arms,
        )
        reasons: set[str] = set()
        if failed_arms:
            reasons.add("ABLATION_ARM_FAILURE")
        for passed, reason in (
            (market_event_beats, "NO_MARKET_EVENT_INCREMENT"),
            (truth_degrades, "TRUTH_PERMUTATION_NOT_DEGRADED"),
            (event_degrades, "EVENT_PERMUTATION_NOT_DEGRADED"),
            (text_degrades, "TEXT_PERMUTATION_NOT_DEGRADED"),
            (timestamp_degrades, "TIMESTAMP_PLACEBO_NOT_DEGRADED"),
            (asset_degrades, "ASSET_PLACEBO_NOT_DEGRADED"),
        ):
            if not passed:
                reasons.add(reason)
        if all(checks):
            reasons.add("EVENT_INCREMENT_FIXTURE_GATE_PASSED")
        results.append(
            HorizonEventAblationResult(
                asset_id=asset_id,
                horizon=horizon,
                regime=regime,
                mean_primary_loss_by_arm=primary_losses,
                mean_net_return_after_cost_by_arm=net_returns,
                failed_arms=failed_arms,
                market_event_beats_market_only=market_event_beats,
                truth_permutation_degrades=truth_degrades,
                event_permutation_degrades=event_degrades,
                text_permutation_degrades=text_degrades,
                timestamp_placebo_degrades=timestamp_degrades,
                asset_placebo_degrades=asset_degrades,
                event_only_and_risk_only_reported=True,
                event_increment_gate_passed_in_fixture=all(checks),
                reason_codes=tuple(sorted(reasons)),
                real_world_increment_claimed=False,
                alpha_promotion_eligible=False,
            )
        )
    supported = tuple(
        horizon
        for horizon in CouncilHorizon
        if any(item.horizon is horizon for item in results)
        and all(
            item.event_increment_gate_passed_in_fixture
            for item in results
            if item.horizon is horizon
        )
    )
    return tuple(results), supported


class EventForecastAblationReport(DomainModel):
    spec: EventAblationSpec
    event_condition: EventConditionSnapshot
    evaluations: Annotated[tuple[EventAblationEvaluation, ...], Field(min_length=1)]
    results: Annotated[tuple[HorizonEventAblationResult, ...], Field(min_length=1)]
    fixture_supported_horizons: tuple[CouncilHorizon, ...]
    same_oos_folds_and_samples: Literal[True] = True
    failures_preserved: Literal[True] = True
    market_event_vs_market_only_reported: Literal[True] = True
    truth_and_event_permutations_reported: Literal[True] = True
    event_increment_reported_by_horizon: Literal[True] = True
    cross_time_stability_claimed: Literal[False] = False
    cross_asset_stability_claimed: Literal[False] = False
    multiple_testing_passed: Literal[False] = False
    cost_stress_passed: Literal[False] = False
    real_world_event_increment_claimed: Literal[False] = False
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    alpha_promotion_eligible: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    report_sha256: str

    @field_validator("report_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="event ablation report hash")

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        expected_results, expected_horizons = _derive_ablation_results(
            spec=self.spec,
            event_condition=self.event_condition,
            evaluations=self.evaluations,
        )
        if self.results != expected_results or self.fixture_supported_horizons != expected_horizons:
            raise ValueError("AQ-EVENT-ABLATION-REPORT-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("AQ-EVENT-ABLATION-REPORT-HASH-MISMATCH")
        return self


def evaluate_event_forecast_ablation(
    *,
    spec: EventAblationSpec,
    event_condition: EventConditionSnapshot,
    evaluations: tuple[EventAblationEvaluation, ...],
) -> EventForecastAblationReport:
    validated_spec = EventAblationSpec.model_validate_json(spec.model_dump_json())
    validated_condition = EventConditionSnapshot.model_validate_json(
        event_condition.model_dump_json()
    )
    results, supported_horizons = _derive_ablation_results(
        spec=validated_spec,
        event_condition=validated_condition,
        evaluations=evaluations,
    )
    data = {
        "spec": validated_spec,
        "event_condition": validated_condition,
        "evaluations": evaluations,
        "results": results,
        "fixture_supported_horizons": supported_horizons,
        "same_oos_folds_and_samples": True,
        "failures_preserved": True,
        "market_event_vs_market_only_reported": True,
        "truth_and_event_permutations_reported": True,
        "event_increment_reported_by_horizon": True,
        "cross_time_stability_claimed": False,
        "cross_asset_stability_claimed": False,
        "multiple_testing_passed": False,
        "cost_stress_passed": False,
        "real_world_event_increment_claimed": False,
        "evidence_tier": EvidenceTier.DEVELOPMENT,
        "alpha_promotion_eligible": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
    }
    candidate = EventForecastAblationReport.model_construct(
        spec=validated_spec,
        event_condition=validated_condition,
        evaluations=evaluations,
        results=results,
        fixture_supported_horizons=supported_horizons,
        same_oos_folds_and_samples=True,
        failures_preserved=True,
        market_event_vs_market_only_reported=True,
        truth_and_event_permutations_reported=True,
        event_increment_reported_by_horizon=True,
        cross_time_stability_claimed=False,
        cross_asset_stability_claimed=False,
        multiple_testing_passed=False,
        cost_stress_passed=False,
        real_world_event_increment_claimed=False,
        evidence_tier=EvidenceTier.DEVELOPMENT,
        alpha_promotion_eligible=False,
        order_submission_enabled=False,
        live_trading_locked=True,
        report_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"report_sha256"}))
    return EventForecastAblationReport.model_validate({**data, "report_sha256": digest})
