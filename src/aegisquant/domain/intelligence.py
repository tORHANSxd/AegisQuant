"""Market-event, source-evidence, forecast, signal, and risk contracts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    AccountId,
    ArtifactId,
    ClaimId,
    ContentId,
    EventClusterId,
    EventId,
    ForecastId,
    ImpactForecastId,
    InstrumentId,
    ModelVersionId,
    NarrativeId,
    ProposalId,
    ProviderId,
    ProviderNativeId,
    RiskDecisionId,
    SignalId,
    SourceDocumentId,
    SourceIdentityId,
    SourcePolicyId,
    StrategyVersionId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    Money,
    NonNegativeDecimal,
    Quantity,
    UnitInterval,
)


class ContentType(StrEnum):
    POST = "POST"
    ARTICLE = "ARTICLE"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    VIDEO_META = "VIDEO_META"
    CHANNEL_MESSAGE = "CHANNEL_MESSAGE"
    RELEASE = "RELEASE"
    FILING = "FILING"


class RightsState(StrEnum):
    ALLOWED = "ALLOWED"
    LIMITED = "LIMITED"
    UNKNOWN = "UNKNOWN"
    PROHIBITED = "PROHIBITED"


class QualityState(StrEnum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INVALID = "INVALID"


class AssertionMode(StrEnum):
    FACT = "FACT"
    FORECAST = "FORECAST"
    OPINION = "OPINION"
    RUMOR = "RUMOR"
    DENIAL = "DENIAL"
    QUESTION = "QUESTION"


class Polarity(StrEnum):
    AFFIRM = "AFFIRM"
    NEGATE = "NEGATE"
    UNCERTAIN = "UNCERTAIN"


class EventClusterStatus(StrEnum):
    RUMOR = "RUMOR"
    EMERGING = "EMERGING"
    CORROBORATED = "CORROBORATED"
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class ForecastHorizon(StrEnum):
    FIVE_MINUTES = "5m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    SEVEN_DAYS = "7d"


class ForecastTarget(StrEnum):
    NET_RETURN = "net_return"
    VOLATILITY = "volatility"
    TAIL_LOSS = "tail_loss"
    FILL_PROBABILITY = "fill_probability"
    SLIPPAGE = "slippage"


class SignalDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class RiskDecisionType(StrEnum):
    APPROVE = "APPROVE"
    CLIP = "CLIP"
    REDUCE_ONLY = "REDUCE_ONLY"
    REJECT = "REJECT"
    HALT = "HALT"


class MarketEvent(DomainModel):
    event_id: EventId
    event_type: str
    instrument_ids: tuple[InstrumentId, ...] = ()
    event_time: UtcDateTime
    available_time: UtcDateTime
    ingest_time: UtcDateTime
    processed_time: UtcDateTime
    revision_time: UtcDateTime | None = None
    source_document_ids: tuple[SourceDocumentId, ...] = ()
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time_order(self) -> MarketEvent:
        if self.available_time > self.ingest_time or self.ingest_time > self.processed_time:
            raise ValueError("event available/ingest/processed times must be monotonic")
        if self.revision_time is not None and self.revision_time > self.processed_time:
            raise ValueError("revision_time cannot exceed processed_time")
        return self


class SourceIdentity(DomainModel):
    source_identity_id: SourceIdentityId
    provider_id: ProviderId
    provider_native_id: ProviderNativeId
    display_name: str
    ownership_group: str
    independence_group: str
    verified: bool
    first_observed_time: UtcDateTime


class RawContentEnvelope(DomainModel):
    content_id: ContentId
    provider_id: ProviderId
    provider_native_id: ProviderNativeId
    source_identity_id: SourceIdentityId
    content_type: ContentType
    canonical_url: str
    author_time: UtcDateTime | None = None
    published_time: UtcDateTime
    first_observed_time: UtcDateTime
    available_time: UtcDateTime
    ingest_time: UtcDateTime
    modified_time: UtcDateTime | None = None
    deleted_time: UtcDateTime | None = None
    language: str
    raw_object_uri: str | None = None
    raw_content_hash: str
    revision: int
    engagement_snapshot_id: ArtifactId | None = None
    source_policy_id: SourcePolicyId
    rights_state: RightsState
    quality_state: QualityState

    @model_validator(mode="after")
    def validate_content_version(self) -> RawContentEnvelope:
        if self.revision < 1:
            raise ValueError("content revision starts at one")
        if len(self.raw_content_hash) != 64:
            raise ValueError("raw_content_hash must be a SHA-256 hex digest")
        if self.available_time > self.ingest_time:
            raise ValueError("content cannot be ingested before it is available")
        if self.deleted_time is not None and self.deleted_time < self.published_time:
            raise ValueError("deleted_time cannot precede published_time")
        return self


class ClaimRecord(DomainModel):
    claim_id: ClaimId
    content_id: ContentId
    claim_text_normalized: str
    subject_entity_ids: tuple[str, ...]
    predicate: str
    object_entity_ids: tuple[str, ...]
    event_type: str
    assertion_mode: AssertionMode
    polarity: Polarity
    evidence_spans: tuple[str, ...]
    extractor_versions: tuple[ModelVersionId, ...]
    source_independence_group: str
    credibility_prior: UnitInterval
    novelty_score: UnitInterval
    prompt_injection_flags: tuple[str, ...] = ()


class EventCluster(DomainModel):
    event_cluster_id: EventClusterId
    event_type: str
    status: EventClusterStatus
    entity_ids: tuple[str, ...]
    claimed_event_time: UtcDateTime | None = None
    first_observed_time: UtcDateTime
    last_updated_time: UtcDateTime
    claim_ids: tuple[ClaimId, ...]
    supporting_evidence_ids: tuple[SourceDocumentId, ...]
    contradicting_evidence_ids: tuple[SourceDocumentId, ...]
    independent_source_count: int
    official_confirmation_ids: tuple[SourceDocumentId, ...]
    credibility_score: UnitInterval
    manipulation_risk: UnitInterval
    uncertainty: UnitInterval
    supersedes_event_cluster_id: EventClusterId | None = None

    @model_validator(mode="after")
    def validate_cluster(self) -> EventCluster:
        if self.last_updated_time < self.first_observed_time:
            raise ValueError("cluster update cannot precede first observation")
        if self.independent_source_count < 0:
            raise ValueError("independent source count cannot be negative")
        return self


class NarrativeState(DomainModel):
    narrative_id: NarrativeId
    topic: str
    entity_ids: tuple[str, ...]
    first_observed_time: UtcDateTime
    as_of_time: UtcDateTime
    propagation_stage: str
    posts_per_hour: NonNegativeDecimal
    independent_author_count: int
    platform_count: int
    sentiment_score: FiniteDecimal
    contradicting_evidence_count: int
    engagement_velocity_per_hour: NonNegativeDecimal
    coordination_risk: UnitInterval
    price_reflection_score: UnitInterval
    decay_half_life_hours: NonNegativeDecimal
    crowding_score: UnitInterval


class ForecastDistribution(DomainModel):
    mean: FiniteDecimal
    std: NonNegativeDecimal
    q05: FiniteDecimal
    q50: FiniteDecimal
    q95: FiniteDecimal

    @model_validator(mode="after")
    def quantiles_are_ordered(self) -> ForecastDistribution:
        if not self.q05 <= self.q50 <= self.q95:
            raise ValueError("forecast quantiles must be ordered")
        return self


class DirectionProbabilities(DomainModel):
    up: UnitInterval
    flat: UnitInterval
    down: UnitInterval

    @model_validator(mode="after")
    def probabilities_sum_to_one(self) -> DirectionProbabilities:
        if self.up + self.flat + self.down != Decimal("1"):
            raise ValueError("direction probabilities must sum exactly to one")
        return self


class ForecastUncertainty(DomainModel):
    epistemic: NonNegativeDecimal
    aleatoric: NonNegativeDecimal
    ensemble_disagreement: NonNegativeDecimal


class HorizonImpact(DomainModel):
    return_distribution: ForecastDistribution
    volatility_delta: FiniteDecimal
    liquidity_delta: FiniteDecimal
    tail_risk_delta: FiniteDecimal


class EventImpactForecast(DomainModel):
    impact_forecast_id: ImpactForecastId
    event_cluster_id: EventClusterId
    as_of_time: UtcDateTime
    affected_exposure_ids: tuple[str, ...]
    horizons: dict[ForecastHorizon, HorizonImpact]
    transmission_channels: tuple[str, ...]
    market_already_moved_score: UnitInterval
    corroboration_score: UnitInterval
    source_quality_score: UnitInterval
    novelty_score: UnitInterval
    manipulation_risk: UnitInterval
    model_disagreement: NonNegativeDecimal
    evidence_ids: tuple[SourceDocumentId, ...]
    model_versions: tuple[ModelVersionId, ...]
    should_abstain: bool
    abstain_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def validate_impact_forecast(self) -> EventImpactForecast:
        required = {
            ForecastHorizon.FIVE_MINUTES,
            ForecastHorizon.THIRTY_MINUTES,
            ForecastHorizon.FOUR_HOURS,
            ForecastHorizon.ONE_DAY,
            ForecastHorizon.SEVEN_DAYS,
        }
        if set(self.horizons) != required:
            raise ValueError("event impact forecast requires 5m, 30m, 4h, 1d, and 7d")
        if self.should_abstain != bool(self.abstain_reasons):
            raise ValueError("impact abstention flag and reasons must agree")
        return self


class ForecastBundle(DomainModel):
    forecast_id: ForecastId
    model_version_id: ModelVersionId
    instrument_id: InstrumentId
    as_of_time: UtcDateTime
    horizon: ForecastHorizon
    target: ForecastTarget
    distribution: ForecastDistribution
    probabilities: DirectionProbabilities
    calibration_version: str
    uncertainty: ForecastUncertainty
    regime_id: str
    feature_snapshot_id: ArtifactId
    dataset_manifest_hash: str
    code_commit: str
    should_abstain: bool
    abstain_reason: str | None = None

    @model_validator(mode="after")
    def validate_abstention(self) -> ForecastBundle:
        if self.should_abstain != (self.abstain_reason is not None):
            raise ValueError("abstention flag and reason must agree")
        return self


class AlphaSignal(DomainModel):
    signal_id: SignalId
    strategy_version_id: StrategyVersionId
    instrument_id: InstrumentId
    as_of_time: UtcDateTime
    valid_until: UtcDateTime
    expected_gross_return: FiniteDecimal
    expected_cost: NonNegativeDecimal
    expected_net_return: FiniteDecimal
    expected_risk: NonNegativeDecimal
    confidence: UnitInterval
    score: FiniteDecimal
    direction: SignalDirection
    capacity_notional: Money
    source_forecast_ids: tuple[ForecastId, ...]
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_signal(self) -> AlphaSignal:
        if self.valid_until <= self.as_of_time:
            raise ValueError("signal validity must end after as_of_time")
        if self.expected_gross_return - self.expected_cost != self.expected_net_return:
            raise ValueError("expected net return must equal gross return minus cost")
        return self


class PortfolioTarget(DomainModel):
    instrument_id: InstrumentId
    current_weight: FiniteDecimal
    target_weight: FiniteDecimal
    target_quantity: Quantity
    target_notional: Money


class IncrementalTrade(DomainModel):
    instrument_id: InstrumentId
    quantity_delta: Quantity
    expected_cost: Money


class PortfolioProposal(DomainModel):
    proposal_id: ProposalId
    account_id: AccountId
    as_of_time: UtcDateTime
    valid_until: UtcDateTime
    targets: tuple[PortfolioTarget, ...]
    incremental_trades: tuple[IncrementalTrade, ...]
    expected_return: FiniteDecimal
    expected_risk: NonNegativeDecimal
    expected_cost: Money
    capacity_notional: Money
    strategy_contributions: dict[str, FiniteDecimal]
    factor_exposures: dict[str, FiniteDecimal]
    market_state_exposures: dict[str, FiniteDecimal]
    constraint_headroom: dict[str, FiniteDecimal]
    confidence: UnitInterval

    @model_validator(mode="after")
    def proposal_has_future_expiry(self) -> PortfolioProposal:
        if self.valid_until <= self.as_of_time:
            raise ValueError("proposal must expire after as_of_time")
        return self


class LimitResult(DomainModel):
    limit_code: str
    passed: bool
    observed: FiniteDecimal
    limit: FiniteDecimal
    unit: str


class RiskDecision(DomainModel):
    risk_decision_id: RiskDecisionId
    proposal_id: ProposalId
    decision: RiskDecisionType
    approved_targets: tuple[PortfolioTarget, ...]
    limit_results: tuple[LimitResult, ...]
    reason_codes: tuple[str, ...]
    risk_policy_version: str
    account_snapshot_id: ArtifactId
    expires_at: UtcDateTime
