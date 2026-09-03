"""Generate or verify deterministic P10 global event-intelligence evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

import polars as pl

from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.provider_registry import ProviderRegistry, SourcePolicyRegistry
from aegisquant.domain.identifiers import ProviderId, SourcePolicyId
from aegisquant.domain.intelligence import (
    EventClusterStatus,
    ForecastHorizon,
    NarrativeState,
    RightsState,
)
from aegisquant.intelligence.committee import EvidenceClaim, ExpertFinding, ExpertRole
from aegisquant.intelligence.world.events import (
    CommitteePath,
    EventAuditBundle,
    NarrativeObservation,
    active_learning_queue,
    build_event_audit_bundle,
    build_narrative_state,
    build_repost_families,
    link_cross_platform_entities,
    next_event_state,
    normalize_revision,
    record_translation,
    run_committee_path,
    summarize_independent_evidence,
)
from aegisquant.intelligence.world.fusion import (
    AblationPrediction,
    AblationView,
    FusionFeature,
    TimedFusionFeature,
    build_feature_snapshot,
    fuse_event_market_impact,
    run_same_budget_ablation,
)
from aegisquant.intelligence.world.models import (
    AnnotationLabel,
    ClaimEvidence,
    ContentRevision,
    EvidenceRelation,
    HumanAnnotation,
    OntologyVersion,
    RuntimeSourceState,
    SourceCredibilityProfile,
    SourceUsePolicy,
    UsePermission,
    WorldSource,
)
from aegisquant.intelligence.world.replay import (
    EngagementPoint,
    EventRadarRow,
    EventReplayRow,
    EvidenceGraphRow,
    NarrativeMonitorRow,
    ReplayEvidence,
    SourceIncrementalMetrics,
    SourceMonitorRow,
    WorldIntelligenceReadModels,
    audit_future_engagement,
    audit_pretrend_and_placebo,
    evaluate_source_increment,
    replay_content_as_of,
    run_latency_stress,
)
from aegisquant.intelligence.world.sources import (
    WORLD_ENDPOINTS,
    build_world_request,
    default_social_catalog,
    gdelt_discover_originals,
    manifest_dune_result,
    official_source_catalog,
    parse_alfred_observations,
    parse_coin_metrics,
    parse_defillama_chain_tvl,
    plan_cursor_gap,
    plan_intelligence_degradation,
    register_dune_query,
    select_alfred_vintage,
)

ROOT: Final = Path(__file__).resolve().parents[1]
DATA: Final = ROOT / "reports/data"
INTELLIGENCE: Final = ROOT / "reports/intelligence"
READ_MODELS: Final = INTELLIGENCE / "read_models"
OBSERVED_AT: Final = datetime(2026, 9, 1, 18, tzinfo=UTC)
LEGACY_FIXTURE_HORIZON_COEFFICIENTS: Final = {
    ForecastHorizon.FIVE_MINUTES: Decimal("0.0002"),
    ForecastHorizon.THIRTY_MINUTES: Decimal("0.0005"),
    ForecastHorizon.FOUR_HOURS: Decimal("0.0010"),
    ForecastHorizon.ONE_DAY: Decimal("0.0015"),
    ForecastHorizon.SEVEN_DAYS: Decimal("0.0020"),
}
JSON_OUTPUTS: Final = (
    "P10_SOURCE_CONTRACT_EVIDENCE.json",
    "P10_SOCIAL_SOURCE_EVIDENCE.json",
    "P10_SOURCE_POLICY_EVIDENCE.json",
    "P10_EVENT_GRAPH_EVIDENCE.json",
    "P10_CREDIBILITY_EVIDENCE.json",
    "P10_COMMITTEE_EVIDENCE.json",
    "P10_FUSION_EVIDENCE.json",
    "P10_ABLATION_EVIDENCE.json",
    "P10_REPLAY_EVIDENCE.json",
    "P10_ANNOTATION_EVIDENCE.json",
    "P10_SOURCE_MONITOR_EVIDENCE.json",
    "P10_DEPENDENCY_CONTRACT.json",
)


def _revision(
    *,
    content_id: str,
    revision: int,
    text: str | None,
    available_at: datetime,
    source_family_id: str,
    deleted_at: datetime | None = None,
) -> ContentRevision:
    hash_input = text if text is not None else f"tombstone:{content_id}:{revision}"
    return ContentRevision(
        content_id=content_id,
        revision=revision,
        provider_id="p10_fixture",
        source_family_id=source_family_id,
        canonical_url=f"https://example.invalid/{content_id}",
        original_language="en",
        published_at=datetime(2026, 9, 1, 15, tzinfo=UTC),
        observed_at=available_at,
        available_at=available_at,
        body_sha256=hashlib.sha256(hash_input.encode()).hexdigest(),
        original_text=text,
        modified_at=available_at if revision > 1 and deleted_at is None else None,
        deleted_at=deleted_at,
        supersedes_revision=revision - 1 if revision > 1 else None,
        policy_id="p10_fixture_policy_v1",
    )


def _committee_findings(*, evidence_id: str, skeptic_abstains: bool) -> tuple[ExpertFinding, ...]:
    findings: list[ExpertFinding] = []
    roles = sorted((role for role in ExpertRole if role is not ExpertRole.ARBITER), key=str)
    for role in roles:
        reasons = (
            ("SOURCE_CONFLICT_REQUIRES_REVIEW",)
            if role is ExpertRole.SKEPTIC and skeptic_abstains
            else ()
        )
        findings.append(
            ExpertFinding(
                role=role,
                claims=(
                    EvidenceClaim(
                        claim_id=f"{role.value.casefold()}-claim",
                        text=f"{role.value} fixture finding",
                        evidence_ids=(evidence_id,),
                        supports=True,
                    ),
                ),
                semantic_confidence=Decimal("0.8"),
                factual_confidence=Decimal("0.7"),
                impact_confidence=Decimal("0.6"),
                directional_score=Decimal("0.2"),
                conflicts=("claim-conflict",) if role is ExpertRole.SKEPTIC else (),
                should_abstain=bool(reasons),
                abstain_reasons=reasons,
            )
        )
    return tuple(findings)


def _fusion_features(asset_id: str) -> tuple[TimedFusionFeature, ...]:
    values = {
        FusionFeature.PRICE_RETURN: Decimal("0.20"),
        FusionFeature.BOOK_IMBALANCE: Decimal("0.10"),
        FusionFeature.OPEN_INTEREST_DELTA: Decimal("0.05"),
        FusionFeature.FUNDING_RATE: Decimal("0.02"),
        FusionFeature.BASIS: Decimal("0.03"),
        FusionFeature.ONCHAIN_FLOW: Decimal("0.15"),
    }
    return tuple(
        TimedFusionFeature(
            asset_id=asset_id,
            feature=feature,
            value=value,
            event_time=OBSERVED_AT - timedelta(minutes=10),
            available_at=OBSERVED_AT - timedelta(minutes=5),
            source_id="p10_fixture",
            source_hash=canonical_sha256(
                {"asset_id": asset_id, "feature": feature.value, "value": str(value)}
            ),
        )
        for feature, value in values.items()
    )


def _build_source_contract_evidence() -> tuple[
    dict[str, object], dict[str, object], list[dict[str, object]]
]:
    alfred_payload = {
        "observations": [
            {
                "realtime_start": "2026-08-01",
                "realtime_end": "2026-08-31",
                "date": "2026-06-01",
                "value": "100.0",
            },
            {
                "realtime_start": "2026-09-01",
                "realtime_end": "9999-12-31",
                "date": "2026-06-01",
                "value": "101.5",
            },
        ]
    }
    observations = parse_alfred_observations(
        alfred_payload,
        series_id="GDP",
        vintage_available_at={
            date(2026, 8, 1): datetime(2026, 8, 1, 16, tzinfo=UTC),
            date(2026, 9, 1): OBSERVED_AT,
        },
    )
    before = select_alfred_vintage(observations, as_of_time=datetime(2026, 8, 15, tzinfo=UTC))
    after = select_alfred_vintage(observations, as_of_time=OBSERVED_AT)
    coin = parse_coin_metrics(
        {
            "data": [
                {
                    "asset": "btc",
                    "time": "2026-09-01T17:00:00Z",
                    "status": "reviewed",
                    "CapMrktCurUSD": "123.45",
                }
            ]
        },
        metric_names=("CapMrktCurUSD",),
        available_at=OBSERVED_AT,
    )
    llama = parse_defillama_chain_tvl(
        [{"date": 1788282000, "tvl": 42}], chain="Ethereum", available_at=OBSERVED_AT
    )
    query = register_dune_query(
        query_id=42,
        version=1,
        name="stablecoin flow fixture",
        sql="SELECT day, flow FROM stablecoin_flow WHERE chain = {{chain}}",
        parameter_names=("chain",),
        registered_at=OBSERVED_AT,
    )
    dune_result = manifest_dune_result(
        query=query,
        parameters={"chain": "ethereum"},
        execution_id="fixture-execution-1",
        requested_at=OBSERVED_AT,
        available_at=OBSERVED_AT + timedelta(seconds=30),
        rows=({"day": "2026-08-31", "flow": "10"},),
    )
    requests = {
        "fred_alfred": build_world_request(
            WorldSource.FRED_ALFRED,
            "series_observations",
            {"series_id": "GDP", "file_type": "json", "output_type": 2},
        ),
        "coin_metrics": build_world_request(
            WorldSource.COIN_METRICS,
            "asset_metrics",
            {"assets": "btc", "metrics": "CapMrktCurUSD"},
        ),
        "dune": build_world_request(
            WorldSource.DUNE,
            "execute_saved_query",
            {"query_id": 42, "query_parameters": "registered-manifest"},
        ),
        "defillama": build_world_request(WorldSource.DEFILLAMA, "chains"),
    }
    source_payload: dict[str, object] = {
        "schema_version": "p10-source-contract-evidence-v1",
        "fixture_only": True,
        "network_requests_performed": 0,
        "credentials_requested_or_stored": False,
        "requests": {key: value.model_dump(mode="json") for key, value in requests.items()},
        "alfred_observations": [item.model_dump(mode="json") for item in observations],
        "alfred_before_revision": [item.model_dump(mode="json") for item in before],
        "alfred_after_revision": [item.model_dump(mode="json") for item in after],
        "future_revision_leakage": False,
        "coin_metrics": [item.model_dump(mode="json") for item in coin],
        "defillama": [item.model_dump(mode="json") for item in llama],
        "community_rate_limit": "10 requests per 6 seconds per IP; 10 parallel",
        "free_and_pro_api_bases_mixed": False,
    }
    dune_payload: dict[str, object] = {
        "schema_version": "p10-dune-registry-v1",
        "query": query.model_dump(mode="json"),
        "write_sql_allowed": False,
    }
    result_rows = [cast("dict[str, object]", dune_result.model_dump(mode="json"))]
    return source_payload, dune_payload, result_rows


def _build_event_evidence() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    NarrativeState,
    EventAuditBundle,
]:
    original = _revision(
        content_id="post-0",
        revision=1,
        text="SEC approves Bitcoin ETF application",
        available_at=OBSERVED_AT,
        source_family_id="official-family",
    )
    normalized = normalize_revision(original)
    translation = record_translation(
        content=normalized,
        translated_text="美国证券交易委员会批准比特币 ETF 申请",
        target_language="zh",
        model_provider="local-fixture",
        model_version="translation-fixture-v1",
        procedure_version="p10-translation-audit-v1",
        confidence=Decimal("0.9"),
        human_reviewed=True,
        created_at=OBSERVED_AT,
    )
    documents = [normalized]
    for index in range(1, 100):
        item = _revision(
            content_id=f"post-{index}",
            revision=1,
            text="SEC approves Bitcoin ETF application",
            available_at=OBSERVED_AT,
            source_family_id=f"author-{index}",
        )
        documents.append(normalize_revision(item, upstream_content_id="post-0"))
    repost_families = build_repost_families(documents)
    entities = link_cross_platform_entities(
        normalized, approved_aliases={"ETF": "instrument:SPOT_BTC_ETF"}
    )
    profiles = (
        SourceCredibilityProfile(
            source_identity_id="sec",
            source_family_id="official-family",
            domain_accuracy=Decimal("0.95"),
            correction_quality=Decimal("0.9"),
            officiality=Decimal("1"),
            manipulation_risk=Decimal("0.05"),
            identity_confidence=Decimal("1"),
            as_of_time=OBSERVED_AT,
            evidence_count=10,
        ),
        SourceCredibilityProfile(
            source_identity_id="independent-journal",
            source_family_id="journal-family",
            domain_accuracy=Decimal("0.8"),
            correction_quality=Decimal("0.8"),
            officiality=Decimal("0.2"),
            manipulation_risk=Decimal("0.1"),
            identity_confidence=Decimal("0.9"),
            as_of_time=OBSERVED_AT,
            evidence_count=5,
        ),
    )
    credibility = summarize_independent_evidence(profiles)
    state = next_event_state(
        current=EventClusterStatus.RUMOR,
        evidence=credibility,
        official_confirmation=True,
        official_denial=False,
        resolved=False,
    )
    fast = run_committee_path(
        path=CommitteePath.FAST,
        findings=_committee_findings(evidence_id="evidence-1", skeptic_abstains=False),
        evidence_ids=("evidence-1",),
        policy_ids=("official_web_catalog_v1",),
        model_versions=("committee-p10-v1",),
    )
    deep = run_committee_path(
        path=CommitteePath.DEEP,
        findings=_committee_findings(evidence_id="evidence-1", skeptic_abstains=True),
        evidence_ids=("evidence-1", "conflict-evidence"),
        policy_ids=("official_web_catalog_v1",),
        model_versions=("committee-p10-v1", "skeptic-p10-v1"),
    )
    evidence = (
        ClaimEvidence(
            claim_id="claim-1",
            evidence_id="evidence-1",
            content_id=original.content_id,
            revision=1,
            relation=EvidenceRelation.SUPPORTS,
            source_family_id="official-family",
            available_at=OBSERVED_AT,
            policy_id="official_web_catalog_v1",
            model_version="committee-p10-v1",
        ),
    )
    bundle = build_event_audit_bundle(
        event_cluster_id="event-cluster-1",
        claim_ids=("claim-1",),
        evidence=evidence,
        committee=fast,
        as_of_time=OBSERVED_AT,
    )
    narrative = build_narrative_state(
        topic="spot bitcoin ETF approval",
        entity_ids=entities.canonical_entity_ids,
        observations=(
            NarrativeObservation(
                content_id="post-0",
                source_family_id="official-family",
                author_id="sec",
                platform="official",
                observed_at=OBSERVED_AT,
                sentiment=Decimal("0.4"),
                engagement_delta=5,
            ),
            NarrativeObservation(
                content_id="journal-1",
                source_family_id="journal-family",
                author_id="journal",
                platform="news",
                observed_at=OBSERVED_AT,
                sentiment=Decimal("0.2"),
                engagement_delta=3,
            ),
        ),
        as_of_time=OBSERVED_AT,
        window_hours=Decimal("1"),
    )
    event_payload: dict[str, object] = {
        "schema_version": "p10-event-graph-evidence-v1",
        "normalized_content": normalized.model_dump(mode="json"),
        "translation": translation.model_dump(mode="json"),
        "entity_resolution": entities.model_dump(mode="json"),
        "repost_family": repost_families[0].model_dump(mode="json"),
        "raw_repost_count": 100,
        "independent_repost_family_count": len(repost_families),
        "event_state": state.value,
        "narrative_state": narrative.model_dump(mode="json"),
        "audit_bundle": bundle.model_dump(mode="json"),
    }
    credibility_payload: dict[str, object] = {
        "schema_version": "p10-credibility-evidence-v1",
        "profiles": [item.model_dump(mode="json") for item in profiles],
        "independent_summary": credibility.model_dump(mode="json"),
        "hotness_used_as_independence": False,
        "reposts_used_as_independence": False,
    }
    committee_payload: dict[str, object] = {
        "schema_version": "p10-committee-evidence-v1",
        "fast": fast.model_dump(mode="json"),
        "deep": deep.model_dump(mode="json"),
        "skeptic_required": True,
        "single_post_order_capability": False,
        "llm_order_command_capability": False,
        "live_trading_locked": True,
    }
    return event_payload, credibility_payload, committee_payload, narrative, bundle


def _build_fusion_and_ablation() -> tuple[dict[str, object], dict[str, object]]:
    snapshots = tuple(
        build_feature_snapshot(
            asset_id=asset_id,
            as_of_time=OBSERVED_AT,
            features=_fusion_features(asset_id),
        )
        for asset_id in ("BTC", "ETH")
    )
    impacts = fuse_event_market_impact(
        horizon_coefficients=LEGACY_FIXTURE_HORIZON_COEFFICIENTS,
        event_cluster_id="event-cluster-1",
        event_directional_score=Decimal("0.4"),
        event_confidence=Decimal("0.8"),
        manipulation_risk=Decimal("0.1"),
        snapshots=snapshots,
        evidence_ids=("evidence-1",),
        model_versions=("fusion-p10-v1",),
    )
    manifest_hash = canonical_sha256({"dataset": "p10-ablation-fixture-v1"})
    actual = {"sample-a": Decimal("0.10"), "sample-b": Decimal("-0.10")}
    predicted = {
        AblationView.MARKET_ONLY: (Decimal("0.08"), Decimal("-0.08")),
        AblationView.EVENT_ONLY: (Decimal("0.10"), Decimal("0.10")),
        AblationView.FUSED: (Decimal("0.09"), Decimal("-0.09")),
        AblationView.RISK_ONLY: (Decimal("0"), Decimal("0")),
    }
    predictions: list[AblationPrediction] = []
    for view, values in predicted.items():
        for index, sample_id in enumerate(actual):
            predictions.append(
                AblationPrediction(
                    sample_id=sample_id,
                    view=view,
                    prediction_time=OBSERVED_AT,
                    feature_available_at=OBSERVED_AT,
                    outcome_available_at=OBSERVED_AT + timedelta(hours=1),
                    predicted_return=values[index],
                    actual_return=actual[sample_id],
                    compute_budget_units=1,
                    dataset_manifest_hash=manifest_hash,
                )
            )
    ablation = run_same_budget_ablation(predictions)
    return (
        {
            "schema_version": "p10-fusion-evidence-v1",
            "feature_snapshots": [item.model_dump(mode="json") for item in snapshots],
            "asset_impacts": [item.model_dump(mode="json") for item in impacts],
            "assets": ["BTC", "ETH"],
            "required_features": sorted(item.value for item in FusionFeature),
            "future_features_used": False,
            "order_capability": False,
        },
        {
            "schema_version": "p10-ablation-evidence-v1",
            "predictions": [item.model_dump(mode="json") for item in predictions],
            "report": ablation.model_dump(mode="json"),
            "same_budget": True,
            "oos_fixture": True,
            "positive_and_negative_results_preserved": True,
            "winner_selected_post_hoc": False,
            "alpha_or_profit_claim": False,
        },
    )


def _build_replay_monitor_annotation(
    *, narrative: NarrativeState, bundle: EventAuditBundle
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    first_time = OBSERVED_AT - timedelta(hours=3)
    update_time = OBSERVED_AT - timedelta(hours=2)
    delete_time = OBSERVED_AT + timedelta(hours=1)
    revisions = (
        _revision(
            content_id="content-1",
            revision=1,
            text="Initial event report",
            available_at=first_time,
            source_family_id="family-1",
        ),
        _revision(
            content_id="content-1",
            revision=2,
            text="Corrected event report",
            available_at=update_time,
            source_family_id="family-1",
        ),
        _revision(
            content_id="content-1",
            revision=3,
            text=None,
            available_at=delete_time,
            source_family_id="family-1",
            deleted_at=delete_time,
        ),
    )
    engagement = (
        EngagementPoint(
            snapshot_id="engagement-1",
            content_id="content-1",
            observed_at=OBSERVED_AT - timedelta(minutes=90),
            available_at=OBSERVED_AT - timedelta(minutes=89),
            metrics={"likes": 10},
        ),
        EngagementPoint(
            snapshot_id="engagement-future",
            content_id="content-1",
            observed_at=OBSERVED_AT + timedelta(minutes=30),
            available_at=OBSERVED_AT + timedelta(minutes=31),
            metrics={"likes": 1000},
        ),
    )
    selection = replay_content_as_of(
        revisions=revisions, engagement=engagement, as_of_time=OBSERVED_AT
    )
    future_engagement = audit_future_engagement(
        content_id="content-1", snapshots=engagement, as_of_time=OBSERVED_AT
    )
    latency = run_latency_stress(
        evidence=(
            ReplayEvidence(
                evidence_id="early",
                source_family_id="family-a",
                available_at=OBSERVED_AT - timedelta(minutes=20),
                directional_score=Decimal("0.5"),
            ),
            ReplayEvidence(
                evidence_id="late",
                source_family_id="family-b",
                available_at=OBSERVED_AT - timedelta(seconds=20),
                directional_score=Decimal("-0.5"),
            ),
            ReplayEvidence(
                evidence_id="repost",
                source_family_id="family-a",
                available_at=OBSERVED_AT - timedelta(minutes=15),
                directional_score=Decimal("0.9"),
            ),
        ),
        decision_time=OBSERVED_AT,
    )
    pretrend = audit_pretrend_and_placebo(
        pre_event_returns=(Decimal("0.001"), Decimal("-0.001")),
        post_event_returns=(Decimal("0.02"), Decimal("0.01")),
        placebo_returns=(Decimal("0.001"), Decimal("0")),
    )
    failing_placebo = audit_pretrend_and_placebo(
        pre_event_returns=(Decimal("0.02"), Decimal("0.01")),
        post_event_returns=(Decimal("0.02"), Decimal("0.01")),
        placebo_returns=(Decimal("0.03"), Decimal("0.02")),
    )
    ontology = OntologyVersion(
        ontology_id="crypto-events",
        version="1.0.0",
        event_types=("REGULATORY_ACTION", "SECURITY_INCIDENT", "PROTOCOL_RELEASE"),
        relation_types=("SUPPORTS", "REFUTES"),
        published_at=OBSERVED_AT,
    )
    annotation = HumanAnnotation(
        annotation_id="annotation-1",
        target_id="claim-1",
        ontology_version=ontology.version,
        label=AnnotationLabel.CONFIRMED,
        annotator_id="reviewer-pseudonym-1",
        rationale="Two independent primary records agree.",
        evidence_ids=("evidence-1", "evidence-2"),
        created_at=OBSERVED_AT,
    )
    queue = active_learning_queue(
        (
            ("high", Decimal("0.9"), Decimal("0.8"), Decimal("0.7"), True),
            ("low", Decimal("0.2"), Decimal("0.1"), Decimal("0.1"), True),
            ("denied", Decimal("1"), Decimal("1"), Decimal("1"), False),
        ),
        limit=3,
    )
    source_metrics = (
        SourceIncrementalMetrics(
            source=WorldSource.GDELT,
            event_incremental_value=Decimal("0"),
            risk_incremental_value=Decimal("0.1"),
            coverage=Decimal("0.8"),
            reliability=Decimal("0.7"),
            evaluation_windows=4,
        ),
        SourceIncrementalMetrics(
            source=WorldSource.X,
            event_incremental_value=Decimal("0"),
            risk_incremental_value=Decimal("0"),
            coverage=Decimal("0.1"),
            reliability=Decimal("0.3"),
            evaluation_windows=4,
        ),
    )
    monitor_decisions = tuple(evaluate_source_increment(item) for item in source_metrics)
    replay_payload: dict[str, object] = {
        "schema_version": "p10-event-replay-evidence-v1",
        "revision_ledger": [item.model_dump(mode="json") for item in revisions],
        "engagement_ledger": [item.model_dump(mode="json") for item in engagement],
        "selection": selection.model_dump(mode="json"),
        "future_engagement_audit": future_engagement.model_dump(mode="json"),
        "latency_stress": latency.model_dump(mode="json"),
        "pretrend_placebo_pass": pretrend.model_dump(mode="json"),
        "pretrend_placebo_negative_control": failing_placebo.model_dump(mode="json"),
        "first_revision_preserved": revisions[0].revision == 1,
        "future_revision_used": False,
        "future_engagement_used": False,
    }
    annotation_payload: dict[str, object] = {
        "schema_version": "p10-annotation-evidence-v1",
        "ontology": ontology.model_dump(mode="json"),
        "annotation": annotation.model_dump(mode="json"),
        "active_learning_queue": [item.model_dump(mode="json") for item in queue],
        "policy_denied_candidate_priority": str(queue[-1].priority_score),
    }
    monitor_payload: dict[str, object] = {
        "schema_version": "p10-source-monitor-evidence-v1",
        "metrics": [item.model_dump(mode="json") for item in source_metrics],
        "decisions": [item.model_dump(mode="json") for item in monitor_decisions],
        "risk_only_retention_supported": True,
        "retirement_supported": True,
    }
    read_models = WorldIntelligenceReadModels(
        event_radar=(
            EventRadarRow(
                event_cluster_id="event-cluster-1",
                status=EventClusterStatus.CONFIRMED,
                impact_score=Decimal("0.2"),
                confidence=Decimal("0.7"),
                independent_family_count=2,
                evidence_ids=("evidence-1",),
                as_of_time=OBSERVED_AT,
            ),
        ),
        evidence_graph=tuple(
            EvidenceGraphRow(
                event_cluster_id=str(bundle.event_cluster_id),
                claim_id=item.claim_id,
                evidence_id=item.evidence_id,
                relation=item.relation.value,
                source_family_id=item.source_family_id,
                policy_id=item.policy_id,
                model_version=item.model_version,
                available_at=item.available_at,
            )
            for item in bundle.evidence
        ),
        narrative_monitor=(
            NarrativeMonitorRow(
                narrative_id=str(narrative.narrative_id),
                topic=str(narrative.topic),
                propagation_stage=str(narrative.propagation_stage),
                independent_author_count=int(narrative.independent_author_count),
                coordination_risk=narrative.coordination_risk,
                as_of_time=narrative.as_of_time,
            ),
        ),
        source_monitor=tuple(
            SourceMonitorRow(
                source=decision.source,
                runtime_state=(
                    RuntimeSourceState.READY
                    if decision.source is WorldSource.GDELT
                    else RuntimeSourceState.AWAITING_CREDENTIALS
                ),
                disposition=decision.disposition,
                last_success_at=OBSERVED_AT if decision.source is WorldSource.GDELT else None,
                gap_count=0 if decision.source is WorldSource.GDELT else 1,
                reason_codes=decision.reason_codes,
            )
            for decision in monitor_decisions
        ),
        event_replay=(
            EventReplayRow(
                content_id=selection.content_id,
                as_of_time=selection.as_of_time,
                selected_revision=selection.revision.revision,
                selected_engagement_snapshot_id=(
                    selection.engagement.snapshot_id if selection.engagement else None
                ),
                deleted_as_of=selection.deleted_as_of,
                excluded_future_items=(
                    selection.excluded_future_revision_count
                    + selection.excluded_future_engagement_count
                ),
            ),
        ),
        generated_as_of=OBSERVED_AT,
    )
    return (
        replay_payload,
        annotation_payload,
        monitor_payload,
        cast("dict[str, object]", read_models.model_dump(mode="json")),
    )


def _build_all() -> tuple[dict[str, dict[str, object]], dict[str, object], list[dict[str, object]]]:
    source_payload, dune_query, dune_results = _build_source_contract_evidence()
    official_catalog = official_source_catalog(checked_at=OBSERVED_AT)
    social_catalog = default_social_catalog()
    discovery = gdelt_discover_originals(
        {
            "articles": [
                {
                    "url": "https://www.sec.gov/news/example",
                    "title": "Official filing published",
                    "seendate": "20260901T170000Z",
                }
            ]
        },
        discovered_at=OBSERVED_AT,
    )
    social_payload: dict[str, object] = {
        "schema_version": "p10-social-source-evidence-v1",
        "catalog": [item.model_dump(mode="json") for item in social_catalog],
        "gdelt_discoveries": [item.model_dump(mode="json") for item in discovery],
        "gdelt_is_authoritative_evidence": False,
        "bluesky_v2_path": WORLD_ENDPOINTS[WorldSource.BLUESKY]["jetstream_v2"].path_template,
        "bluesky_v2_checkpoint": "seq",
        "bluesky_v1_legacy_fallback": True,
        "x_zero_latency_assumed": False,
        "telegram_mtproto_or_user_session_used": False,
        "youtube_unauthorized_transcript_collected": False,
        "github_api_version": "2026-03-10",
        "cursor_gap": plan_cursor_gap(
            source=WorldSource.BLUESKY,
            expected_cursor=10,
            observed_cursor=15,
            detected_at=OBSERVED_AT,
            earliest_recoverable_at=OBSERVED_AT - timedelta(hours=1),
        ).model_dump(mode="json"),
        "degradation": plan_intelligence_degradation(
            source=WorldSource.X,
            source_state=RuntimeSourceState.AWAITING_CREDENTIALS,
            llm_available=False,
            cache_available_at=OBSERVED_AT - timedelta(hours=1),
            as_of_time=OBSERVED_AT,
        ).model_dump(mode="json"),
        "credentials_requested_or_stored": False,
        "network_requests_performed": 0,
    }
    policies = (
        SourceUsePolicy(
            policy_id="official-public-v1",
            source=WorldSource.OFFICIAL,
            rights_state=RightsState.ALLOWED,
            raw_local_storage=UsePermission.LOCAL_ONLY,
            cloud_inference=UsePermission.PROHIBITED,
            embedding=UsePermission.LOCAL_ONLY,
            training=UsePermission.PROHIBITED,
            fine_tuning=UsePermission.PROHIBITED,
            display=UsePermission.ALLOWED,
            export=UsePermission.PROHIBITED,
            deletion_sync_required=True,
            revision_sync_required=True,
            retention_days=30,
            approved_scopes=("public_metadata",),
            checked_at=OBSERVED_AT,
        ),
        SourceUsePolicy(
            policy_id="unknown-deny-sensitive-v1",
            source=WorldSource.REDDIT,
            rights_state=RightsState.UNKNOWN,
            raw_local_storage=UsePermission.PROHIBITED,
            cloud_inference=UsePermission.PROHIBITED,
            embedding=UsePermission.PROHIBITED,
            training=UsePermission.PROHIBITED,
            fine_tuning=UsePermission.PROHIBITED,
            display=UsePermission.PROHIBITED,
            export=UsePermission.PROHIBITED,
            deletion_sync_required=True,
            revision_sync_required=True,
            retention_days=0,
            approved_scopes=(),
            checked_at=OBSERVED_AT,
        ),
    )
    provider_registry = ProviderRegistry.from_yaml(ROOT / "data/catalogs/provider_registry.yaml")
    policy_registry = SourcePolicyRegistry.from_yaml(
        ROOT / "data/catalogs/source_policy_registry.yaml"
    )
    enabled_public: list[str] = []
    for provider_id, policy_id in (
        ("coin_metrics_community", "coin_metrics_community_v1"),
        ("defillama_public", "defillama_public_v1"),
        ("official_web_catalog", "official_web_catalog_v1"),
    ):
        policy = policy_registry.get(SourcePolicyId(policy_id))
        enabled_public.append(
            str(provider_registry.require_collection(ProviderId(provider_id), policy).provider_id)
        )
    policy_payload: dict[str, object] = {
        "schema_version": "p10-source-policy-evidence-v1",
        "policies": [item.model_dump(mode="json") for item in policies],
        "enabled_public_providers": enabled_public,
        "awaiting_credentials": [
            "fred_alfred",
            "dune_official",
            "x_official",
            "telegram_bot",
            "youtube_official",
        ],
        "disabled_by_policy": ["reddit_disabled", "discord_disabled"],
        "foundation_model_training_allowed": False,
        "plaintext_secrets_stored": False,
        "live_trading_locked": True,
    }
    event, credibility, committee, narrative, bundle = _build_event_evidence()
    fusion, ablation = _build_fusion_and_ablation()
    replay, annotation, monitor, read_models = _build_replay_monitor_annotation(
        narrative=narrative, bundle=bundle
    )
    dependency_payload: dict[str, object] = {
        "schema_version": "p10-dependency-contract-v1",
        "python_runtime": ".".join(map(str, sys.version_info[:3])),
        "versions": {
            name: importlib.metadata.version(name) for name in ("polars", "pydantic", "PyYAML")
        },
        "new_runtime_dependencies_added": False,
        "external_network_used_for_evidence": False,
        "secrets_used": False,
        "live_trading_locked": True,
    }
    payloads: dict[str, dict[str, object]] = {
        "P10_SOURCE_CONTRACT_EVIDENCE.json": source_payload,
        "P10_SOCIAL_SOURCE_EVIDENCE.json": social_payload,
        "P10_SOURCE_POLICY_EVIDENCE.json": policy_payload,
        "P10_EVENT_GRAPH_EVIDENCE.json": event,
        "P10_CREDIBILITY_EVIDENCE.json": credibility,
        "P10_COMMITTEE_EVIDENCE.json": committee,
        "P10_FUSION_EVIDENCE.json": fusion,
        "P10_ABLATION_EVIDENCE.json": ablation,
        "P10_REPLAY_EVIDENCE.json": replay,
        "P10_ANNOTATION_EVIDENCE.json": annotation,
        "P10_SOURCE_MONITOR_EVIDENCE.json": monitor,
        "P10_DEPENDENCY_CONTRACT.json": dependency_payload,
    }
    dune_results_payload: dict[str, object] = {
        "schema_version": "p10-dune-result-manifests-v1",
        "manifests": dune_results,
    }
    intelligence_payload: dict[str, object] = {
        "DUNE_QUERY_REGISTRY.json": dune_query,
        "DUNE_RESULT_MANIFESTS.json": dune_results_payload,
        "P10_READ_MODELS.json": read_models,
    }
    official_rows = [
        cast("dict[str, object]", item.model_dump(mode="json")) for item in official_catalog
    ]
    return payloads, intelligence_payload, official_rows


def _read_model_outputs(read_models: dict[str, object]) -> dict[str, object]:
    return {
        "EVENT_RADAR.json": read_models["event_radar"],
        "EVIDENCE_GRAPH.json": read_models["evidence_graph"],
        "NARRATIVE_MONITOR.json": read_models["narrative_monitor"],
        "SOURCE_MONITOR.json": read_models["source_monitor"],
        "EVENT_REPLAY.json": read_models["event_replay"],
    }


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    pl.DataFrame(rows, orient="row").write_parquet(path, compression="zstd", statistics=True)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def generate(*, check: bool) -> None:
    payloads, intelligence_payload, official_rows = _build_all()
    read_outputs = _read_model_outputs(
        cast("dict[str, object]", intelligence_payload["P10_READ_MODELS.json"])
    )
    if check:
        for name, expected in payloads.items():
            path = DATA / name
            if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != expected:
                raise RuntimeError(f"stale P10 evidence: {name}")
        for name, expected in intelligence_payload.items():
            path = INTELLIGENCE / name
            if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != expected:
                raise RuntimeError(f"stale P10 intelligence output: {name}")
        for name, expected in read_outputs.items():
            path = READ_MODELS / name
            if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != expected:
                raise RuntimeError(f"stale P10 read model: {name}")
        catalog_path = INTELLIGENCE / "OFFICIAL_SOURCE_CATALOG.parquet"
        if not catalog_path.is_file() or pl.read_parquet(catalog_path).to_dicts() != official_rows:
            raise RuntimeError("stale P10 official source catalog")
        print("P10 evidence verified: 12 data JSON, 3 intelligence JSON, 5 read models, 1 Parquet")
        return
    DATA.mkdir(parents=True, exist_ok=True)
    INTELLIGENCE.mkdir(parents=True, exist_ok=True)
    READ_MODELS.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        _write_json(DATA / name, payload)
    for name, payload in intelligence_payload.items():
        _write_json(INTELLIGENCE / name, payload)
    for name, payload in read_outputs.items():
        _write_json(READ_MODELS / name, payload)
    _write_parquet(INTELLIGENCE / "OFFICIAL_SOURCE_CATALOG.parquet", official_rows)
    print("P10 evidence generated: 12 data JSON, 3 intelligence JSON, 5 read models, 1 Parquet")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    generate(check=arguments.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
