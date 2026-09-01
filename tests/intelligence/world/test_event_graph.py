from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.intelligence.world.events import (
    CommitteePath,
    NarrativeObservation,
    NormalizedContent,
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
from aegisquant.intelligence.world.models import (
    ClaimEvidence,
    EvidenceRelation,
    SourceCredibilityProfile,
)
from tests.intelligence.world.helpers import NOW, committee_findings, revision


def test_normalization_and_translation_preserve_auditable_hashes() -> None:
    normalized = normalize_revision(revision())
    translation = record_translation(
        content=normalized,
        translated_text="比特币协议升级已确认",
        target_language="zh",
        model_provider="local-fixture",
        model_version="translation-fixture-v1",
        procedure_version="p10-translation-audit-v1",
        confidence=Decimal("0.9"),
        human_reviewed=True,
        created_at=NOW,
    )
    assert translation.input_sha256 == normalized.original_sha256
    assert translation.output_sha256 != translation.input_sha256
    assert translation.human_reviewed is True
    with pytest.raises(ValidationError, match="languages must differ"):
        record_translation(
            content=normalized,
            translated_text="same language",
            target_language="en",
            model_provider="local-fixture",
            model_version="translation-fixture-v1",
            procedure_version="p10-translation-audit-v1",
            confidence=Decimal("0.5"),
            human_reviewed=False,
            created_at=NOW,
        )


def test_one_hundred_reposts_count_as_one_independent_family() -> None:
    documents: list[NormalizedContent] = []
    for index in range(100):
        item = revision(content_id=f"post-{index}")
        documents.append(normalize_revision(item, upstream_content_id="post-0" if index else None))
    families = build_repost_families(documents)
    assert len(families) == 1
    assert len(families[0].member_content_ids) == 100
    assert families[0].independent_evidence_count == 1
    assert families[0].exact_duplicate_count == 99


def test_near_duplicate_and_cross_platform_entities_are_deterministic() -> None:
    left = normalize_revision(
        revision(content_id="left", text="SEC approves Bitcoin ETF application today")
    )
    right = normalize_revision(
        revision(content_id="right", text="SEC approves Bitcoin ETF application today!")
    )
    families = build_repost_families((left, right), near_duplicate_threshold=Decimal("0.8"))
    linked = link_cross_platform_entities(left, approved_aliases={"ETF": "instrument:SPOT_BTC_ETF"})
    assert len(families) == 1
    assert {"asset:BTC", "regulator:US_SEC", "instrument:SPOT_BTC_ETF"} <= set(
        linked.canonical_entity_ids
    )


def test_high_impact_event_bundle_traces_policy_model_conflict_and_skeptic() -> None:
    decision = run_committee_path(
        path=CommitteePath.FAST,
        findings=committee_findings(),
        evidence_ids=("evidence-1",),
        policy_ids=("fixture-policy-v1",),
        model_versions=("committee-fixture-v1",),
    )
    evidence = (
        ClaimEvidence(
            claim_id="market-claim",
            evidence_id="evidence-1",
            content_id="content-1",
            revision=1,
            relation=EvidenceRelation.SUPPORTS,
            source_family_id="family-1",
            available_at=NOW,
            policy_id="fixture-policy-v1",
            model_version="committee-fixture-v1",
        ),
    )
    bundle = build_event_audit_bundle(
        event_cluster_id="event-1",
        claim_ids=("market-claim",),
        evidence=evidence,
        committee=decision,
        as_of_time=NOW,
    )
    assert bundle.policy_ids == ("fixture-policy-v1",)
    assert bundle.skeptic_claim_ids == ("skeptic-claim",)
    future = evidence[0].model_copy(update={"available_at": datetime(2026, 9, 2, tzinfo=UTC)})
    with pytest.raises(ValidationError, match="future evidence"):
        build_event_audit_bundle(
            event_cluster_id="event-1",
            claim_ids=("market-claim",),
            evidence=(future,),
            committee=decision,
            as_of_time=NOW,
        )


def test_event_state_uses_independent_families_not_profile_count() -> None:
    profiles = tuple(
        SourceCredibilityProfile(
            source_identity_id=f"source-{index}",
            source_family_id="shared-family",
            domain_accuracy=Decimal("0.8"),
            correction_quality=Decimal("0.8"),
            officiality=Decimal("0.1"),
            manipulation_risk=Decimal("0.1"),
            identity_confidence=Decimal("0.8"),
            as_of_time=NOW,
            evidence_count=1,
        )
        for index in range(100)
    )
    summary = summarize_independent_evidence(profiles)
    state = next_event_state(
        current=EventClusterStatus.RUMOR,
        evidence=summary,
        official_confirmation=False,
        official_denial=False,
        resolved=False,
    )
    assert summary.profile_count == 100 and summary.independent_family_count == 1
    assert state is EventClusterStatus.EMERGING


def test_narrative_state_counts_cross_platform_independence_and_coordination() -> None:
    observations = (
        NarrativeObservation(
            content_id="x-1",
            source_family_id="family-a",
            author_id="author-a",
            platform="x",
            observed_at=NOW,
            sentiment=Decimal("0.4"),
            engagement_delta=10,
        ),
        NarrativeObservation(
            content_id="bsky-1",
            source_family_id="family-b",
            author_id="author-b",
            platform="bluesky",
            observed_at=NOW,
            sentiment=Decimal("0.2"),
            engagement_delta=4,
        ),
        NarrativeObservation(
            content_id="x-repost",
            source_family_id="family-a",
            author_id="author-c",
            platform="x",
            observed_at=NOW,
            sentiment=Decimal("0.4"),
            engagement_delta=1,
        ),
    )
    state = build_narrative_state(
        topic="ETF approval",
        entity_ids=("asset:BTC",),
        observations=observations,
        as_of_time=NOW,
        window_hours=Decimal("1"),
    )
    assert state.propagation_stage == "CROSS_PLATFORM"
    assert state.platform_count == 2
    assert state.coordination_risk == Decimal("1") / Decimal("3")
