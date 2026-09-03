"""Evidence search lanes, official denials, rights, revisions, and PIT selection."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    SourceDocumentId,
    SourceId,
    SourceIdentityId,
    SourcePolicyId,
)
from aegisquant.domain.intelligence import Polarity, RightsState
from aegisquant.domain.truth import (
    EvidenceQuery,
    EvidenceQueryKind,
    EvidenceRetrievalHit,
    EvidenceSearchPlan,
)
from aegisquant.intelligence.truth import select_evidence_as_of
from aegisquant.truth.contracts import (
    IdentityFactor,
    OfficialIdentityAssessment,
    OfficialIdentityState,
)

NOW = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
DECISION = NOW + timedelta(minutes=10)


def query(text: str) -> EvidenceQuery:
    return EvidenceQuery(text=text, language="en", end_time=DECISION)


def plan() -> EvidenceSearchPlan:
    return EvidenceSearchPlan(
        search_plan_id=ArtifactId("search-plan:claim-1"),
        claim_id=ClaimId("claim-1"),
        generated_at=NOW,
        available_at=NOW,
        decision_time=DECISION,
        support_queries=(query("issuer confirms acquisition"),),
        contradiction_queries=(query("issuer denies acquisition"),),
        primary_source_queries=(query("site:issuer.example acquisition filing"),),
        official_denial_queries=(query("site:issuer.example acquisition denied"),),
        revision_queries=(query("acquisition correction retraction"),),
        timeline_queries=(query("acquisition announcement timeline"),),
    )


def hit(
    evidence_id: str,
    document_id: str,
    *,
    query_kind: EvidenceQueryKind = EvidenceQueryKind.SUPPORT,
    revision_number: int = 1,
    previous_revision_id: ArtifactId | None = None,
    minute: int = 1,
    deleted_time: datetime | None = None,
    rights_state: RightsState = RightsState.ALLOWED,
    official: bool = False,
    verified: bool = False,
    polarity: Polarity = Polarity.AFFIRM,
) -> EvidenceRetrievalHit:
    search_plan = plan()
    evidence_query = {
        EvidenceQueryKind.SUPPORT: search_plan.support_queries[0],
        EvidenceQueryKind.CONTRADICTION: search_plan.contradiction_queries[0],
        EvidenceQueryKind.PRIMARY_SOURCE: search_plan.primary_source_queries[0],
        EvidenceQueryKind.OFFICIAL_DENIAL: search_plan.official_denial_queries[0],
        EvidenceQueryKind.REVISION: search_plan.revision_queries[0],
        EvidenceQueryKind.TIMELINE: search_plan.timeline_queries[0],
    }[query_kind]
    observed = NOW + timedelta(minutes=minute)
    return EvidenceRetrievalHit(
        evidence_id=ArtifactId(evidence_id),
        search_plan_id=search_plan.search_plan_id,
        claim_id=search_plan.claim_id,
        query_kind=query_kind,
        query_fingerprint_sha256=evidence_query.content_sha256(),
        source_document_id=SourceDocumentId(document_id),
        source_identity_id=SourceIdentityId(f"source:{document_id}"),
        source_policy_id=SourcePolicyId("policy:public-evidence"),
        revision_id=ArtifactId(f"revision:{document_id}:{revision_number}"),
        revision_number=revision_number,
        previous_revision_id=previous_revision_id,
        canonical_url=f"https://evidence.example/{document_id}/{revision_number}",
        content_sha256=hashlib.sha256(f"{document_id}:{revision_number}".encode()).hexdigest(),
        polarity=polarity,
        published_time=NOW,
        observed_time=observed,
        available_at=observed,
        retrieved_at=observed,
        deleted_time=deleted_time,
        rights_state=rights_state,
        is_official_source=official,
        official_identity_verified=verified,
        official_identity_assessment_id=(
            ArtifactId(f"identity-assessment:{document_id}") if verified else None
        ),
        lineage_node_ids=(f"document:{document_id}",),
    )


def identity_assessment(
    evidence_hit: EvidenceRetrievalHit,
    *,
    source_identity_id: SourceIdentityId | None = None,
) -> OfficialIdentityAssessment:
    assert evidence_hit.official_identity_assessment_id is not None
    return OfficialIdentityAssessment(
        assessment_id=evidence_hit.official_identity_assessment_id,
        source_id=SourceId("issuer"),
        source_identity_id=source_identity_id or evidence_hit.source_identity_id,
        registry_entry_id=ArtifactId("registry-entry:issuer:v1"),
        state=OfficialIdentityState.AUTHENTIC,
        matched_factors=(IdentityFactor.API_ENDPOINT,),
        reason_codes=("OFFICIAL_ENDPOINT_MATCH",),
        observed_at=NOW,
        available_at=NOW,
    )


def test_search_plan_requires_six_bounded_non_vote_query_lanes() -> None:
    search_plan = plan()
    assert search_plan.probability_aggregation == "CALIBRATED_MODEL_NOT_AGENT_VOTE"
    assert all(search_plan.query_hashes(kind) for kind in EvidenceQueryKind)

    payload = {
        field_name: getattr(search_plan, field_name)
        for field_name in EvidenceSearchPlan.model_fields
    }
    payload["contradiction_queries"] = ()
    with pytest.raises(ValidationError):
        EvidenceSearchPlan.model_validate(payload)

    payload = dict(payload)
    payload["contradiction_queries"] = search_plan.contradiction_queries
    payload["probability_aggregation"] = "AGENT_VOTE"
    with pytest.raises(ValidationError):
        EvidenceSearchPlan.model_validate(payload)

    payload["probability_aggregation"] = search_plan.probability_aggregation
    payload["timeline_queries"] = (
        EvidenceQuery(
            text="future leak",
            language="en",
            end_time=DECISION + timedelta(seconds=1),
        ),
    )
    with pytest.raises(ValueError, match="AFTER-DECISION"):
        EvidenceSearchPlan.model_validate(payload)


def test_official_denial_requires_verified_official_identity_and_negation() -> None:
    with pytest.raises(ValueError, match="UNVERIFIED-OFFICIAL-DENIAL"):
        hit(
            "hit:denial:spoof",
            "denial-spoof",
            query_kind=EvidenceQueryKind.OFFICIAL_DENIAL,
            polarity=Polarity.NEGATE,
        )

    denial = hit(
        "hit:denial:official",
        "denial-official",
        query_kind=EvidenceQueryKind.OFFICIAL_DENIAL,
        official=True,
        verified=True,
        polarity=Polarity.NEGATE,
    )
    assert denial.official_identity_verified is True
    assessment = identity_assessment(denial)
    assert select_evidence_as_of(
        plan=plan(),
        hits=(denial,),
        official_identity_assessments=(assessment,),
    ) == (denial,)

    with pytest.raises(ValueError, match="ASSESSMENT-MISSING"):
        select_evidence_as_of(plan=plan(), hits=(denial,))
    with pytest.raises(ValueError, match="ASSESSMENT-MISMATCH"):
        select_evidence_as_of(
            plan=plan(),
            hits=(denial,),
            official_identity_assessments=(
                identity_assessment(denial, source_identity_id=SourceIdentityId("spoof")),
            ),
        )


def test_selection_uses_latest_visible_revision_and_filters_future_deleted_and_prohibited() -> None:
    first = hit("hit:doc-a:1", "doc-a")
    second = hit(
        "hit:doc-a:2",
        "doc-a",
        revision_number=2,
        previous_revision_id=first.revision_id,
        minute=5,
    )
    future = hit("hit:future", "future", minute=11)
    deleted = hit(
        "hit:deleted",
        "deleted",
        minute=6,
        deleted_time=NOW + timedelta(minutes=6),
    )
    prohibited = hit(
        "hit:prohibited",
        "prohibited",
        minute=7,
        rights_state=RightsState.PROHIBITED,
    )
    unknown_rights = hit(
        "hit:unknown-rights",
        "unknown-rights",
        minute=8,
        rights_state=RightsState.UNKNOWN,
    )

    selected = select_evidence_as_of(
        plan=plan(),
        hits=(future, prohibited, unknown_rights, first, deleted, second),
    )
    assert selected == (second,)


def test_revision_chain_is_contiguous_and_a_deleted_latest_revision_never_falls_back() -> None:
    first = hit("hit:chain:1", "chain")
    broken = hit(
        "hit:chain:2",
        "chain",
        revision_number=2,
        previous_revision_id=ArtifactId("revision:unrelated:1"),
        minute=5,
    )
    with pytest.raises(ValueError, match="PREDECESSOR-MISMATCH"):
        select_evidence_as_of(plan=plan(), hits=(first, broken))

    tombstone = hit(
        "hit:chain:deleted",
        "chain",
        revision_number=2,
        previous_revision_id=first.revision_id,
        minute=5,
        deleted_time=NOW + timedelta(minutes=5),
    )
    assert select_evidence_as_of(plan=plan(), hits=(first, tombstone)) == ()


def test_selection_rejects_cross_plan_or_unexecuted_query_claims() -> None:
    search_plan = plan()
    wrong_plan = hit("hit:wrong-plan", "wrong-plan").model_copy(
        update={"search_plan_id": ArtifactId("other-plan")}
    )
    with pytest.raises(ValueError, match="PLAN-MISMATCH"):
        select_evidence_as_of(plan=search_plan, hits=(wrong_plan,))

    wrong_query = hit("hit:wrong-query", "wrong-query").model_copy(
        update={"query_fingerprint_sha256": "0" * 64}
    )
    with pytest.raises(ValueError, match="QUERY-MISMATCH"):
        select_evidence_as_of(plan=search_plan, hits=(wrong_query,))
