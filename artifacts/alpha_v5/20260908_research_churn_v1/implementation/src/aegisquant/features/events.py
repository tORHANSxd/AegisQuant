"""Evidence-linked event features using only point-in-time cluster state."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from aegisquant.domain.intelligence import (
    AssertionMode,
    ClaimRecord,
    EventCluster,
    NarrativeState,
    Polarity,
    QualityState,
)
from aegisquant.domain.time import UtcDateTime, assert_point_in_time
from aegisquant.domain.values import canonical_result
from aegisquant.features.models import (
    FeatureDefinition,
    FeatureDType,
    FeatureEntity,
    FeatureValueRecord,
    FeatureVector,
)


def _event_definition(
    feature_id: str, description: str, dtype: FeatureDType, unit: str
) -> FeatureDefinition:
    return FeatureDefinition(
        feature_id=feature_id,
        version="1.0.0",
        description=description,
        entity=FeatureEntity.EVENT,
        dtype=dtype,
        unit=unit,
        inputs=("event_cluster", "claim_records", "narrative_snapshot"),
        formula_reference=f"AegisQuant P07 {feature_id} v1",
        lookback_seconds=0,
        minimum_history=1,
        frequency_seconds=1,
        normalization="none",
        missing_policy="explicit_missing_indicator",
        online_compatible=True,
        owner="intelligence-research",
        tests=("tests/unit/features/test_event_features.py",),
    )


def event_feature_definitions() -> tuple[FeatureDefinition, ...]:
    specifications = (
        (
            "event.is_official",
            "Whether official evidence was available",
            FeatureDType.BOOLEAN,
            "flag",
        ),
        ("event.independent_sources", "Independent source count", FeatureDType.INT64, "count"),
        ("event.type", "Versioned event taxonomy value", FeatureDType.STRING, "category"),
        ("event.novelty", "Credibility-weighted claim novelty", FeatureDType.FLOAT64, "score"),
        (
            "event.stance",
            "Target-entity claim stance, not document sentiment",
            FeatureDType.FLOAT64,
            "score",
        ),
        (
            "event.propagation_speed",
            "Point-in-time posts and engagement velocity",
            FeatureDType.FLOAT64,
            "per_hour",
        ),
        (
            "event.market_reflection",
            "Degree to which price already reflected event",
            FeatureDType.FLOAT64,
            "score",
        ),
        ("event.data_quality", "Point-in-time data quality", FeatureDType.STRING, "state"),
        ("event.credibility", "Cluster credibility", FeatureDType.FLOAT64, "score"),
        ("event.manipulation_risk", "Information manipulation risk", FeatureDType.FLOAT64, "score"),
        ("event.uncertainty", "Event uncertainty", FeatureDType.FLOAT64, "score"),
        (
            "event.official_confirmation_delay",
            "Delay from first observation to official confirmation snapshot",
            FeatureDType.FLOAT64,
            "seconds",
        ),
    )
    return tuple(_event_definition(*item) for item in specifications)


def _stance(claims: tuple[ClaimRecord, ...]) -> Decimal:
    if not claims:
        return Decimal("0")
    numerator = Decimal("0")
    denominator = Decimal("0")
    polarity = {
        Polarity.AFFIRM: Decimal("1"),
        Polarity.NEGATE: Decimal("-1"),
        Polarity.UNCERTAIN: Decimal("0"),
    }
    mode_weight = {
        AssertionMode.FACT: Decimal("1"),
        AssertionMode.FORECAST: Decimal("0.6"),
        AssertionMode.OPINION: Decimal("0.35"),
        AssertionMode.RUMOR: Decimal("0.2"),
        AssertionMode.DENIAL: Decimal("1"),
        AssertionMode.QUESTION: Decimal("0.1"),
    }
    for claim in claims:
        weight = claim.credibility_prior * mode_weight[claim.assertion_mode]
        direction = polarity[claim.polarity]
        if claim.assertion_mode is AssertionMode.DENIAL:
            direction *= Decimal("-1")
        numerator += direction * weight
        denominator += weight
    return Decimal("0") if denominator == 0 else canonical_result(numerator / denominator)


def build_event_feature_vector(
    *,
    cluster: EventCluster,
    cluster_available_time: UtcDateTime,
    claims: Iterable[ClaimRecord],
    narrative: NarrativeState | None,
    as_of_time: UtcDateTime,
    quality_state: QualityState,
    source_dataset_ids: tuple[str, ...],
) -> FeatureVector:
    assert_point_in_time(available_time=cluster_available_time, decision_time=as_of_time)
    assert_point_in_time(available_time=cluster.last_updated_time, decision_time=as_of_time)
    claim_values = tuple(claims)
    expected_claims = {str(value) for value in cluster.claim_ids}
    observed_claims = {str(value.claim_id) for value in claim_values}
    if expected_claims != observed_claims:
        raise ValueError("AQ-EVENT-FEATURE-CLAIM-SNAPSHOT-INCOMPLETE")
    if narrative is not None:
        assert_point_in_time(available_time=narrative.as_of_time, decision_time=as_of_time)

    definitions = {item.feature_id: item.qualified_id for item in event_feature_definitions()}
    novelty = (
        Decimal("0")
        if not claim_values
        else canonical_result(
            sum((claim.novelty_score for claim in claim_values), Decimal("0"))
            / Decimal(len(claim_values))
        )
    )
    propagation_speed = (
        Decimal("0")
        if narrative is None
        else canonical_result(narrative.posts_per_hour + narrative.engagement_velocity_per_hour)
    )
    market_reflection = Decimal("0") if narrative is None else narrative.price_reflection_score
    official_delay = (
        Decimal("0")
        if not cluster.official_confirmation_ids
        else Decimal(str((cluster.last_updated_time - cluster.first_observed_time).total_seconds()))
    )
    raw_values: dict[str, Decimal | int | str | bool] = {
        definitions["event.is_official"]: bool(cluster.official_confirmation_ids),
        definitions["event.independent_sources"]: cluster.independent_source_count,
        definitions["event.type"]: cluster.event_type,
        definitions["event.novelty"]: novelty,
        definitions["event.stance"]: _stance(claim_values),
        definitions["event.propagation_speed"]: propagation_speed,
        definitions["event.market_reflection"]: market_reflection,
        definitions["event.data_quality"]: quality_state.value,
        definitions["event.credibility"]: cluster.credibility_score,
        definitions["event.manipulation_risk"]: cluster.manipulation_risk,
        definitions["event.uncertainty"]: cluster.uncertainty,
        definitions["event.official_confirmation_delay"]: official_delay,
    }
    missing: tuple[str, ...] = ()
    if narrative is None:
        missing = tuple(
            sorted(
                (
                    definitions["event.propagation_speed"],
                    definitions["event.market_reflection"],
                )
            )
        )
        raw_values.pop(definitions["event.propagation_speed"])
        raw_values.pop(definitions["event.market_reflection"])
    return FeatureVector(
        entity_id=str(cluster.event_cluster_id),
        event_time=cluster.first_observed_time,
        available_time=cluster_available_time,
        values=tuple(
            FeatureValueRecord(feature_key=key, value=raw_values[key]) for key in sorted(raw_values)
        ),
        missing_flags=missing,
        source_dataset_ids=tuple(sorted(set(source_dataset_ids))),
    )
