"""Strict point-in-time contracts for Forecast Council 2.0 research."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.identifiers import ArtifactId, AssetId, InstrumentId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval
from aegisquant.research.budgets import ResourceBudget, ResourceRequest


class CouncilHorizon(StrEnum):
    FIVE_SECONDS = "5s"
    FIFTEEN_SECONDS = "15s"
    THIRTY_SECONDS = "30s"
    ONE_MINUTE = "1m"
    THREE_MINUTES = "3m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    TWELVE_HOURS = "12h"
    ONE_DAY = "1d"
    THREE_DAYS = "3d"
    SEVEN_DAYS = "7d"


class MarketRegime(StrEnum):
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    LOW_VOL_COMPRESSION = "LOW_VOL_COMPRESSION"
    VOL_EXPANSION = "VOL_EXPANSION"
    LIQUIDITY_CRISIS = "LIQUIDITY_CRISIS"
    NEWS_SHOCK = "NEWS_SHOCK"
    LIQUIDATION_CASCADE = "LIQUIDATION_CASCADE"
    FUNDING_DISLOCATION = "FUNDING_DISLOCATION"
    CORRELATION_BREAKDOWN = "CORRELATION_BREAKDOWN"
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    UNKNOWN = "UNKNOWN"
    OOD = "OOD"


class ForecastModelClass(StrEnum):
    BASELINE = "BASELINE"
    FOUNDATION = "FOUNDATION"
    SUPERVISED = "SUPERVISED"
    MICROSTRUCTURE = "MICROSTRUCTURE"
    VISION = "VISION"


class ForecastModality(StrEnum):
    NUMERIC_ONLY = "NUMERIC_ONLY"
    VISION_ONLY = "VISION_ONLY"
    NUMERIC_VISION = "NUMERIC_VISION"


class PredictionMode(StrEnum):
    BASELINE = "BASELINE"
    TRAINED = "TRAINED"
    ZERO_SHOT = "ZERO_SHOT"


class CapabilityStatus(StrEnum):
    RUNNABLE_LOCAL = "RUNNABLE_LOCAL"
    ADAPTER_ONLY = "ADAPTER_ONLY"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    LICENSE_BLOCKED = "LICENSE_BLOCKED"
    OPTIONAL = "OPTIONAL"


class LicenseStatus(StrEnum):
    PROJECT_OWNED = "PROJECT_OWNED"
    VERIFIED_PERMISSIVE = "VERIFIED_PERMISSIVE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    UNVERIFIED = "UNVERIFIED"
    PROHIBITED = "PROHIBITED"


class FoldEvaluationState(StrEnum):
    EVALUATED = "EVALUATED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"


class CalibrationMethod(StrEnum):
    PLATT_LOGISTIC = "PLATT_LOGISTIC"
    ISOTONIC = "ISOTONIC"
    TEMPERATURE = "TEMPERATURE"
    BETA = "BETA"
    ADAPTIVE_CONFORMAL = "ADAPTIVE_CONFORMAL"
    DISTRIBUTION_AWARE_CONFORMAL = "DISTRIBUTION_AWARE_CONFORMAL"
    ROLLING_QUANTILE = "ROLLING_QUANTILE"


class MarketStateTensor(DomainModel):
    """One content-addressed market window containing only decision-time data."""

    tensor_id: ArtifactId
    instrument_id: InstrumentId
    asset_id: AssetId
    window_start: UtcDateTime
    decision_time: UtcDateTime
    observed_at: Annotated[tuple[UtcDateTime, ...], Field(min_length=3)]
    available_at: Annotated[tuple[UtcDateTime, ...], Field(min_length=3)]
    feature_names: Annotated[tuple[str, ...], Field(min_length=1)]
    values: Annotated[tuple[tuple[FiniteDecimal | None, ...], ...], Field(min_length=3)]
    source_dataset_ids: Annotated[tuple[str, ...], Field(min_length=1)]
    dataset_manifest_sha256: str
    feature_snapshot_sha256: str
    tensor_sha256: str

    @field_validator("dataset_manifest_sha256", "feature_snapshot_sha256", "tensor_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forecast tensor lineage hash")

    @model_validator(mode="after")
    def validate_tensor(self) -> Self:
        if len(set(self.feature_names)) != len(self.feature_names) or any(
            not name.strip() for name in self.feature_names
        ):
            raise ValueError("market tensor feature names must be non-blank and unique")
        if (
            self.source_dataset_ids != tuple(sorted(self.source_dataset_ids))
            or len(set(self.source_dataset_ids)) != len(self.source_dataset_ids)
            or any(not item.strip() for item in self.source_dataset_ids)
        ):
            raise ValueError("market tensor source dataset ids must be sorted and unique")
        row_count = len(self.observed_at)
        if len(self.available_at) != row_count or len(self.values) != row_count:
            raise ValueError("market tensor time and value dimensions differ")
        if any(len(row) != len(self.feature_names) for row in self.values):
            raise ValueError("market tensor values must be rectangular")
        if (
            len(set(self.observed_at)) != row_count
            or tuple(sorted(self.observed_at)) != self.observed_at
        ):
            raise ValueError("market tensor observations must be unique and ordered")
        if self.window_start > self.observed_at[0]:
            raise ValueError("market tensor window starts after its first observation")
        for observed, available in zip(self.observed_at, self.available_at, strict=True):
            if observed > available:
                raise ValueError("market tensor data cannot be available before observation")
            if available > self.decision_time:
                raise ValueError("AQ-FORECAST-MARKET-TENSOR-LOOKAHEAD")
        for column in range(len(self.feature_names)):
            if all(row[column] is None for row in self.values):
                raise ValueError("market tensor cannot contain an entirely missing feature")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"tensor_sha256"}))
        if self.tensor_sha256 != expected_hash:
            raise ValueError("AQ-FORECAST-MARKET-TENSOR-HASH-MISMATCH")
        return self


def create_market_state_tensor(
    *,
    tensor_id: ArtifactId,
    instrument_id: InstrumentId,
    asset_id: AssetId,
    window_start: UtcDateTime,
    decision_time: UtcDateTime,
    observed_at: tuple[UtcDateTime, ...],
    available_at: tuple[UtcDateTime, ...],
    feature_names: tuple[str, ...],
    values: tuple[tuple[Decimal | None, ...], ...],
    source_dataset_ids: tuple[str, ...],
    dataset_manifest_sha256: str,
    feature_snapshot_sha256: str,
) -> MarketStateTensor:
    """Create a tensor whose digest is computed from its validated semantic fields."""

    data = {
        "tensor_id": tensor_id,
        "instrument_id": instrument_id,
        "asset_id": asset_id,
        "window_start": window_start,
        "decision_time": decision_time,
        "observed_at": observed_at,
        "available_at": available_at,
        "feature_names": feature_names,
        "values": values,
        "source_dataset_ids": source_dataset_ids,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "feature_snapshot_sha256": feature_snapshot_sha256,
    }
    candidate = MarketStateTensor.model_construct(
        tensor_id=tensor_id,
        instrument_id=instrument_id,
        asset_id=asset_id,
        window_start=window_start,
        decision_time=decision_time,
        observed_at=observed_at,
        available_at=available_at,
        feature_names=feature_names,
        values=values,
        source_dataset_ids=source_dataset_ids,
        dataset_manifest_sha256=dataset_manifest_sha256,
        feature_snapshot_sha256=feature_snapshot_sha256,
        tensor_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"tensor_sha256"}))
    return MarketStateTensor.model_validate({**data, "tensor_sha256": digest})


def validate_market_state_tensor(tensor: MarketStateTensor) -> MarketStateTensor:
    """Revalidate copied/untrusted model objects at a computation boundary."""

    return MarketStateTensor.model_validate_json(tensor.model_dump_json())


class ForecastQuantiles(DomainModel):
    q01: FiniteDecimal
    q05: FiniteDecimal
    q10: FiniteDecimal
    q25: FiniteDecimal
    q50: FiniteDecimal
    q75: FiniteDecimal
    q90: FiniteDecimal
    q95: FiniteDecimal
    q99: FiniteDecimal

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        values = (
            self.q01,
            self.q05,
            self.q10,
            self.q25,
            self.q50,
            self.q75,
            self.q90,
            self.q95,
            self.q99,
        )
        if values != tuple(sorted(values)):
            raise ValueError("forecast quantiles must be ordered")
        return self


class ForecastDistributionV2(DomainModel):
    mean: FiniteDecimal
    standard_deviation: NonNegativeDecimal
    quantiles: ForecastQuantiles

    @model_validator(mode="after")
    def validate_mean_support(self) -> Self:
        if not self.quantiles.q01 <= self.mean <= self.quantiles.q99:
            raise ValueError("forecast mean must lie inside q01/q99")
        return self


class DirectionProbabilitiesV2(DomainModel):
    up: UnitInterval
    flat: UnitInterval
    down: UnitInterval

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.up + self.flat + self.down != Decimal("1"):
            raise ValueError("direction probabilities must sum exactly to one")
        return self


class BarrierHitProbabilities(DomainModel):
    upside: UnitInterval
    downside: UnitInterval


class ForecastUncertaintyV2(DomainModel):
    epistemic: NonNegativeDecimal
    aleatoric: NonNegativeDecimal
    ensemble_disagreement: NonNegativeDecimal


class HorizonForecast(DomainModel):
    horizon: CouncilHorizon
    return_distribution: ForecastDistributionV2
    direction_probabilities: DirectionProbabilitiesV2
    realized_volatility_distribution: ForecastDistributionV2
    future_high_low_range: NonNegativeDecimal
    maximum_favorable_excursion: NonNegativeDecimal
    maximum_adverse_excursion: FiniteDecimal
    barrier_hit_probabilities: BarrierHitProbabilities
    tail_risk_probability: UnitInterval
    liquidity_forecast: NonNegativeDecimal
    spread_forecast: NonNegativeDecimal
    slippage_forecast: NonNegativeDecimal
    uncertainty: ForecastUncertaintyV2
    abstain_probability: UnitInterval

    @model_validator(mode="after")
    def validate_path_metrics(self) -> Self:
        if self.maximum_adverse_excursion > 0:
            raise ValueError("maximum adverse excursion must be non-positive")
        if self.realized_volatility_distribution.quantiles.q01 < 0:
            raise ValueError("realized volatility distribution cannot be negative")
        return self


class CalibrationArtifact(DomainModel):
    calibration_id: ArtifactId
    method: CalibrationMethod
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    training_cutoff: UtcDateTime
    fitted_at: UtcDateTime
    available_at: UtcDateTime
    calibration_sample_ids: Annotated[tuple[str, ...], Field(min_length=2)]
    forbidden_test_sample_ids: Annotated[tuple[str, ...], Field(min_length=1)]
    split_sha256: str
    artifact_sha256: str

    @field_validator("split_sha256", "artifact_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forecast calibration hash")

    @model_validator(mode="after")
    def validate_calibration(self) -> Self:
        if not self.training_cutoff <= self.fitted_at <= self.available_at:
            raise ValueError("calibration timestamps are not monotonic")
        if len(set(self.calibration_sample_ids)) != len(self.calibration_sample_ids):
            raise ValueError("calibration sample ids must be unique")
        if len(set(self.forbidden_test_sample_ids)) != len(self.forbidden_test_sample_ids):
            raise ValueError("calibration test sample ids must be unique")
        if set(self.calibration_sample_ids) & set(self.forbidden_test_sample_ids):
            raise ValueError("AQ-FORECAST-CALIBRATION-TEST-LEAKAGE")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("AQ-FORECAST-CALIBRATION-HASH-MISMATCH")
        return self


def create_calibration_artifact(
    *,
    calibration_id: ArtifactId,
    method: CalibrationMethod,
    asset_id: AssetId,
    horizon: CouncilHorizon,
    regime: MarketRegime,
    training_cutoff: UtcDateTime,
    fitted_at: UtcDateTime,
    available_at: UtcDateTime,
    calibration_sample_ids: tuple[str, ...],
    forbidden_test_sample_ids: tuple[str, ...],
    split_sha256: str,
) -> CalibrationArtifact:
    data = {
        "calibration_id": calibration_id,
        "method": method,
        "asset_id": asset_id,
        "horizon": horizon,
        "regime": regime,
        "training_cutoff": training_cutoff,
        "fitted_at": fitted_at,
        "available_at": available_at,
        "calibration_sample_ids": calibration_sample_ids,
        "forbidden_test_sample_ids": forbidden_test_sample_ids,
        "split_sha256": split_sha256,
    }
    candidate = CalibrationArtifact.model_construct(
        calibration_id=calibration_id,
        method=method,
        asset_id=asset_id,
        horizon=horizon,
        regime=regime,
        training_cutoff=training_cutoff,
        fitted_at=fitted_at,
        available_at=available_at,
        calibration_sample_ids=calibration_sample_ids,
        forbidden_test_sample_ids=forbidden_test_sample_ids,
        split_sha256=split_sha256,
        artifact_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"artifact_sha256"}))
    return CalibrationArtifact.model_validate({**data, "artifact_sha256": digest})


class ForecastEnvelope(DomainModel):
    forecast_id: ArtifactId
    model_id: str
    model_revision: str
    model_capability_sha256: str
    market_state_tensor_sha256: str
    dataset_manifest_sha256: str
    calibration_artifact_sha256_by_horizon: dict[CouncilHorizon, str]
    instrument_id: InstrumentId
    asset_id: AssetId
    as_of_time: UtcDateTime
    regime: MarketRegime
    prediction_mode: PredictionMode
    horizons: Annotated[tuple[HorizonForecast, ...], Field(min_length=1)]
    should_abstain: bool
    abstain_reasons: tuple[str, ...]
    forecast_sha256: str
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    alpha_promotion_eligible: Literal[False] = False
    action: Literal["RESEARCH_PROPOSAL_ONLY"] = "RESEARCH_PROPOSAL_ONLY"
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True

    @field_validator(
        "model_capability_sha256",
        "market_state_tensor_sha256",
        "dataset_manifest_sha256",
        "forecast_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forecast envelope lineage hash")

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if not self.model_id.strip() or not self.model_revision.strip():
            raise ValueError("forecast model identity cannot be blank")
        horizons = tuple(item.horizon for item in self.horizons)
        if len(set(horizons)) != len(horizons):
            raise ValueError("forecast envelope horizons must be unique")
        if set(self.calibration_artifact_sha256_by_horizon) != set(horizons):
            raise ValueError("forecast envelope requires one calibration hash per horizon")
        for value in self.calibration_artifact_sha256_by_horizon.values():
            ensure_sha256(value, field_name="forecast calibration binding hash")
        if self.should_abstain != bool(self.abstain_reasons):
            raise ValueError("forecast abstention flag and reasons must agree")
        if self.abstain_reasons != tuple(sorted(set(self.abstain_reasons))):
            raise ValueError("forecast abstention reasons must be sorted and unique")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"forecast_sha256"}))
        if self.forecast_sha256 != expected_hash:
            raise ValueError("AQ-FORECAST-ENVELOPE-HASH-MISMATCH")
        return self


def create_forecast_envelope(
    *,
    forecast_id: ArtifactId,
    model_id: str,
    model_revision: str,
    model_capability_sha256: str,
    market_state_tensor_sha256: str,
    dataset_manifest_sha256: str,
    calibration_artifact_sha256_by_horizon: dict[CouncilHorizon, str],
    instrument_id: InstrumentId,
    asset_id: AssetId,
    as_of_time: UtcDateTime,
    regime: MarketRegime,
    prediction_mode: PredictionMode,
    horizons: tuple[HorizonForecast, ...],
    should_abstain: bool,
    abstain_reasons: tuple[str, ...],
) -> ForecastEnvelope:
    data = {
        "forecast_id": forecast_id,
        "model_id": model_id,
        "model_revision": model_revision,
        "model_capability_sha256": model_capability_sha256,
        "market_state_tensor_sha256": market_state_tensor_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "calibration_artifact_sha256_by_horizon": calibration_artifact_sha256_by_horizon,
        "instrument_id": instrument_id,
        "asset_id": asset_id,
        "as_of_time": as_of_time,
        "regime": regime,
        "prediction_mode": prediction_mode,
        "horizons": horizons,
        "should_abstain": should_abstain,
        "abstain_reasons": abstain_reasons,
    }
    candidate = ForecastEnvelope.model_construct(
        forecast_id=forecast_id,
        model_id=model_id,
        model_revision=model_revision,
        model_capability_sha256=model_capability_sha256,
        market_state_tensor_sha256=market_state_tensor_sha256,
        dataset_manifest_sha256=dataset_manifest_sha256,
        calibration_artifact_sha256_by_horizon=calibration_artifact_sha256_by_horizon,
        instrument_id=instrument_id,
        asset_id=asset_id,
        as_of_time=as_of_time,
        regime=regime,
        prediction_mode=prediction_mode,
        horizons=horizons,
        should_abstain=should_abstain,
        abstain_reasons=abstain_reasons,
        forecast_sha256="0" * 64,
    )
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={"forecast_sha256"}))
    return ForecastEnvelope.model_validate({**data, "forecast_sha256": digest})


class ModelCapability(DomainModel):
    candidate_id: str
    family: str
    model_class: ForecastModelClass
    modality: ForecastModality
    prediction_modes: Annotated[tuple[PredictionMode, ...], Field(min_length=1)]
    supported_horizons: Annotated[tuple[CouncilHorizon, ...], Field(min_length=1)]
    supported_regimes: Annotated[tuple[MarketRegime, ...], Field(min_length=1)]
    supports_return_distribution: bool
    supports_direction_probabilities: bool
    supports_volatility_distribution: bool
    supports_range_and_excursions: bool
    supports_barrier_and_tail: bool
    supports_liquidity_spread_slippage: bool
    supports_uncertainty_and_abstain: bool
    status: CapabilityStatus
    adapter_name: str
    model_revision: str
    code_license: str
    weights_license: str
    license_status: LicenseStatus
    weights_required: bool
    weight_sha256: str | None = None
    production_allowed: Literal[False] = False

    @field_validator("weight_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name="forecast candidate weight hash")

    @model_validator(mode="after")
    def validate_capability(self) -> Self:
        if any(
            not value.strip()
            for value in (
                self.candidate_id,
                self.family,
                self.adapter_name,
                self.model_revision,
                self.code_license,
                self.weights_license,
            )
        ):
            raise ValueError("forecast capability identity and license fields cannot be blank")
        for values, label in (
            (self.prediction_modes, "prediction modes"),
            (self.supported_horizons, "supported horizons"),
            (self.supported_regimes, "supported regimes"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"forecast capability {label} must be unique")
        if (PredictionMode.ZERO_SHOT in self.prediction_modes) != (
            self.model_class is ForecastModelClass.FOUNDATION
        ):
            raise ValueError("zero-shot mode is reserved for foundation candidates")
        if (
            self.weights_required
            and self.status is CapabilityStatus.RUNNABLE_LOCAL
            and self.weight_sha256 is None
        ):
            raise ValueError("runnable weighted candidate requires a verified weight hash")
        if self.status is CapabilityStatus.RUNNABLE_LOCAL:
            required_outputs = (
                self.supports_return_distribution,
                self.supports_direction_probabilities,
                self.supports_volatility_distribution,
                self.supports_range_and_excursions,
                self.supports_barrier_and_tail,
                self.supports_liquidity_spread_slippage,
                self.supports_uncertainty_and_abstain,
            )
            if not all(required_outputs):
                raise ValueError("runnable candidate must satisfy the complete forecast contract")
            if self.license_status in {LicenseStatus.UNVERIFIED, LicenseStatus.PROHIBITED}:
                raise ValueError("runnable candidate requires an approved research license")
        return self


REQUIRED_FOUNDATION_FAMILIES = frozenset({"TIMESFM_2_5", "CHRONOS_2", "MOIRAI_2", "TOTO_2_0"})


class CapabilityMatrix(DomainModel):
    as_of_time: UtcDateTime
    candidates: Annotated[tuple[ModelCapability, ...], Field(min_length=8)]
    vision_optional: Literal[True] = True
    no_single_universal_model_assumption: Literal[True] = True
    zero_shot_promotion_allowed: Literal[False] = False
    final_holdout_opened: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("forecast capability candidate ids must be unique")
        foundation_families = {
            item.family
            for item in self.candidates
            if item.model_class is ForecastModelClass.FOUNDATION
        }
        if not foundation_families >= REQUIRED_FOUNDATION_FAMILIES:
            raise ValueError("forecast capability matrix is missing a required foundation family")
        classes = {item.model_class for item in self.candidates}
        if (
            not {
                ForecastModelClass.BASELINE,
                ForecastModelClass.SUPERVISED,
                ForecastModelClass.MICROSTRUCTURE,
                ForecastModelClass.VISION,
            }
            <= classes
        ):
            raise ValueError("forecast capability matrix is missing a required model class")
        return self


def capability_sha256(capability: ModelCapability) -> str:
    validated = ModelCapability.model_validate_json(capability.model_dump_json())
    return canonical_sha256(validated.model_dump(mode="json"))


def capability_matrix_sha256(matrix: CapabilityMatrix) -> str:
    validated = CapabilityMatrix.model_validate_json(matrix.model_dump_json())
    return canonical_sha256(validated.model_dump(mode="json"))


class CandidateGateDecision(DomainModel):
    candidate_id: str
    capability_sha256: str
    budget_sha256: str
    request_sha256: str
    budget: ResourceBudget
    request: ResourceRequest
    dependency_available: bool
    weights_verified: bool
    allowed_to_evaluate: bool
    block_reasons: tuple[str, ...]
    restriction_codes: tuple[str, ...]
    alpha_promotion_eligible: Literal[False] = False

    @field_validator("capability_sha256", "budget_sha256", "request_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forecast candidate gate lineage hash")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.budget_sha256 != canonical_sha256(self.budget.model_dump(mode="json")):
            raise ValueError("AQ-FORECAST-GATE-BUDGET-HASH-MISMATCH")
        if self.request_sha256 != canonical_sha256(self.request.model_dump(mode="json")):
            raise ValueError("AQ-FORECAST-GATE-REQUEST-HASH-MISMATCH")
        if self.allowed_to_evaluate == bool(self.block_reasons):
            raise ValueError("candidate gate decision and block reasons disagree")
        if self.block_reasons != tuple(sorted(set(self.block_reasons))):
            raise ValueError("candidate gate block reasons must be sorted and unique")
        if self.restriction_codes != tuple(sorted(set(self.restriction_codes))):
            raise ValueError("candidate gate restrictions must be sorted and unique")
        return self


class ForecastMetrics(DomainModel):
    primary_loss: NonNegativeDecimal
    direction_accuracy: UnitInterval
    mean_absolute_error: NonNegativeDecimal
    root_mean_squared_error: NonNegativeDecimal
    crps: NonNegativeDecimal
    pinball_loss: NonNegativeDecimal
    brier_score: NonNegativeDecimal
    interval_coverage: UnitInterval
    tail_recall: UnitInterval
    net_return_after_cost: FiniteDecimal


class OosFoldEvaluation(DomainModel):
    candidate_id: str
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    fold_id: str
    split_sha256: str
    model_capability_sha256: str
    dataset_manifest_sha256: str
    calibration_artifact_sha256: str
    prediction_artifact_sha256: str
    training_end: UtcDateTime
    calibration_end: UtcDateTime
    test_start: UtcDateTime
    test_end: UtcDateTime
    evaluation_available_at: UtcDateTime
    training_sample_ids: Annotated[tuple[str, ...], Field(min_length=2)]
    calibration_sample_ids: Annotated[tuple[str, ...], Field(min_length=2)]
    test_sample_ids: Annotated[tuple[str, ...], Field(min_length=2)]
    prediction_mode: PredictionMode
    state: FoldEvaluationState
    metrics: ForecastMetrics | None = None
    abstain_or_failure_reason: str | None = None
    final_holdout_opened: Literal[False] = False

    @field_validator(
        "split_sha256",
        "model_capability_sha256",
        "dataset_manifest_sha256",
        "calibration_artifact_sha256",
        "prediction_artifact_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forecast OOS split hash")

    @model_validator(mode="after")
    def validate_fold(self) -> Self:
        if not self.candidate_id.strip() or not self.fold_id.strip():
            raise ValueError("forecast OOS candidate and fold ids cannot be blank")
        if not (
            self.training_end
            < self.calibration_end
            < self.test_start
            <= self.test_end
            <= self.evaluation_available_at
        ):
            raise ValueError("AQ-FORECAST-OOS-TIME-LEAKAGE")
        sample_groups = (
            self.training_sample_ids,
            self.calibration_sample_ids,
            self.test_sample_ids,
        )
        if any(len(set(values)) != len(values) for values in sample_groups):
            raise ValueError("forecast OOS sample ids must be unique within each partition")
        if (
            set(self.training_sample_ids) & set(self.calibration_sample_ids)
            or set(self.training_sample_ids) & set(self.test_sample_ids)
            or set(self.calibration_sample_ids) & set(self.test_sample_ids)
        ):
            raise ValueError("AQ-FORECAST-OOS-SAMPLE-LEAKAGE")
        if self.state is FoldEvaluationState.EVALUATED:
            if self.metrics is None or self.abstain_or_failure_reason is not None:
                raise ValueError("evaluated OOS fold requires metrics and no failure reason")
        elif self.metrics is not None or not self.abstain_or_failure_reason:
            raise ValueError("non-evaluated OOS fold requires one reason and no metrics")
        return self


class ModelArenaSpec(DomainModel):
    baseline_candidate_id: str
    expected_fold_count: int = Field(ge=2)
    minimum_absolute_improvement: NonNegativeDecimal
    evaluation_cutoff: UtcDateTime
    universal_model_assumption: Literal[False] = False
    zero_shot_promotion_allowed: Literal[False] = False
    final_holdout_opened: Literal[False] = False


class ArenaCandidateSummary(DomainModel):
    candidate_id: str
    model_class: ForecastModelClass
    prediction_mode: PredictionMode
    fold_ids: tuple[str, ...]
    mean_primary_loss: NonNegativeDecimal | None
    mean_direction_accuracy: UnitInterval | None
    mean_crps: NonNegativeDecimal | None
    mean_brier_score: NonNegativeDecimal | None
    mean_interval_coverage: UnitInterval | None
    mean_tail_recall: UnitInterval | None
    mean_net_return_after_cost: FiniteDecimal | None
    eligible_for_selection: bool
    exclusion_reasons: tuple[str, ...]
    alpha_promotion_eligible: Literal[False] = False

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        metrics = (
            self.mean_primary_loss,
            self.mean_direction_accuracy,
            self.mean_crps,
            self.mean_brier_score,
            self.mean_interval_coverage,
            self.mean_tail_recall,
            self.mean_net_return_after_cost,
        )
        if self.eligible_for_selection:
            if any(value is None for value in metrics) or self.exclusion_reasons:
                raise ValueError("eligible arena candidate requires metrics and no exclusion")
        elif not self.exclusion_reasons:
            raise ValueError("ineligible arena candidate requires an exclusion reason")
        return self


class ArenaCellResult(DomainModel):
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    baseline_candidate_id: str
    research_champion_candidate_id: str
    candidates: Annotated[tuple[ArenaCandidateSummary, ...], Field(min_length=2)]
    equal_oos_folds: Literal[True] = True
    selection_scope: Literal["asset_x_horizon_x_regime"] = "asset_x_horizon_x_regime"
    alpha_promotion_eligible: Literal[False] = False

    @model_validator(mode="after")
    def validate_cell(self) -> Self:
        candidates = {item.candidate_id: item for item in self.candidates}
        if len(candidates) != len(self.candidates):
            raise ValueError("arena cell candidate ids must be unique")
        if self.baseline_candidate_id not in candidates:
            raise ValueError("arena cell baseline is missing")
        champion = candidates.get(self.research_champion_candidate_id)
        if champion is None or not champion.eligible_for_selection:
            raise ValueError("arena cell champion must be selection-eligible")
        if not candidates[self.baseline_candidate_id].eligible_for_selection:
            raise ValueError("arena cell baseline must be selection-eligible")
        return self


class ModelArenaReport(DomainModel):
    capability_matrix_sha256: str
    spec: ModelArenaSpec
    cells: Annotated[tuple[ArenaCellResult, ...], Field(min_length=1)]
    fair_comparison: Literal[True] = True
    no_single_universal_model_assumption: Literal[True] = True
    zero_shot_is_promotion: Literal[False] = False
    failures_preserved: Literal[True] = True
    evidence_tier: Literal[EvidenceTier.DEVELOPMENT] = EvidenceTier.DEVELOPMENT
    alpha_promotion_eligible: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True

    @field_validator("capability_matrix_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forecast capability matrix hash")

    @model_validator(mode="after")
    def validate_cells(self) -> Self:
        keys = tuple((item.asset_id, item.horizon, item.regime) for item in self.cells)
        if len(set(keys)) != len(keys):
            raise ValueError("model arena cells must be unique")
        return self


class VisionAblationReport(DomainModel):
    asset_id: AssetId
    horizon: CouncilHorizon
    regime: MarketRegime
    numeric_only_loss: NonNegativeDecimal
    vision_only_loss: NonNegativeDecimal
    numeric_vision_loss: NonNegativeDecimal
    minimum_absolute_improvement: NonNegativeDecimal
    retain_vision: bool
    selected_modality: ForecastModality
    reason_code: str
    alpha_promotion_eligible: Literal[False] = False

    @model_validator(mode="after")
    def validate_ablation(self) -> Self:
        best_vision = min(self.vision_only_loss, self.numeric_vision_loss)
        expected_retain = self.numeric_only_loss - best_vision >= self.minimum_absolute_improvement
        if self.retain_vision != expected_retain:
            raise ValueError("vision ablation retention does not match OOS losses")
        expected_modality = ForecastModality.NUMERIC_ONLY
        if expected_retain:
            expected_modality = (
                ForecastModality.VISION_ONLY
                if self.vision_only_loss <= self.numeric_vision_loss
                else ForecastModality.NUMERIC_VISION
            )
        if self.selected_modality is not expected_modality:
            raise ValueError("vision ablation selected modality is inconsistent")
        expected_reason = (
            "VISION_OOS_INCREMENT_PASSED" if expected_retain else "VISION_NO_OOS_INCREMENT"
        )
        if self.reason_code != expected_reason:
            raise ValueError("vision ablation reason code is inconsistent")
        return self


def bind_forecast_inputs(
    *,
    forecast: ForecastEnvelope,
    tensor: MarketStateTensor,
    calibrations: tuple[CalibrationArtifact, ...],
    capability: ModelCapability,
) -> None:
    """Revalidate and bind all lineage objects consumed by a forecast."""

    validated_forecast = ForecastEnvelope.model_validate_json(forecast.model_dump_json())
    validated_tensor = validate_market_state_tensor(tensor)
    validated_calibrations = tuple(
        CalibrationArtifact.model_validate_json(item.model_dump_json()) for item in calibrations
    )
    validated_capability = ModelCapability.model_validate_json(capability.model_dump_json())
    if validated_forecast.market_state_tensor_sha256 != validated_tensor.tensor_sha256:
        raise ValueError("AQ-FORECAST-TENSOR-BINDING-MISMATCH")
    if validated_forecast.dataset_manifest_sha256 != validated_tensor.dataset_manifest_sha256:
        raise ValueError("AQ-FORECAST-DATASET-BINDING-MISMATCH")
    calibration_by_horizon = {item.horizon: item for item in validated_calibrations}
    if len(calibration_by_horizon) != len(validated_calibrations):
        raise ValueError("AQ-FORECAST-DUPLICATE-CALIBRATION-HORIZON")
    if set(calibration_by_horizon) != {item.horizon for item in validated_forecast.horizons}:
        raise ValueError("AQ-FORECAST-CALIBRATION-HORIZON-MISMATCH")
    if any(
        validated_forecast.calibration_artifact_sha256_by_horizon[horizon]
        != artifact.artifact_sha256
        for horizon, artifact in calibration_by_horizon.items()
    ):
        raise ValueError("AQ-FORECAST-CALIBRATION-BINDING-MISMATCH")
    if validated_forecast.model_capability_sha256 != capability_sha256(validated_capability):
        raise ValueError("AQ-FORECAST-CAPABILITY-BINDING-MISMATCH")
    if (
        validated_forecast.model_id != validated_capability.candidate_id
        or validated_forecast.model_revision != validated_capability.model_revision
        or validated_forecast.prediction_mode not in validated_capability.prediction_modes
    ):
        raise ValueError("AQ-FORECAST-MODEL-BINDING-MISMATCH")
    if (
        validated_forecast.asset_id != validated_tensor.asset_id
        or validated_forecast.instrument_id != validated_tensor.instrument_id
        or validated_forecast.as_of_time != validated_tensor.decision_time
    ):
        raise ValueError("AQ-FORECAST-MARKET-IDENTITY-MISMATCH")
    if any(
        artifact.asset_id != validated_forecast.asset_id
        or artifact.regime is not validated_forecast.regime
        or artifact.available_at > validated_forecast.as_of_time
        for artifact in validated_calibrations
    ):
        raise ValueError("AQ-FORECAST-CALIBRATION-PIT-MISMATCH")
    supported = set(validated_capability.supported_horizons)
    if any(item.horizon not in supported for item in validated_forecast.horizons):
        raise ValueError("AQ-FORECAST-UNSUPPORTED-HORIZON")
