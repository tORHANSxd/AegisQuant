from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.identifiers import (
    ClaimId,
    ContentId,
    EventClusterId,
    ModelVersionId,
    NarrativeId,
    SourceDocumentId,
)
from aegisquant.domain.intelligence import (
    AssertionMode,
    ClaimRecord,
    EventCluster,
    EventClusterStatus,
    NarrativeState,
    Polarity,
    QualityState,
)
from aegisquant.features import FeatureVector, build_event_feature_vector, values_by_key

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)


def claim() -> ClaimRecord:
    return ClaimRecord(
        claim_id=ClaimId("claim-1"),
        content_id=ContentId("content-1"),
        claim_text_normalized="issuer confirmed reserve audit",
        subject_entity_ids=("issuer",),
        predicate="confirmed",
        object_entity_ids=("reserve-audit",),
        event_type="reserve_update",
        assertion_mode=AssertionMode.FACT,
        polarity=Polarity.AFFIRM,
        evidence_spans=("confirmed",),
        extractor_versions=(ModelVersionId("extractor-v1"),),
        source_independence_group="official",
        credibility_prior=Decimal("0.9"),
        novelty_score=Decimal("0.8"),
    )


def cluster() -> EventCluster:
    return EventCluster(
        event_cluster_id=EventClusterId("event-1"),
        event_type="reserve_update",
        status=EventClusterStatus.CONFIRMED,
        entity_ids=("issuer",),
        first_observed_time=NOW,
        last_updated_time=NOW + timedelta(seconds=20),
        claim_ids=(ClaimId("claim-1"),),
        supporting_evidence_ids=(SourceDocumentId("doc-1"),),
        contradicting_evidence_ids=(),
        independent_source_count=2,
        official_confirmation_ids=(SourceDocumentId("official-1"),),
        credibility_score=Decimal("0.9"),
        manipulation_risk=Decimal("0.1"),
        uncertainty=Decimal("0.15"),
    )


def narrative(
    *, sentiment: Decimal = Decimal("-0.99"), as_of: datetime | None = None
) -> NarrativeState:
    return NarrativeState(
        narrative_id=NarrativeId("narrative-1"),
        topic="reserve audit",
        entity_ids=("issuer",),
        first_observed_time=NOW,
        as_of_time=as_of or NOW + timedelta(seconds=20),
        propagation_stage="confirmed",
        posts_per_hour=Decimal("3"),
        independent_author_count=2,
        platform_count=2,
        sentiment_score=sentiment,
        contradicting_evidence_count=0,
        engagement_velocity_per_hour=Decimal("4"),
        coordination_risk=Decimal("0.1"),
        price_reflection_score=Decimal("0.25"),
        decay_half_life_hours=Decimal("2"),
        crowding_score=Decimal("0.2"),
    )


def build(narrative_state: NarrativeState | None) -> FeatureVector:
    return build_event_feature_vector(
        cluster=cluster(),
        cluster_available_time=NOW + timedelta(seconds=20),
        claims=(claim(),),
        narrative=narrative_state,
        as_of_time=NOW + timedelta(seconds=30),
        quality_state=QualityState.GOOD,
        source_dataset_ids=("event-v1",),
    )


def test_event_feature_uses_claim_stance_not_document_sentiment() -> None:
    negative_document = build(narrative(sentiment=Decimal("-0.99")))
    positive_document = build(narrative(sentiment=Decimal("0.99")))
    first = values_by_key(negative_document)
    second = values_by_key(positive_document)
    stance_key = next(key for key in first if key.startswith("event.stance"))
    propagation_key = next(key for key in first if key.startswith("event.propagation_speed"))
    assert first[stance_key] == Decimal("1")
    assert first[stance_key] == second[stance_key]
    assert first[propagation_key] == Decimal("7")


def test_event_feature_rejects_incomplete_or_future_snapshots() -> None:
    with pytest.raises(ValueError, match="CLAIM-SNAPSHOT-INCOMPLETE"):
        build_event_feature_vector(
            cluster=cluster(),
            cluster_available_time=NOW + timedelta(seconds=20),
            claims=(),
            narrative=None,
            as_of_time=NOW + timedelta(seconds=30),
            quality_state=QualityState.GOOD,
            source_dataset_ids=("event-v1",),
        )
    with pytest.raises(ValueError, match="AQ-TIME-LOOKAHEAD"):
        build(narrative(as_of=NOW + timedelta(minutes=2)))


def test_missing_narrative_is_explicit_not_fabricated() -> None:
    vector = build(None)
    assert len(vector.missing_flags) == 2
    assert all(key.startswith("event.") for key in vector.missing_flags)
