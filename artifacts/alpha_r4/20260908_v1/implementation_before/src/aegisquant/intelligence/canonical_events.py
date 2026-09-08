"""Point-in-time canonical events, surprise, diffusion, and price-in gates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ArtifactId, EventClusterId, EventId
from aegisquant.domain.intelligence import EventCluster, EventClusterStatus, QualityState
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.truth import TruthAssessment, TruthState
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    UnitInterval,
)


def _json_time(value: UtcDateTime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class EventValueKind(StrEnum):
    ACTUAL = "ACTUAL"
    CONSENSUS = "CONSENSUS"
    WHISPER = "WHISPER"
    PRIOR_PROBABILITY = "PRIOR_PROBABILITY"


class SurpriseDirection(StrEnum):
    MORE_POSITIVE_THAN_EXPECTED = "MORE_POSITIVE_THAN_EXPECTED"
    AS_EXPECTED = "AS_EXPECTED"
    MORE_NEGATIVE_THAN_EXPECTED = "MORE_NEGATIVE_THAN_EXPECTED"


class NarrativePropagationStage(StrEnum):
    EMERGING = "EMERGING"
    CROSS_PLATFORM = "CROSS_PLATFORM"
    BROAD = "BROAD"


class MarketReflectionMetric(StrEnum):
    PRE_CONFIRMATION_PRICE_MOVE = "PRE_CONFIRMATION_PRICE_MOVE"
    ABNORMAL_RETURN = "ABNORMAL_RETURN"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    OPEN_INTEREST_CHANGE = "OPEN_INTEREST_CHANGE"
    FUNDING_CHANGE = "FUNDING_CHANGE"
    BASIS_CHANGE = "BASIS_CHANGE"
    OPTIONS_IV_SKEW = "OPTIONS_IV_SKEW"
    CROSS_ASSET_RESPONSE = "CROSS_ASSET_RESPONSE"
    NARRATIVE_DIFFUSION = "NARRATIVE_DIFFUSION"
    LIQUIDATION_FLOW = "LIQUIDATION_FLOW"
    MARKET_DEPTH_CHANGE = "MARKET_DEPTH_CHANGE"


class TimedEventValue(DomainModel):
    value_id: ArtifactId
    event_cluster_id: EventClusterId
    kind: EventValueKind
    value: FiniteDecimal
    unit: str = Field(min_length=1)
    observed_at: UtcDateTime
    available_at: UtcDateTime
    source_artifact_id: ArtifactId
    source_sha256: str

    @model_validator(mode="after")
    def validate_value(self) -> TimedEventValue:
        if self.observed_at > self.available_at:
            raise ValueError("AQ-EVENT-VALUE-TIME-ORDER")
        ensure_sha256(self.source_sha256, field_name="source_sha256")
        if self.kind is EventValueKind.PRIOR_PROBABILITY and not Decimal(
            "0"
        ) <= self.value <= Decimal("1"):
            raise ValueError("AQ-EVENT-PRIOR-PROBABILITY-RANGE")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"value_id"}))
        if str(self.value_id) != expected:
            raise ValueError("AQ-EVENT-VALUE-ID-HASH-MISMATCH")
        return self


class EventValueSnapshot(DomainModel):
    snapshot_id: ArtifactId
    event_cluster_id: EventClusterId
    as_of_time: UtcDateTime
    values: tuple[TimedEventValue, ...] = Field(min_length=1)
    snapshot_sha256: str

    @model_validator(mode="after")
    def validate_snapshot(self) -> EventValueSnapshot:
        ensure_sha256(self.snapshot_sha256, field_name="snapshot_sha256")
        kinds = tuple(item.kind for item in self.values)
        if kinds != tuple(sorted(kinds, key=lambda item: item.value)) or len(kinds) != len(
            set(kinds)
        ):
            raise ValueError("AQ-EVENT-VALUE-SNAPSHOT-ORDER-OR-DUPLICATE")
        if any(item.event_cluster_id != self.event_cluster_id for item in self.values):
            raise ValueError("AQ-EVENT-VALUE-CLUSTER-MISMATCH")
        if any(item.available_at > self.as_of_time for item in self.values):
            raise ValueError("AQ-EVENT-VALUE-LOOKAHEAD")
        present = set(kinds)
        pair = {EventValueKind.ACTUAL, EventValueKind.CONSENSUS}
        if bool(pair & present) and not pair <= present:
            raise ValueError("AQ-EVENT-ACTUAL-CONSENSUS-PAIR-REQUIRED")
        if EventValueKind.WHISPER in present and not pair <= present:
            raise ValueError("AQ-EVENT-WHISPER-REQUIRES-ACTUAL-CONSENSUS")
        comparable = [
            item for item in self.values if item.kind is not EventValueKind.PRIOR_PROBABILITY
        ]
        if comparable and len({item.unit for item in comparable}) != 1:
            raise ValueError("AQ-EVENT-VALUE-UNIT-MISMATCH")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"snapshot_id", "snapshot_sha256"})
        )
        if str(self.snapshot_id) != expected or self.snapshot_sha256 != expected:
            raise ValueError("AQ-EVENT-VALUE-SNAPSHOT-HASH-MISMATCH")
        return self


class EventSurprise(DomainModel):
    surprise_id: ArtifactId
    event_cluster_id: EventClusterId
    value_snapshot_id: ArtifactId
    value_snapshot_sha256: str
    as_of_time: UtcDateTime
    actual_value: FiniteDecimal
    expected_value: FiniteDecimal
    whisper_value: FiniteDecimal | None = None
    surprise_value: FiniteDecimal
    whisper_surprise_value: FiniteDecimal | None = None
    materiality_threshold: NonNegativeDecimal
    value_unit: str = Field(min_length=1)
    direction: SurpriseDirection
    surprise_sha256: str

    @model_validator(mode="after")
    def validate_surprise(self) -> EventSurprise:
        ensure_sha256(self.value_snapshot_sha256, field_name="value_snapshot_sha256")
        ensure_sha256(self.surprise_sha256, field_name="surprise_sha256")
        if self.surprise_value != self.actual_value - self.expected_value:
            raise ValueError("AQ-EVENT-SURPRISE-CALCULATION-MISMATCH")
        if (self.whisper_value is None) != (self.whisper_surprise_value is None):
            raise ValueError("AQ-EVENT-WHISPER-SURPRISE-BINDING")
        if self.whisper_value is not None and self.whisper_surprise_value != (
            self.actual_value - self.whisper_value
        ):
            raise ValueError("AQ-EVENT-WHISPER-SURPRISE-CALCULATION-MISMATCH")
        expected_direction = (
            SurpriseDirection.MORE_POSITIVE_THAN_EXPECTED
            if self.surprise_value > self.materiality_threshold
            else SurpriseDirection.MORE_NEGATIVE_THAN_EXPECTED
            if self.surprise_value < -self.materiality_threshold
            else SurpriseDirection.AS_EXPECTED
        )
        if self.direction is not expected_direction:
            raise ValueError("AQ-EVENT-SURPRISE-DIRECTION-MISMATCH")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"surprise_id", "surprise_sha256"})
        )
        if str(self.surprise_id) != expected or self.surprise_sha256 != expected:
            raise ValueError("AQ-EVENT-SURPRISE-HASH-MISMATCH")
        return self


class NarrativeDiffusionObservation(DomainModel):
    observation_id: ArtifactId
    event_cluster_id: EventClusterId
    source_id: str = Field(min_length=1)
    independence_group: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=35)
    verified_source: bool
    kol_source: bool = False
    news_wire_source: bool = False
    observed_at: UtcDateTime
    available_at: UtcDateTime
    source_sha256: str

    @model_validator(mode="after")
    def validate_observation(self) -> NarrativeDiffusionObservation:
        if self.observed_at > self.available_at:
            raise ValueError("AQ-NARRATIVE-OBSERVATION-TIME-ORDER")
        ensure_sha256(self.source_sha256, field_name="source_sha256")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"observation_id"}))
        if str(self.observation_id) != expected:
            raise ValueError("AQ-NARRATIVE-OBSERVATION-ID-HASH-MISMATCH")
        return self


class NarrativeDiffusionSnapshot(DomainModel):
    diffusion_id: ArtifactId
    event_cluster_id: EventClusterId
    as_of_time: UtcDateTime
    window_hours: NonNegativeDecimal
    observations: tuple[NarrativeDiffusionObservation, ...] = Field(min_length=1)
    first_source_id: str = Field(min_length=1)
    first_verified_source_id: str | None = None
    first_observed_at: UtcDateTime
    first_verified_at: UtcDateTime | None = None
    independent_source_count: int = Field(ge=1)
    platform_count: int = Field(ge=1)
    language_count: int = Field(ge=1)
    kol_count: int = Field(ge=0)
    news_wire_count: int = Field(ge=0)
    source_velocity_per_hour: NonNegativeDecimal
    independent_source_velocity_per_hour: NonNegativeDecimal
    propagation_stage: NarrativePropagationStage
    price_response_at: UtcDateTime | None = None
    price_response_available_at: UtcDateTime | None = None
    price_response_source_sha256: str | None = None
    volume_response_at: UtcDateTime | None = None
    volume_response_available_at: UtcDateTime | None = None
    volume_response_source_sha256: str | None = None
    price_response_lag_seconds: NonNegativeDecimal | None = None
    volume_response_lag_seconds: NonNegativeDecimal | None = None
    diffusion_sha256: str

    @model_validator(mode="after")
    def validate_diffusion(self) -> NarrativeDiffusionSnapshot:
        ensure_sha256(self.diffusion_sha256, field_name="diffusion_sha256")
        if self.window_hours <= 0:
            raise ValueError("AQ-NARRATIVE-WINDOW-NOT-POSITIVE")
        ordered = tuple(
            sorted(
                self.observations, key=lambda item: (item.available_at, str(item.observation_id))
            )
        )
        if self.observations != ordered or len({item.observation_id for item in ordered}) != len(
            ordered
        ):
            raise ValueError("AQ-NARRATIVE-OBSERVATION-ORDER-OR-DUPLICATE")
        if any(item.event_cluster_id != self.event_cluster_id for item in ordered):
            raise ValueError("AQ-NARRATIVE-CLUSTER-MISMATCH")
        if any(item.available_at > self.as_of_time for item in ordered):
            raise ValueError("AQ-NARRATIVE-LOOKAHEAD")
        first = min(ordered, key=lambda item: (item.observed_at, str(item.observation_id)))
        if self.first_source_id != first.source_id or self.first_observed_at != first.observed_at:
            raise ValueError("AQ-NARRATIVE-FIRST-SOURCE-MISMATCH")
        verified = tuple(item for item in ordered if item.verified_source)
        if verified:
            first_verified = min(
                verified, key=lambda item: (item.observed_at, str(item.observation_id))
            )
            if (
                self.first_verified_source_id != first_verified.source_id
                or self.first_verified_at != first_verified.observed_at
            ):
                raise ValueError("AQ-NARRATIVE-FIRST-VERIFIED-SOURCE-MISMATCH")
        elif self.first_verified_source_id is not None or self.first_verified_at is not None:
            raise ValueError("AQ-NARRATIVE-FORGED-VERIFIED-SOURCE")
        expected_counts = (
            len({item.independence_group for item in ordered}),
            len({item.platform for item in ordered}),
            len({item.language for item in ordered}),
            sum(item.kol_source for item in ordered),
            sum(item.news_wire_source for item in ordered),
        )
        if expected_counts != (
            self.independent_source_count,
            self.platform_count,
            self.language_count,
            self.kol_count,
            self.news_wire_count,
        ):
            raise ValueError("AQ-NARRATIVE-DIFFUSION-COUNT-MISMATCH")
        expected_velocity = Decimal(len(ordered)) / self.window_hours
        expected_independent_velocity = Decimal(expected_counts[0]) / self.window_hours
        if (
            self.source_velocity_per_hour != expected_velocity
            or self.independent_source_velocity_per_hour != expected_independent_velocity
        ):
            raise ValueError("AQ-NARRATIVE-DIFFUSION-VELOCITY-MISMATCH")
        expected_stage = (
            NarrativePropagationStage.BROAD
            if expected_counts[0] >= 4 and expected_counts[1] >= 3
            else NarrativePropagationStage.CROSS_PLATFORM
            if expected_counts[0] >= 2 and expected_counts[1] >= 2
            else NarrativePropagationStage.EMERGING
        )
        if self.propagation_stage is not expected_stage:
            raise ValueError("AQ-NARRATIVE-PROPAGATION-STAGE-MISMATCH")
        self._validate_response(
            name="price",
            response_at=self.price_response_at,
            response_available_at=self.price_response_available_at,
            source_sha256=self.price_response_source_sha256,
            lag_seconds=self.price_response_lag_seconds,
        )
        self._validate_response(
            name="volume",
            response_at=self.volume_response_at,
            response_available_at=self.volume_response_available_at,
            source_sha256=self.volume_response_source_sha256,
            lag_seconds=self.volume_response_lag_seconds,
        )
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"diffusion_id", "diffusion_sha256"})
        )
        if str(self.diffusion_id) != expected or self.diffusion_sha256 != expected:
            raise ValueError("AQ-NARRATIVE-DIFFUSION-HASH-MISMATCH")
        return self

    def _validate_response(
        self,
        *,
        name: str,
        response_at: UtcDateTime | None,
        response_available_at: UtcDateTime | None,
        source_sha256: str | None,
        lag_seconds: Decimal | None,
    ) -> None:
        present = (response_at, response_available_at, source_sha256, lag_seconds)
        if all(value is None for value in present):
            return
        if (
            response_at is None
            or response_available_at is None
            or source_sha256 is None
            or lag_seconds is None
        ):
            raise ValueError(f"AQ-NARRATIVE-{name.upper()}-RESPONSE-BINDING")
        ensure_sha256(source_sha256, field_name=f"{name}_response_source_sha256")
        if not self.first_observed_at <= response_at <= response_available_at <= self.as_of_time:
            raise ValueError(f"AQ-NARRATIVE-{name.upper()}-RESPONSE-TIME-ORDER")
        expected_lag = Decimal(str((response_at - self.first_observed_at).total_seconds()))
        if lag_seconds != expected_lag:
            raise ValueError(f"AQ-NARRATIVE-{name.upper()}-RESPONSE-LAG-MISMATCH")


class TimedMarketReflectionMetric(DomainModel):
    metric_id: ArtifactId
    event_cluster_id: EventClusterId
    metric: MarketReflectionMetric
    reflection_strength: UnitInterval
    observed_at: UtcDateTime
    available_at: UtcDateTime
    source_id: str = Field(min_length=1)
    source_sha256: str

    @model_validator(mode="after")
    def validate_metric(self) -> TimedMarketReflectionMetric:
        if self.observed_at > self.available_at:
            raise ValueError("AQ-MARKET-REFLECTION-METRIC-TIME-ORDER")
        ensure_sha256(self.source_sha256, field_name="source_sha256")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"metric_id"}))
        if str(self.metric_id) != expected:
            raise ValueError("AQ-MARKET-REFLECTION-METRIC-ID-HASH-MISMATCH")
        return self


class MarketReflectionPolicy(DomainModel):
    policy_version: str = Field(min_length=1)
    required_metrics: tuple[MarketReflectionMetric, ...] = Field(min_length=1)
    metric_weights: dict[MarketReflectionMetric, UnitInterval]
    high_price_in_threshold: UnitInterval
    max_metric_age_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_policy(self) -> MarketReflectionPolicy:
        if len(self.required_metrics) != len(set(self.required_metrics)):
            raise ValueError("AQ-MARKET-REFLECTION-DUPLICATE-REQUIRED-METRIC")
        if set(self.metric_weights) != set(self.required_metrics):
            raise ValueError("AQ-MARKET-REFLECTION-WEIGHT-COVERAGE")
        if sum(self.metric_weights.values(), Decimal("0")) != Decimal("1"):
            raise ValueError("AQ-MARKET-REFLECTION-WEIGHTS-SUM")
        return self

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class MarketReflectionScore(DomainModel):
    reflection_id: ArtifactId
    event_cluster_id: EventClusterId
    as_of_time: UtcDateTime
    policy: MarketReflectionPolicy
    metrics: tuple[TimedMarketReflectionMetric, ...]
    missing_metrics: tuple[MarketReflectionMetric, ...]
    stale_metric_ids: tuple[ArtifactId, ...]
    market_reflection_score: UnitInterval | None = None
    already_priced_probability: UnitInterval | None = None
    high_price_in: bool
    quality_state: QualityState
    method: Literal["DEVELOPMENT_WEIGHTED_SCORE_V1"] = "DEVELOPMENT_WEIGHTED_SCORE_V1"
    promotion_eligible: Literal[False] = False
    reflection_sha256: str

    @model_validator(mode="after")
    def validate_reflection(self) -> MarketReflectionScore:
        ensure_sha256(self.reflection_sha256, field_name="reflection_sha256")
        ordered = tuple(sorted(self.metrics, key=lambda item: item.metric.value))
        if self.metrics != ordered or len({item.metric for item in ordered}) != len(ordered):
            raise ValueError("AQ-MARKET-REFLECTION-METRIC-ORDER-OR-DUPLICATE")
        if any(item.event_cluster_id != self.event_cluster_id for item in ordered):
            raise ValueError("AQ-MARKET-REFLECTION-CLUSTER-MISMATCH")
        if any(item.available_at > self.as_of_time for item in ordered):
            raise ValueError("AQ-MARKET-REFLECTION-LOOKAHEAD")
        present = {item.metric for item in ordered}
        expected_missing = tuple(
            sorted(set(self.policy.required_metrics) - present, key=lambda item: item.value)
        )
        if self.missing_metrics != expected_missing:
            raise ValueError("AQ-MARKET-REFLECTION-MISSING-METRIC-MISMATCH")
        expected_stale = tuple(
            sorted(
                (
                    item.metric_id
                    for item in ordered
                    if (self.as_of_time - item.available_at).total_seconds()
                    > self.policy.max_metric_age_seconds
                ),
                key=str,
            )
        )
        if self.stale_metric_ids != expected_stale:
            raise ValueError("AQ-MARKET-REFLECTION-STALE-METRIC-MISMATCH")
        complete = not expected_missing and not expected_stale
        if complete:
            expected_score = sum(
                (
                    item.reflection_strength * self.policy.metric_weights[item.metric]
                    for item in ordered
                    if item.metric in self.policy.metric_weights
                ),
                Decimal("0"),
            )
            if (
                self.quality_state is not QualityState.GOOD
                or self.market_reflection_score != expected_score
                or self.already_priced_probability != expected_score
                or self.high_price_in != (expected_score >= self.policy.high_price_in_threshold)
            ):
                raise ValueError("AQ-MARKET-REFLECTION-SCORE-MISMATCH")
        elif (
            self.quality_state is QualityState.GOOD
            or self.market_reflection_score is not None
            or self.already_priced_probability is not None
            or self.high_price_in
        ):
            raise ValueError("AQ-MARKET-REFLECTION-INCOMPLETE-MUST-FAIL-CLOSED")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"reflection_id", "reflection_sha256"})
        )
        if str(self.reflection_id) != expected or self.reflection_sha256 != expected:
            raise ValueError("AQ-MARKET-REFLECTION-HASH-MISMATCH")
        return self


class CanonicalEvent(DomainModel):
    event_id: EventId
    revision_id: ArtifactId
    previous_revision_id: ArtifactId | None = None
    revision_number: int = Field(ge=1)
    source_cluster: EventCluster
    event_type: str = Field(min_length=1)
    event_stage: EventClusterStatus
    entities: tuple[str, ...] = Field(min_length=1)
    assets: tuple[str, ...] = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    actual_value: FiniteDecimal | None = None
    expected_value: FiniteDecimal | None = None
    whisper_value: FiniteDecimal | None = None
    surprise_value: FiniteDecimal | None = None
    surprise_direction: SurpriseDirection | None = None
    value_unit: str | None = None
    event_value_snapshot: EventValueSnapshot | None = None
    event_surprise: EventSurprise | None = None
    truth_assessment: TruthAssessment
    novelty: UnitInterval
    severity: UnitInterval
    persistence: UnitInterval
    transmission_channels: tuple[str, ...] = Field(min_length=1)
    affected_assets: tuple[str, ...] = Field(min_length=1)
    source_ids: tuple[str, ...] = Field(min_length=1)
    narrative_diffusion: NarrativeDiffusionSnapshot
    market_reflection: MarketReflectionScore
    first_seen_at: UtcDateTime
    confirmed_at: UtcDateTime | None = None
    available_at: UtcDateTime
    created_at: UtcDateTime
    canonical_sha256: str

    @model_validator(mode="after")
    def validate_event(self) -> CanonicalEvent:
        ensure_sha256(self.canonical_sha256, field_name="canonical_sha256")
        cluster_id = self.source_cluster.event_cluster_id
        if self.event_type != self.source_cluster.event_type or self.entities != tuple(
            sorted(set(self.source_cluster.entity_ids))
        ):
            raise ValueError("AQ-CANONICAL-EVENT-CLUSTER-BINDING")
        if (
            self.narrative_diffusion.event_cluster_id != cluster_id
            or self.market_reflection.event_cluster_id != cluster_id
        ):
            raise ValueError("AQ-CANONICAL-EVENT-CONTEXT-CLUSTER-BINDING")
        if (
            self.event_value_snapshot is not None
            and self.event_value_snapshot.event_cluster_id != cluster_id
        ):
            raise ValueError("AQ-CANONICAL-EVENT-VALUE-CLUSTER-BINDING")
        if self.event_surprise is not None and (
            self.event_value_snapshot is None
            or self.event_surprise.event_cluster_id != cluster_id
            or self.event_surprise.value_snapshot_id != self.event_value_snapshot.snapshot_id
            or self.event_surprise.value_snapshot_sha256
            != self.event_value_snapshot.snapshot_sha256
            or self.event_surprise.as_of_time != self.event_value_snapshot.as_of_time
        ):
            raise ValueError("AQ-CANONICAL-EVENT-SURPRISE-BINDING")
        scalar_values = (
            self.actual_value,
            self.expected_value,
            self.whisper_value,
            self.surprise_value,
            self.surprise_direction,
            self.value_unit,
        )
        if self.event_surprise is None:
            if any(value is not None for value in scalar_values):
                raise ValueError("AQ-CANONICAL-EVENT-FORGED-SURPRISE-SCALAR")
        elif scalar_values != (
            self.event_surprise.actual_value,
            self.event_surprise.expected_value,
            self.event_surprise.whisper_value,
            self.event_surprise.surprise_value,
            self.event_surprise.direction,
            self.event_surprise.value_unit,
        ):
            raise ValueError("AQ-CANONICAL-EVENT-SURPRISE-SCALAR-MISMATCH")
        if self.truth_assessment.claim_id not in self.source_cluster.claim_ids:
            raise ValueError("AQ-CANONICAL-EVENT-TRUTH-CLAIM-NOT-IN-CLUSTER")
        cluster_evidence = set(self.source_cluster.supporting_evidence_ids) | set(
            self.source_cluster.contradicting_evidence_ids
        )
        if not set(self.truth_assessment.source_document_ids) <= cluster_evidence:
            raise ValueError("AQ-CANONICAL-EVENT-TRUTH-EVIDENCE-NOT-IN-CLUSTER")
        if not self.first_seen_at <= self.available_at or self.created_at != self.available_at:
            raise ValueError("AQ-CANONICAL-EVENT-TIME-ORDER")
        input_availability = (
            self.source_cluster.last_updated_time,
            self.truth_assessment.available_at,
            self.narrative_diffusion.as_of_time,
            self.market_reflection.as_of_time,
            *(
                (self.event_value_snapshot.as_of_time,)
                if self.event_value_snapshot is not None
                else ()
            ),
            *((self.event_surprise.as_of_time,) if self.event_surprise is not None else ()),
        )
        if any(value > self.available_at for value in input_availability):
            raise ValueError("AQ-CANONICAL-EVENT-INPUT-LOOKAHEAD")
        if self.event_stage is EventClusterStatus.CONFIRMED:
            if self.confirmed_at is None or self.truth_assessment.truth_state not in {
                TruthState.VERIFIED_PRIMARY,
                TruthState.VERIFIED_MULTI_SOURCE,
            }:
                raise ValueError("AQ-CANONICAL-EVENT-CONFIRMATION-TRUTH-BINDING")
        elif (
            self.event_stage
            in {
                EventClusterStatus.RUMOR,
                EventClusterStatus.EMERGING,
                EventClusterStatus.CORROBORATED,
            }
            and self.confirmed_at is not None
        ):
            raise ValueError("AQ-CANONICAL-EVENT-PREMATURE-CONFIRMATION-TIME")
        if (
            self.confirmed_at is not None
            and not self.first_seen_at <= self.confirmed_at <= self.available_at
        ):
            raise ValueError("AQ-CANONICAL-EVENT-CONFIRMATION-TIME-ORDER")
        if self.revision_number == 1 and self.previous_revision_id is not None:
            raise ValueError("AQ-CANONICAL-EVENT-FIRST-REVISION-HAS-PREDECESSOR")
        if self.revision_number > 1 and self.previous_revision_id is None:
            raise ValueError("AQ-CANONICAL-EVENT-LATER-REVISION-MISSING-PREDECESSOR")
        if self.source_ids != tuple(sorted(set(self.source_ids))):
            raise ValueError("AQ-CANONICAL-EVENT-SOURCE-ORDER-OR-DUPLICATE")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"revision_id", "canonical_sha256"})
        )
        if str(self.revision_id) != expected or self.canonical_sha256 != expected:
            raise ValueError("AQ-CANONICAL-EVENT-HASH-MISMATCH")
        return self


class EventDirectionalGate(DomainModel):
    gate_id: ArtifactId
    event_id: EventId
    event_revision_id: ArtifactId
    event_cluster_id: EventClusterId
    market_reflection_id: ArtifactId
    as_of_time: UtcDateTime
    event_stage: EventClusterStatus
    market_reflection_score: UnitInterval | None = None
    high_price_in_threshold: UnitInterval
    market_reflection_quality: QualityState
    directional_candidate_allowed: bool
    risk_overlay_allowed: bool = True
    reason_codes: tuple[str, ...] = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    action: Literal["RESEARCH_PROPOSAL_ONLY"] = "RESEARCH_PROPOSAL_ONLY"
    order_submission_allowed: Literal[False] = False
    gate_sha256: str

    @model_validator(mode="after")
    def validate_gate(self) -> EventDirectionalGate:
        ensure_sha256(self.gate_sha256, field_name="gate_sha256")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("AQ-EVENT-GATE-REASON-ORDER-OR-DUPLICATE")
        stage_allows = self.event_stage is EventClusterStatus.CONFIRMED
        reflection_available = (
            self.market_reflection_quality is QualityState.GOOD
            and self.market_reflection_score is not None
        )
        not_priced = (
            self.market_reflection_score is not None
            and self.market_reflection_score < self.high_price_in_threshold
        )
        expected_allowed = stage_allows and reflection_available and not_priced
        if self.directional_candidate_allowed != expected_allowed:
            raise ValueError("AQ-EVENT-GATE-ALLOWANCE-MISMATCH")
        required_reasons: set[str] = set()
        if not stage_allows:
            required_reasons.add("EVENT_NOT_CONFIRMED")
        if not reflection_available:
            required_reasons.add("MARKET_REFLECTION_INSUFFICIENT")
        if reflection_available and not not_priced:
            required_reasons.add("EVENT_ALREADY_PRICED")
        if expected_allowed:
            required_reasons.add("P05_DIRECTIONAL_RESEARCH_CANDIDATE")
        if not required_reasons <= set(self.reason_codes):
            raise ValueError("AQ-EVENT-GATE-MISSING-REASON")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"gate_id", "gate_sha256"})
        )
        if str(self.gate_id) != expected or self.gate_sha256 != expected:
            raise ValueError("AQ-EVENT-GATE-HASH-MISMATCH")
        return self


DEFAULT_MARKET_REFLECTION_POLICY = MarketReflectionPolicy(
    policy_version="v5-p05-market-reflection-v1",
    required_metrics=(
        MarketReflectionMetric.PRE_CONFIRMATION_PRICE_MOVE,
        MarketReflectionMetric.ABNORMAL_RETURN,
        MarketReflectionMetric.VOLUME_SPIKE,
        MarketReflectionMetric.OPEN_INTEREST_CHANGE,
        MarketReflectionMetric.FUNDING_CHANGE,
        MarketReflectionMetric.BASIS_CHANGE,
        MarketReflectionMetric.CROSS_ASSET_RESPONSE,
        MarketReflectionMetric.NARRATIVE_DIFFUSION,
        MarketReflectionMetric.LIQUIDATION_FLOW,
        MarketReflectionMetric.MARKET_DEPTH_CHANGE,
    ),
    metric_weights={
        MarketReflectionMetric.PRE_CONFIRMATION_PRICE_MOVE: Decimal("0.18"),
        MarketReflectionMetric.ABNORMAL_RETURN: Decimal("0.16"),
        MarketReflectionMetric.VOLUME_SPIKE: Decimal("0.12"),
        MarketReflectionMetric.OPEN_INTEREST_CHANGE: Decimal("0.10"),
        MarketReflectionMetric.FUNDING_CHANGE: Decimal("0.08"),
        MarketReflectionMetric.BASIS_CHANGE: Decimal("0.08"),
        MarketReflectionMetric.CROSS_ASSET_RESPONSE: Decimal("0.08"),
        MarketReflectionMetric.NARRATIVE_DIFFUSION: Decimal("0.08"),
        MarketReflectionMetric.LIQUIDATION_FLOW: Decimal("0.06"),
        MarketReflectionMetric.MARKET_DEPTH_CHANGE: Decimal("0.06"),
    },
    high_price_in_threshold=Decimal("0.80"),
    max_metric_age_seconds=86_400,
)


def build_timed_event_value(
    *,
    event_cluster_id: EventClusterId,
    kind: EventValueKind,
    value: Decimal,
    unit: str,
    observed_at: datetime,
    available_at: datetime,
    source_artifact_id: ArtifactId,
    source_sha256: str,
) -> TimedEventValue:
    observed = ensure_utc(observed_at)
    available = ensure_utc(available_at)
    payload = {
        "event_cluster_id": str(event_cluster_id),
        "kind": kind.value,
        "value": str(value),
        "unit": unit,
        "observed_at": _json_time(observed),
        "available_at": _json_time(available),
        "source_artifact_id": str(source_artifact_id),
        "source_sha256": source_sha256,
    }
    return TimedEventValue(
        value_id=ArtifactId(canonical_sha256(payload)),
        event_cluster_id=event_cluster_id,
        kind=kind,
        value=value,
        unit=unit,
        observed_at=observed,
        available_at=available,
        source_artifact_id=source_artifact_id,
        source_sha256=source_sha256,
    )


def build_event_value_snapshot(
    *,
    event_cluster_id: EventClusterId,
    as_of_time: datetime,
    values: Sequence[TimedEventValue],
) -> EventValueSnapshot:
    as_of = ensure_utc(as_of_time)
    ordered = tuple(sorted(values, key=lambda item: item.kind.value))
    payload = {
        "event_cluster_id": str(event_cluster_id),
        "as_of_time": _json_time(as_of),
        "values": [item.model_dump(mode="json") for item in ordered],
    }
    digest = canonical_sha256(payload)
    return EventValueSnapshot(
        snapshot_id=ArtifactId(digest),
        event_cluster_id=event_cluster_id,
        as_of_time=as_of,
        values=ordered,
        snapshot_sha256=digest,
    )


def calculate_event_surprise(
    snapshot: EventValueSnapshot,
    *,
    materiality_threshold: Decimal,
) -> EventSurprise:
    by_kind = {item.kind: item for item in snapshot.values}
    actual = by_kind.get(EventValueKind.ACTUAL)
    expected = by_kind.get(EventValueKind.CONSENSUS)
    if actual is None or expected is None:
        raise ValueError("AQ-EVENT-SURPRISE-REQUIRES-ACTUAL-CONSENSUS")
    whisper = by_kind.get(EventValueKind.WHISPER)
    surprise = actual.value - expected.value
    direction = (
        SurpriseDirection.MORE_POSITIVE_THAN_EXPECTED
        if surprise > materiality_threshold
        else SurpriseDirection.MORE_NEGATIVE_THAN_EXPECTED
        if surprise < -materiality_threshold
        else SurpriseDirection.AS_EXPECTED
    )
    payload = {
        "event_cluster_id": str(snapshot.event_cluster_id),
        "value_snapshot_id": str(snapshot.snapshot_id),
        "value_snapshot_sha256": snapshot.snapshot_sha256,
        "as_of_time": _json_time(snapshot.as_of_time),
        "actual_value": str(actual.value),
        "expected_value": str(expected.value),
        "whisper_value": str(whisper.value) if whisper is not None else None,
        "surprise_value": str(surprise),
        "whisper_surprise_value": str(actual.value - whisper.value)
        if whisper is not None
        else None,
        "materiality_threshold": str(materiality_threshold),
        "value_unit": actual.unit,
        "direction": direction.value,
    }
    digest = canonical_sha256(payload)
    return EventSurprise(
        surprise_id=ArtifactId(digest),
        event_cluster_id=snapshot.event_cluster_id,
        value_snapshot_id=snapshot.snapshot_id,
        value_snapshot_sha256=snapshot.snapshot_sha256,
        as_of_time=snapshot.as_of_time,
        actual_value=actual.value,
        expected_value=expected.value,
        whisper_value=whisper.value if whisper is not None else None,
        surprise_value=surprise,
        whisper_surprise_value=(actual.value - whisper.value if whisper is not None else None),
        materiality_threshold=materiality_threshold,
        value_unit=actual.unit,
        direction=direction,
        surprise_sha256=digest,
    )


def build_narrative_observation(
    *,
    event_cluster_id: EventClusterId,
    source_id: str,
    independence_group: str,
    platform: str,
    language: str,
    verified_source: bool,
    observed_at: datetime,
    available_at: datetime,
    source_sha256: str,
    kol_source: bool = False,
    news_wire_source: bool = False,
) -> NarrativeDiffusionObservation:
    observed = ensure_utc(observed_at)
    available = ensure_utc(available_at)
    payload = {
        "event_cluster_id": str(event_cluster_id),
        "source_id": source_id,
        "independence_group": independence_group,
        "platform": platform,
        "language": language,
        "verified_source": verified_source,
        "kol_source": kol_source,
        "news_wire_source": news_wire_source,
        "observed_at": _json_time(observed),
        "available_at": _json_time(available),
        "source_sha256": source_sha256,
    }
    return NarrativeDiffusionObservation(
        observation_id=ArtifactId(canonical_sha256(payload)),
        event_cluster_id=event_cluster_id,
        source_id=source_id,
        independence_group=independence_group,
        platform=platform,
        language=language,
        verified_source=verified_source,
        kol_source=kol_source,
        news_wire_source=news_wire_source,
        observed_at=observed,
        available_at=available,
        source_sha256=source_sha256,
    )


def build_narrative_diffusion(
    *,
    event_cluster_id: EventClusterId,
    observations: Sequence[NarrativeDiffusionObservation],
    as_of_time: datetime,
    window_hours: Decimal,
    price_response_at: datetime | None = None,
    price_response_available_at: datetime | None = None,
    price_response_source_sha256: str | None = None,
    volume_response_at: datetime | None = None,
    volume_response_available_at: datetime | None = None,
    volume_response_source_sha256: str | None = None,
) -> NarrativeDiffusionSnapshot:
    as_of = ensure_utc(as_of_time)
    if not observations or window_hours <= 0:
        raise ValueError("AQ-NARRATIVE-DIFFUSION-INPUTS")
    ordered = tuple(
        sorted(observations, key=lambda item: (item.available_at, str(item.observation_id)))
    )
    first = min(ordered, key=lambda item: (item.observed_at, str(item.observation_id)))
    verified = tuple(item for item in ordered if item.verified_source)
    first_verified = (
        min(verified, key=lambda item: (item.observed_at, str(item.observation_id)))
        if verified
        else None
    )
    independent_count = len({item.independence_group for item in ordered})
    platform_count = len({item.platform for item in ordered})
    stage = (
        NarrativePropagationStage.BROAD
        if independent_count >= 4 and platform_count >= 3
        else NarrativePropagationStage.CROSS_PLATFORM
        if independent_count >= 2 and platform_count >= 2
        else NarrativePropagationStage.EMERGING
    )
    price_at = ensure_utc(price_response_at) if price_response_at is not None else None
    price_available = (
        ensure_utc(price_response_available_at) if price_response_available_at is not None else None
    )
    volume_at = ensure_utc(volume_response_at) if volume_response_at is not None else None
    volume_available = (
        ensure_utc(volume_response_available_at)
        if volume_response_available_at is not None
        else None
    )
    payload = {
        "event_cluster_id": str(event_cluster_id),
        "as_of_time": _json_time(as_of),
        "window_hours": str(window_hours),
        "observations": [item.model_dump(mode="json") for item in ordered],
        "first_source_id": first.source_id,
        "first_verified_source_id": first_verified.source_id if first_verified else None,
        "first_observed_at": _json_time(first.observed_at),
        "first_verified_at": _json_time(first_verified.observed_at) if first_verified else None,
        "independent_source_count": independent_count,
        "platform_count": platform_count,
        "language_count": len({item.language for item in ordered}),
        "kol_count": sum(item.kol_source for item in ordered),
        "news_wire_count": sum(item.news_wire_source for item in ordered),
        "source_velocity_per_hour": str(Decimal(len(ordered)) / window_hours),
        "independent_source_velocity_per_hour": str(Decimal(independent_count) / window_hours),
        "propagation_stage": stage.value,
        "price_response_at": _json_time(price_at) if price_at else None,
        "price_response_available_at": _json_time(price_available) if price_available else None,
        "price_response_source_sha256": price_response_source_sha256,
        "volume_response_at": _json_time(volume_at) if volume_at else None,
        "volume_response_available_at": _json_time(volume_available) if volume_available else None,
        "volume_response_source_sha256": volume_response_source_sha256,
        "price_response_lag_seconds": (
            str(Decimal(str((price_at - first.observed_at).total_seconds()))) if price_at else None
        ),
        "volume_response_lag_seconds": (
            str(Decimal(str((volume_at - first.observed_at).total_seconds())))
            if volume_at
            else None
        ),
    }
    digest = canonical_sha256(payload)
    return NarrativeDiffusionSnapshot(
        diffusion_id=ArtifactId(digest),
        event_cluster_id=event_cluster_id,
        as_of_time=as_of,
        window_hours=window_hours,
        observations=ordered,
        first_source_id=first.source_id,
        first_verified_source_id=first_verified.source_id if first_verified else None,
        first_observed_at=first.observed_at,
        first_verified_at=first_verified.observed_at if first_verified else None,
        independent_source_count=independent_count,
        platform_count=platform_count,
        language_count=len({item.language for item in ordered}),
        kol_count=sum(item.kol_source for item in ordered),
        news_wire_count=sum(item.news_wire_source for item in ordered),
        source_velocity_per_hour=Decimal(len(ordered)) / window_hours,
        independent_source_velocity_per_hour=Decimal(independent_count) / window_hours,
        propagation_stage=stage,
        price_response_at=price_at,
        price_response_available_at=price_available,
        price_response_source_sha256=price_response_source_sha256,
        volume_response_at=volume_at,
        volume_response_available_at=volume_available,
        volume_response_source_sha256=volume_response_source_sha256,
        price_response_lag_seconds=(
            Decimal(str((price_at - first.observed_at).total_seconds())) if price_at else None
        ),
        volume_response_lag_seconds=(
            Decimal(str((volume_at - first.observed_at).total_seconds())) if volume_at else None
        ),
        diffusion_sha256=digest,
    )


def build_market_reflection_metric(
    *,
    event_cluster_id: EventClusterId,
    metric: MarketReflectionMetric,
    reflection_strength: Decimal,
    observed_at: datetime,
    available_at: datetime,
    source_id: str,
    source_sha256: str,
) -> TimedMarketReflectionMetric:
    observed = ensure_utc(observed_at)
    available = ensure_utc(available_at)
    payload = {
        "event_cluster_id": str(event_cluster_id),
        "metric": metric.value,
        "reflection_strength": str(reflection_strength),
        "observed_at": _json_time(observed),
        "available_at": _json_time(available),
        "source_id": source_id,
        "source_sha256": source_sha256,
    }
    return TimedMarketReflectionMetric(
        metric_id=ArtifactId(canonical_sha256(payload)),
        event_cluster_id=event_cluster_id,
        metric=metric,
        reflection_strength=reflection_strength,
        observed_at=observed,
        available_at=available,
        source_id=source_id,
        source_sha256=source_sha256,
    )


def calculate_market_reflection(
    *,
    event_cluster_id: EventClusterId,
    metrics: Sequence[TimedMarketReflectionMetric],
    as_of_time: datetime,
    policy: MarketReflectionPolicy = DEFAULT_MARKET_REFLECTION_POLICY,
) -> MarketReflectionScore:
    as_of = ensure_utc(as_of_time)
    ordered = tuple(sorted(metrics, key=lambda item: item.metric.value))
    present = {item.metric for item in ordered}
    missing = tuple(sorted(set(policy.required_metrics) - present, key=lambda item: item.value))
    stale = tuple(
        sorted(
            (
                item.metric_id
                for item in ordered
                if (as_of - item.available_at).total_seconds() > policy.max_metric_age_seconds
            ),
            key=str,
        )
    )
    complete = not missing and not stale
    score = (
        sum(
            (
                item.reflection_strength * policy.metric_weights[item.metric]
                for item in ordered
                if item.metric in policy.metric_weights
            ),
            Decimal("0"),
        )
        if complete
        else None
    )
    payload = {
        "event_cluster_id": str(event_cluster_id),
        "as_of_time": _json_time(as_of),
        "policy": policy.model_dump(mode="json"),
        "metrics": [item.model_dump(mode="json") for item in ordered],
        "missing_metrics": [item.value for item in missing],
        "stale_metric_ids": [str(item) for item in stale],
        "market_reflection_score": str(score) if score is not None else None,
        "already_priced_probability": str(score) if score is not None else None,
        "high_price_in": score is not None and score >= policy.high_price_in_threshold,
        "quality_state": (QualityState.GOOD if complete else QualityState.DEGRADED).value,
        "method": "DEVELOPMENT_WEIGHTED_SCORE_V1",
        "promotion_eligible": False,
    }
    digest = canonical_sha256(payload)
    return MarketReflectionScore(
        reflection_id=ArtifactId(digest),
        event_cluster_id=event_cluster_id,
        as_of_time=as_of,
        policy=policy,
        metrics=ordered,
        missing_metrics=missing,
        stale_metric_ids=stale,
        market_reflection_score=score,
        already_priced_probability=score,
        high_price_in=score is not None and score >= policy.high_price_in_threshold,
        quality_state=QualityState.GOOD if complete else QualityState.DEGRADED,
        reflection_sha256=digest,
    )


_ALLOWED_CANONICAL_TRANSITIONS: Mapping[EventClusterStatus, frozenset[EventClusterStatus]] = {
    EventClusterStatus.RUMOR: frozenset(EventClusterStatus),
    EventClusterStatus.EMERGING: frozenset(
        {
            EventClusterStatus.EMERGING,
            EventClusterStatus.CORROBORATED,
            EventClusterStatus.CONFIRMED,
            EventClusterStatus.DENIED,
            EventClusterStatus.RESOLVED,
        }
    ),
    EventClusterStatus.CORROBORATED: frozenset(
        {
            EventClusterStatus.CORROBORATED,
            EventClusterStatus.CONFIRMED,
            EventClusterStatus.DENIED,
            EventClusterStatus.RESOLVED,
        }
    ),
    EventClusterStatus.CONFIRMED: frozenset(
        {
            EventClusterStatus.CONFIRMED,
            EventClusterStatus.DENIED,
            EventClusterStatus.RESOLVED,
        }
    ),
    EventClusterStatus.DENIED: frozenset({EventClusterStatus.DENIED, EventClusterStatus.RESOLVED}),
    EventClusterStatus.RESOLVED: frozenset({EventClusterStatus.RESOLVED}),
}


def _event_stage(cluster: EventCluster, truth: TruthAssessment) -> EventClusterStatus:
    if cluster.status is EventClusterStatus.RESOLVED:
        return EventClusterStatus.RESOLVED
    if truth.truth_state in {TruthState.CONTRADICTED, TruthState.RETRACTED}:
        return EventClusterStatus.DENIED
    if truth.truth_state in {TruthState.VERIFIED_PRIMARY, TruthState.VERIFIED_MULTI_SOURCE}:
        return EventClusterStatus.CONFIRMED
    if truth.truth_state is TruthState.PARTIALLY_CORROBORATED:
        return EventClusterStatus.CORROBORATED
    return EventClusterStatus.RUMOR


def build_canonical_event(
    *,
    cluster: EventCluster,
    truth_assessment: TruthAssessment,
    narrative_diffusion: NarrativeDiffusionSnapshot,
    market_reflection: MarketReflectionScore,
    as_of_time: datetime,
    jurisdiction: str,
    affected_assets: tuple[str, ...],
    novelty: Decimal,
    severity: Decimal,
    persistence: Decimal,
    transmission_channels: tuple[str, ...],
    event_value_snapshot: EventValueSnapshot | None = None,
    event_surprise: EventSurprise | None = None,
    predecessor: CanonicalEvent | None = None,
) -> CanonicalEvent:
    as_of = ensure_utc(as_of_time)
    if any(
        value > as_of
        for value in (
            cluster.last_updated_time,
            truth_assessment.available_at,
            narrative_diffusion.as_of_time,
            market_reflection.as_of_time,
            *((event_value_snapshot.as_of_time,) if event_value_snapshot else ()),
            *((event_surprise.as_of_time,) if event_surprise else ()),
        )
    ):
        raise ValueError("AQ-CANONICAL-EVENT-LOOKAHEAD")
    stage = _event_stage(cluster, truth_assessment)
    entities = tuple(sorted(set(cluster.entity_ids)))
    assets = tuple(
        sorted(set(affected_assets) | {item for item in entities if item.startswith("asset:")})
    )
    source_ids = tuple(
        sorted(
            {
                *(str(item) for item in cluster.supporting_evidence_ids),
                *(str(item) for item in cluster.contradicting_evidence_ids),
            }
        )
    )
    event_id = EventId(
        canonical_sha256(
            {
                "event_cluster_id": str(cluster.event_cluster_id),
                "event_type": cluster.event_type,
                "entities": entities,
            }
        )
    )
    revision_number = 1
    previous_revision_id = None
    confirmed_at = cluster.last_updated_time if stage is EventClusterStatus.CONFIRMED else None
    first_seen_at = cluster.first_observed_time
    if predecessor is not None:
        if predecessor.event_id != event_id:
            raise ValueError("AQ-CANONICAL-EVENT-PREDECESSOR-IDENTITY-MISMATCH")
        if stage not in _ALLOWED_CANONICAL_TRANSITIONS[predecessor.event_stage]:
            raise ValueError("AQ-CANONICAL-EVENT-ILLEGAL-STATE-REGRESSION")
        if as_of <= predecessor.available_at:
            raise ValueError("AQ-CANONICAL-EVENT-REVISION-TIME-NOT-INCREASING")
        revision_number = predecessor.revision_number + 1
        previous_revision_id = predecessor.revision_id
        first_seen_at = predecessor.first_seen_at
        confirmed_at = predecessor.confirmed_at or confirmed_at
    available_at = max(
        cluster.last_updated_time,
        truth_assessment.available_at,
        narrative_diffusion.as_of_time,
        market_reflection.as_of_time,
        *((event_value_snapshot.as_of_time,) if event_value_snapshot else ()),
        *((event_surprise.as_of_time,) if event_surprise else ()),
    )
    surprise = event_surprise
    payload = {
        "event_id": str(event_id),
        "previous_revision_id": str(previous_revision_id) if previous_revision_id else None,
        "revision_number": revision_number,
        "source_cluster": cluster.model_dump(mode="json"),
        "event_type": cluster.event_type,
        "event_stage": stage.value,
        "entities": entities,
        "assets": assets,
        "jurisdiction": jurisdiction,
        "actual_value": str(surprise.actual_value) if surprise else None,
        "expected_value": str(surprise.expected_value) if surprise else None,
        "whisper_value": str(surprise.whisper_value)
        if surprise and surprise.whisper_value is not None
        else None,
        "surprise_value": str(surprise.surprise_value) if surprise else None,
        "surprise_direction": surprise.direction.value if surprise else None,
        "value_unit": surprise.value_unit if surprise else None,
        "event_value_snapshot": event_value_snapshot.model_dump(mode="json")
        if event_value_snapshot
        else None,
        "event_surprise": surprise.model_dump(mode="json") if surprise else None,
        "truth_assessment": truth_assessment.model_dump(mode="json"),
        "novelty": str(novelty),
        "severity": str(severity),
        "persistence": str(persistence),
        "transmission_channels": tuple(sorted(set(transmission_channels))),
        "affected_assets": tuple(sorted(set(affected_assets))),
        "source_ids": source_ids,
        "narrative_diffusion": narrative_diffusion.model_dump(mode="json"),
        "market_reflection": market_reflection.model_dump(mode="json"),
        "first_seen_at": _json_time(first_seen_at),
        "confirmed_at": _json_time(confirmed_at) if confirmed_at else None,
        "available_at": _json_time(available_at),
        "created_at": _json_time(available_at),
    }
    digest = canonical_sha256(payload)
    return CanonicalEvent(
        event_id=event_id,
        revision_id=ArtifactId(digest),
        previous_revision_id=previous_revision_id,
        revision_number=revision_number,
        source_cluster=cluster,
        event_type=cluster.event_type,
        event_stage=stage,
        entities=entities,
        assets=assets,
        jurisdiction=jurisdiction,
        actual_value=surprise.actual_value if surprise else None,
        expected_value=surprise.expected_value if surprise else None,
        whisper_value=surprise.whisper_value if surprise else None,
        surprise_value=surprise.surprise_value if surprise else None,
        surprise_direction=surprise.direction if surprise else None,
        value_unit=surprise.value_unit if surprise else None,
        event_value_snapshot=event_value_snapshot,
        event_surprise=surprise,
        truth_assessment=truth_assessment,
        novelty=novelty,
        severity=severity,
        persistence=persistence,
        transmission_channels=tuple(sorted(set(transmission_channels))),
        affected_assets=tuple(sorted(set(affected_assets))),
        source_ids=source_ids,
        narrative_diffusion=narrative_diffusion,
        market_reflection=market_reflection,
        first_seen_at=first_seen_at,
        confirmed_at=confirmed_at,
        available_at=available_at,
        created_at=available_at,
        canonical_sha256=digest,
    )


def build_event_directional_gate(
    *,
    event: CanonicalEvent,
    as_of_time: datetime,
) -> EventDirectionalGate:
    as_of = ensure_utc(as_of_time)
    if event.available_at > as_of or event.market_reflection.as_of_time > as_of:
        raise ValueError("AQ-EVENT-GATE-LOOKAHEAD")
    reflection = event.market_reflection
    reasons: set[str] = set()
    if event.event_stage is not EventClusterStatus.CONFIRMED:
        reasons.add("EVENT_NOT_CONFIRMED")
    reflection_available = (
        reflection.quality_state is QualityState.GOOD
        and reflection.market_reflection_score is not None
    )
    if not reflection_available:
        reasons.add("MARKET_REFLECTION_INSUFFICIENT")
    if reflection_available and reflection.high_price_in:
        reasons.add("EVENT_ALREADY_PRICED")
    allowed = not reasons
    if allowed:
        reasons.add("P05_DIRECTIONAL_RESEARCH_CANDIDATE")
    payload = {
        "event_id": str(event.event_id),
        "event_revision_id": str(event.revision_id),
        "event_cluster_id": str(event.source_cluster.event_cluster_id),
        "market_reflection_id": str(reflection.reflection_id),
        "as_of_time": _json_time(as_of),
        "event_stage": event.event_stage.value,
        "market_reflection_score": (
            str(reflection.market_reflection_score)
            if reflection.market_reflection_score is not None
            else None
        ),
        "high_price_in_threshold": str(reflection.policy.high_price_in_threshold),
        "market_reflection_quality": reflection.quality_state.value,
        "directional_candidate_allowed": allowed,
        "risk_overlay_allowed": True,
        "reason_codes": tuple(sorted(reasons)),
        "policy_version": reflection.policy.policy_version,
        "action": "RESEARCH_PROPOSAL_ONLY",
        "order_submission_allowed": False,
    }
    digest = canonical_sha256(payload)
    return EventDirectionalGate(
        gate_id=ArtifactId(digest),
        event_id=event.event_id,
        event_revision_id=event.revision_id,
        event_cluster_id=event.source_cluster.event_cluster_id,
        market_reflection_id=reflection.reflection_id,
        as_of_time=as_of,
        event_stage=event.event_stage,
        market_reflection_score=reflection.market_reflection_score,
        high_price_in_threshold=reflection.policy.high_price_in_threshold,
        market_reflection_quality=reflection.quality_state,
        directional_candidate_allowed=allowed,
        risk_overlay_allowed=True,
        reason_codes=tuple(sorted(reasons)),
        policy_version=reflection.policy.policy_version,
        gate_sha256=digest,
    )
