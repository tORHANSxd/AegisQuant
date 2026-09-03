from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    EventClusterId,
    SourceDocumentId,
)
from aegisquant.domain.intelligence import EventCluster, EventClusterStatus, QualityState
from aegisquant.domain.truth import ClaimType, TruthAssessment, TruthAssessmentScope, TruthState
from aegisquant.intelligence.canonical_events import (
    DEFAULT_MARKET_REFLECTION_POLICY,
    CanonicalEvent,
    EventDirectionalGate,
    EventSurprise,
    EventValueKind,
    MarketReflectionMetric,
    NarrativePropagationStage,
    SurpriseDirection,
    build_canonical_event,
    build_event_directional_gate,
    build_event_value_snapshot,
    build_market_reflection_metric,
    build_narrative_diffusion,
    build_narrative_observation,
    build_timed_event_value,
    calculate_event_surprise,
    calculate_market_reflection,
)
from aegisquant.intelligence.committee import arbitrate
from aegisquant.intelligence.impact import build_event_impact_forecast
from aegisquant.intelligence.world.fusion import (
    FusionFeature,
    TimedFusionFeature,
    build_feature_snapshot,
    fuse_event_market_impact,
)
from tests.p08_helpers import fitted_horizon_coefficients
from tests.p08_intelligence_helpers import committee_findings

BASE = datetime(2026, 9, 2, 12, tzinfo=UTC)
AS_OF = BASE + timedelta(minutes=30)
HASH_A = "a" * 64
HASH_B = "b" * 64


def cluster(
    *, status: EventClusterStatus = EventClusterStatus.CONFIRMED, at: datetime = BASE
) -> EventCluster:
    official = (
        (SourceDocumentId("doc-primary"),)
        if status
        in {EventClusterStatus.CONFIRMED, EventClusterStatus.DENIED, EventClusterStatus.RESOLVED}
        else ()
    )
    return EventCluster(
        event_cluster_id=EventClusterId("event-p05"),
        event_type="MACRO_RELEASE",
        status=status,
        entity_ids=("regulator:US_FED", "asset:BTC"),
        claimed_event_time=at,
        first_observed_time=at,
        last_updated_time=at + timedelta(minutes=10),
        claim_ids=(ClaimId("claim-p05"),),
        supporting_evidence_ids=(
            SourceDocumentId("evidence-1"),
            SourceDocumentId("evidence-2"),
        ),
        contradicting_evidence_ids=(),
        independent_source_count=2,
        official_confirmation_ids=((SourceDocumentId("evidence-1"),) if official else ()),
        credibility_score=Decimal("0.95"),
        manipulation_risk=Decimal("0.02"),
        uncertainty=Decimal("0.10"),
    )


def truth(
    *, state: TruthState = TruthState.VERIFIED_PRIMARY, at: datetime = BASE
) -> TruthAssessment:
    available = at + timedelta(minutes=10)
    return TruthAssessment(
        assessment_id=ArtifactId(f"truth-{state.value.casefold()}"),
        claim_id=ClaimId("claim-p05"),
        claim_type=ClaimType.FACT,
        assessment_scope=TruthAssessmentScope.CLAIM_TRUTH,
        source_document_ids=(SourceDocumentId("evidence-1"), SourceDocumentId("evidence-2")),
        source_revision_ids=(ArtifactId("revision-primary"), ArtifactId("revision-wire")),
        source_identity_probability=Decimal("0.99"),
        content_integrity_probability=Decimal("0.99"),
        claim_truth_probability=Decimal("0.97"),
        claim_current_probability=Decimal("0.98"),
        evidence_independence_probability=Decimal("0.95"),
        manipulation_probability=Decimal("0.02"),
        revision_probability=Decimal("0.03"),
        source_compromised_probability=Decimal("0.01"),
        independent_evidence_count=2,
        evidence_dependency_score=Decimal("0.05"),
        contradiction_probability=Decimal("0.02"),
        calibration_bucket="DEVELOPMENT_P05",
        truth_state=state,
        reason_codes=("AQ-P05-DEVELOPMENT-TRUTH",),
        evidence_graph_hash=HASH_A,
        model_version="truth-p04-development-v1",
        policy_version="v5-p04",
        assessed_at=available,
        available_at=available,
    )


def diffusion(*, at: datetime = BASE):
    observations = (
        build_narrative_observation(
            event_cluster_id=EventClusterId("event-p05"),
            source_id="source-rumor",
            independence_group="rumor-family",
            platform="social",
            language="en",
            verified_source=False,
            kol_source=True,
            observed_at=at,
            available_at=at + timedelta(minutes=1),
            source_sha256=HASH_A,
        ),
        build_narrative_observation(
            event_cluster_id=EventClusterId("event-p05"),
            source_id="source-primary",
            independence_group="primary-family",
            platform="official-web",
            language="zh",
            verified_source=True,
            news_wire_source=True,
            observed_at=at + timedelta(minutes=5),
            available_at=at + timedelta(minutes=6),
            source_sha256=HASH_B,
        ),
    )
    return build_narrative_diffusion(
        event_cluster_id=EventClusterId("event-p05"),
        observations=observations,
        as_of_time=at + timedelta(minutes=30),
        window_hours=Decimal("0.5"),
        price_response_at=at + timedelta(minutes=8),
        price_response_available_at=at + timedelta(minutes=9),
        price_response_source_sha256=HASH_A,
        volume_response_at=at + timedelta(minutes=9),
        volume_response_available_at=at + timedelta(minutes=10),
        volume_response_source_sha256=HASH_B,
    )


def reflection(
    strength: Decimal, *, at: datetime = BASE, omit: MarketReflectionMetric | None = None
):
    metrics = tuple(
        build_market_reflection_metric(
            event_cluster_id=EventClusterId("event-p05"),
            metric=metric,
            reflection_strength=strength,
            observed_at=at + timedelta(minutes=8),
            available_at=at + timedelta(minutes=9),
            source_id=f"market:{metric.value}",
            source_sha256=HASH_A,
        )
        for metric in DEFAULT_MARKET_REFLECTION_POLICY.required_metrics
        if metric is not omit
    )
    return calculate_market_reflection(
        event_cluster_id=EventClusterId("event-p05"),
        metrics=metrics,
        as_of_time=at + timedelta(minutes=30),
    )


def surprise(*, at: datetime = BASE):
    values = tuple(
        build_timed_event_value(
            event_cluster_id=EventClusterId("event-p05"),
            kind=kind,
            value=value,
            unit="percent",
            observed_at=at + timedelta(minutes=index),
            available_at=at + timedelta(minutes=index + 1),
            source_artifact_id=ArtifactId(f"value-source-{kind.value.casefold()}"),
            source_sha256=HASH_B,
        )
        for index, (kind, value) in enumerate(
            (
                (EventValueKind.ACTUAL, Decimal("3.5")),
                (EventValueKind.CONSENSUS, Decimal("3.0")),
                (EventValueKind.WHISPER, Decimal("3.2")),
            ),
            start=5,
        )
    )
    snapshot = build_event_value_snapshot(
        event_cluster_id=EventClusterId("event-p05"),
        as_of_time=at + timedelta(minutes=20),
        values=values,
    )
    return snapshot, calculate_event_surprise(snapshot, materiality_threshold=Decimal("0.1"))


def canonical(
    *,
    state: TruthState = TruthState.VERIFIED_PRIMARY,
    status: EventClusterStatus = EventClusterStatus.CONFIRMED,
    reflection_strength: Decimal = Decimal("0.40"),
    at: datetime = BASE,
    predecessor: CanonicalEvent | None = None,
    omit_reflection_metric: MarketReflectionMetric | None = None,
) -> CanonicalEvent:
    value_snapshot, event_surprise = surprise(at=at)
    return build_canonical_event(
        cluster=cluster(status=status, at=at),
        truth_assessment=truth(state=state, at=at),
        narrative_diffusion=diffusion(at=at),
        market_reflection=reflection(
            reflection_strength,
            at=at,
            omit=omit_reflection_metric,
        ),
        event_value_snapshot=value_snapshot,
        event_surprise=event_surprise,
        as_of_time=at + timedelta(minutes=30),
        jurisdiction="US",
        affected_assets=("asset:BTC",),
        novelty=Decimal("0.8"),
        severity=Decimal("0.6"),
        persistence=Decimal("0.5"),
        transmission_channels=("rates", "liquidity"),
        predecessor=predecessor,
    )


def test_actual_expected_whisper_surprise_is_bound_and_recomputed() -> None:
    event = canonical()
    assert event.actual_value == Decimal("3.5")
    assert event.expected_value == Decimal("3.0")
    assert event.whisper_value == Decimal("3.2")
    assert event.surprise_value == Decimal("0.5")
    assert event.surprise_direction is SurpriseDirection.MORE_POSITIVE_THAN_EXPECTED

    forged = event.model_dump(mode="json")
    forged["surprise_value"] = "9"
    with pytest.raises(ValidationError, match="AQ-CANONICAL-EVENT-SURPRISE-SCALAR-MISMATCH"):
        CanonicalEvent.model_validate_json(json.dumps(forged))


def test_future_surprise_timestamp_cannot_enter_canonical_event() -> None:
    event = canonical()
    snapshot = event.event_value_snapshot
    current_surprise = event.event_surprise
    assert snapshot is not None and current_surprise is not None
    payload = current_surprise.model_dump(mode="json")
    payload["as_of_time"] = (AS_OF + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    digest = canonical_sha256(
        {
            key: value
            for key, value in payload.items()
            if key not in {"surprise_id", "surprise_sha256"}
        }
    )
    payload["surprise_id"] = digest
    payload["surprise_sha256"] = digest
    future_surprise = EventSurprise.model_validate_json(json.dumps(payload))

    with pytest.raises(ValueError, match="AQ-CANONICAL-EVENT-LOOKAHEAD"):
        build_canonical_event(
            cluster=event.source_cluster,
            truth_assessment=event.truth_assessment,
            narrative_diffusion=event.narrative_diffusion,
            market_reflection=event.market_reflection,
            event_value_snapshot=snapshot,
            event_surprise=future_surprise,
            as_of_time=AS_OF,
            jurisdiction="US",
            affected_assets=("asset:BTC",),
            novelty=Decimal("0.8"),
            severity=Decimal("0.6"),
            persistence=Decimal("0.5"),
            transmission_channels=("rates", "liquidity"),
        )


def test_narrative_diffusion_is_pit_and_tracks_first_verified_source() -> None:
    snapshot = diffusion()
    assert snapshot.first_source_id == "source-rumor"
    assert snapshot.first_verified_source_id == "source-primary"
    assert snapshot.propagation_stage is NarrativePropagationStage.CROSS_PLATFORM
    assert snapshot.price_response_lag_seconds == Decimal("480")
    assert snapshot.volume_response_lag_seconds == Decimal("540")

    future = build_narrative_observation(
        event_cluster_id=EventClusterId("event-p05"),
        source_id="future",
        independence_group="future",
        platform="future",
        language="en",
        verified_source=False,
        observed_at=AS_OF + timedelta(seconds=1),
        available_at=AS_OF + timedelta(seconds=2),
        source_sha256=HASH_A,
    )
    with pytest.raises(ValidationError, match="AQ-NARRATIVE-LOOKAHEAD"):
        build_narrative_diffusion(
            event_cluster_id=EventClusterId("event-p05"),
            observations=(future,),
            as_of_time=AS_OF,
            window_hours=Decimal("1"),
        )


def test_market_reflection_is_fail_closed_when_incomplete_or_high() -> None:
    high = reflection(Decimal("0.90"))
    assert high.high_price_in is True
    high_gate = build_event_directional_gate(
        event=canonical(reflection_strength=Decimal("0.90")), as_of_time=AS_OF
    )
    assert high_gate.directional_candidate_allowed is False
    assert "EVENT_ALREADY_PRICED" in high_gate.reason_codes

    incomplete = reflection(Decimal("0.10"), omit=MarketReflectionMetric.MARKET_DEPTH_CHANGE)
    assert incomplete.quality_state is QualityState.DEGRADED
    assert incomplete.market_reflection_score is None
    incomplete_event = canonical(
        reflection_strength=Decimal("0.10"),
        omit_reflection_metric=MarketReflectionMetric.MARKET_DEPTH_CHANGE,
    )
    incomplete_gate = build_event_directional_gate(event=incomplete_event, as_of_time=AS_OF)
    assert incomplete_gate.directional_candidate_allowed is False
    assert "MARKET_REFLECTION_INSUFFICIENT" in incomplete_gate.reason_codes


def test_rumor_never_becomes_directional_candidate() -> None:
    rumor_event = canonical(
        state=TruthState.RUMOR,
        status=EventClusterStatus.RUMOR,
        reflection_strength=Decimal("0.10"),
    )
    gate = build_event_directional_gate(event=rumor_event, as_of_time=AS_OF)
    assert rumor_event.event_stage is EventClusterStatus.RUMOR
    assert gate.directional_candidate_allowed is False
    assert "EVENT_NOT_CONFIRMED" in gate.reason_codes
    assert gate.order_submission_allowed is False


def test_canonical_event_revision_cannot_regress_from_confirmed_to_rumor() -> None:
    first = canonical()
    with pytest.raises(ValueError, match="AQ-CANONICAL-EVENT-ILLEGAL-STATE-REGRESSION"):
        canonical(
            state=TruthState.RUMOR,
            status=EventClusterStatus.RUMOR,
            at=BASE + timedelta(hours=1),
            predecessor=first,
        )


def fusion_snapshot():
    features = tuple(
        TimedFusionFeature(
            asset_id="asset:BTC",
            feature=feature,
            value=Decimal("0.2"),
            event_time=BASE + timedelta(minutes=8),
            available_at=BASE + timedelta(minutes=9),
            source_id=f"market:{feature.value}",
            source_hash=HASH_A,
        )
        for feature in FusionFeature
    )
    return build_feature_snapshot(asset_id="asset:BTC", as_of_time=AS_OF, features=features)


def test_high_price_in_and_legacy_paths_cannot_emit_directional_impact() -> None:
    event = canonical(reflection_strength=Decimal("0.90"))
    gate = build_event_directional_gate(event=event, as_of_time=AS_OF)
    committee = arbitrate(
        findings=committee_findings(),
        allowed_evidence_ids=frozenset({"evidence-1", "evidence-2"}),
    )
    denied = build_event_impact_forecast(
        horizon_coefficients=fitted_horizon_coefficients(),
        cluster=event.source_cluster,
        canonical_event=event,
        directional_gate=gate,
        committee=committee,
        as_of_time=AS_OF,
        affected_exposure_ids=("asset:BTC",),
    )
    assert denied.should_abstain is True
    assert denied.directional_candidate_allowed is False
    assert "EVENT_ALREADY_PRICED" in denied.abstain_reasons
    assert {item.return_distribution.mean for item in denied.horizons.values()} == {Decimal("0")}

    legacy = build_event_impact_forecast(
        horizon_coefficients=fitted_horizon_coefficients(),
        cluster=event.source_cluster,
        committee=committee,
        as_of_time=AS_OF,
        affected_exposure_ids=("asset:BTC",),
        market_already_moved_score=Decimal("0.1"),
    )
    assert legacy.directional_candidate_allowed is False
    assert "CANONICAL_EVENT_GATE_REQUIRED" in legacy.abstain_reasons
    assert {item.return_distribution.mean for item in legacy.horizons.values()} == {Decimal("0")}


def _forge_gate(
    gate: EventDirectionalGate,
    *,
    as_of_time: datetime | None = None,
) -> EventDirectionalGate:
    payload = gate.model_dump(mode="json")
    payload["high_price_in_threshold"] = "1"
    payload["directional_candidate_allowed"] = True
    payload["reason_codes"] = ["P05_DIRECTIONAL_RESEARCH_CANDIDATE"]
    if as_of_time is not None:
        payload["as_of_time"] = as_of_time.isoformat().replace("+00:00", "Z")
    digest = canonical_sha256(
        {key: value for key, value in payload.items() if key not in {"gate_id", "gate_sha256"}}
    )
    payload["gate_id"] = digest
    payload["gate_sha256"] = digest
    return EventDirectionalGate.model_validate_json(json.dumps(payload))


def test_self_consistent_forged_gate_cannot_override_event_reflection_policy() -> None:
    event = canonical(reflection_strength=Decimal("0.90"))
    real_gate = build_event_directional_gate(event=event, as_of_time=AS_OF)
    forged_gate = _forge_gate(real_gate)
    assert forged_gate.directional_candidate_allowed is True
    committee = arbitrate(
        findings=committee_findings(),
        allowed_evidence_ids=frozenset({"evidence-1", "evidence-2"}),
    )
    with pytest.raises(ValueError, match="AQ-IMPACT-DIRECTIONAL-GATE-BINDING"):
        build_event_impact_forecast(
            horizon_coefficients=fitted_horizon_coefficients(),
            cluster=event.source_cluster,
            canonical_event=event,
            directional_gate=forged_gate,
            committee=committee,
            as_of_time=AS_OF,
            affected_exposure_ids=("asset:BTC",),
        )
    with pytest.raises(ValueError, match="AQ-FUSION-DIRECTIONAL-GATE-BINDING"):
        fuse_event_market_impact(
            horizon_coefficients=fitted_horizon_coefficients(),
            event_cluster_id=str(event.source_cluster.event_cluster_id),
            event=event,
            directional_gate=forged_gate,
            event_directional_score=Decimal("0.8"),
            event_confidence=Decimal("0.9"),
            manipulation_risk=Decimal("0.01"),
            snapshots=(fusion_snapshot(),),
            evidence_ids=("evidence-1",),
            model_versions=("p05-development",),
        )


def test_fusion_rejects_gate_timestamp_before_canonical_event_availability() -> None:
    future_event = canonical(
        reflection_strength=Decimal("0.40"),
        at=BASE + timedelta(hours=1),
    )
    real_gate = build_event_directional_gate(
        event=future_event,
        as_of_time=AS_OF + timedelta(hours=1),
    )
    forged_early_gate = _forge_gate(real_gate, as_of_time=AS_OF)
    with pytest.raises(ValueError, match="AQ-FUSION-CANONICAL-EVENT-LOOKAHEAD"):
        fuse_event_market_impact(
            horizon_coefficients=fitted_horizon_coefficients(),
            event_cluster_id=str(future_event.source_cluster.event_cluster_id),
            event=future_event,
            directional_gate=forged_early_gate,
            event_directional_score=Decimal("0.8"),
            event_confidence=Decimal("0.9"),
            manipulation_risk=Decimal("0.01"),
            snapshots=(fusion_snapshot(),),
            evidence_ids=("evidence-1",),
            model_versions=("p05-development",),
        )


def test_confirmed_low_price_in_event_is_only_a_directional_research_candidate() -> None:
    event = canonical(reflection_strength=Decimal("0.40"))
    gate = build_event_directional_gate(event=event, as_of_time=AS_OF)
    assert gate.directional_candidate_allowed is True
    assert gate.action == "RESEARCH_PROPOSAL_ONLY"
    assert gate.order_submission_allowed is False
    committee = arbitrate(
        findings=committee_findings(),
        allowed_evidence_ids=frozenset({"evidence-1", "evidence-2"}),
    )
    impact = build_event_impact_forecast(
        horizon_coefficients=fitted_horizon_coefficients(),
        cluster=event.source_cluster,
        canonical_event=event,
        directional_gate=gate,
        committee=committee,
        as_of_time=AS_OF,
        affected_exposure_ids=("asset:BTC",),
    )
    assert impact.directional_candidate_allowed is True
    assert impact.should_abstain is False
    assert any(item.return_distribution.mean != 0 for item in impact.horizons.values())


def test_fusion_honors_the_same_directional_gate() -> None:
    event = canonical(reflection_strength=Decimal("0.90"))
    gate = build_event_directional_gate(event=event, as_of_time=AS_OF)
    denied = fuse_event_market_impact(
        horizon_coefficients=fitted_horizon_coefficients(),
        event_cluster_id=str(event.source_cluster.event_cluster_id),
        event=event,
        directional_gate=gate,
        event_directional_score=Decimal("0.8"),
        event_confidence=Decimal("0.9"),
        manipulation_risk=Decimal("0.01"),
        snapshots=(fusion_snapshot(),),
        evidence_ids=("evidence-1",),
        model_versions=("p05-development",),
    )[0]
    assert denied.should_abstain is True
    assert denied.directional_candidate_allowed is False
    assert {item.expected_return for item in denied.horizons} == {Decimal("0")}

    legacy = fuse_event_market_impact(
        horizon_coefficients=fitted_horizon_coefficients(),
        event_cluster_id=str(event.source_cluster.event_cluster_id),
        event_directional_score=Decimal("0.8"),
        event_confidence=Decimal("0.9"),
        manipulation_risk=Decimal("0.01"),
        snapshots=(fusion_snapshot(),),
        evidence_ids=("evidence-1",),
        model_versions=("p05-development",),
    )[0]
    assert "CANONICAL_EVENT_GATE_REQUIRED" in legacy.abstain_reasons
    assert {item.expected_return for item in legacy.horizons} == {Decimal("0")}
