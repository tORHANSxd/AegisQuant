from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    SourceDocumentId,
    SourceIdentityId,
)
from aegisquant.domain.truth import (
    AtomicClaim,
    ClaimSpan,
    ClaimType,
    TemporalRevision,
    TruthAssessment,
    TruthAssessmentScope,
    TruthState,
)
from aegisquant.intelligence.graph import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    GraphEdgeType,
    GraphNodeType,
    build_evidence_graph,
)
from aegisquant.intelligence.truth import (
    partition_claims_as_of,
    select_revisions_as_of,
    select_truth_assessments_as_of,
)

BASE_TIME = datetime(2026, 9, 2, 8, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def revision(
    number: int,
    *,
    available_after: int,
    deleted: bool = False,
    observed_after: int | None = None,
    deleted_after: int | None = None,
) -> TemporalRevision:
    instant = BASE_TIME + timedelta(seconds=available_after)
    observed = BASE_TIME + timedelta(
        seconds=observed_after if observed_after is not None else available_after
    )
    return TemporalRevision(
        source_document_id=SourceDocumentId("doc-1"),
        revision_id=ArtifactId(f"revision-{number}"),
        previous_revision_id=(ArtifactId(f"revision-{number - 1}") if number > 1 else None),
        revision_number=number,
        content_hash=(HASH_A, HASH_B, HASH_C)[number - 1],
        observed_at=observed,
        effective_at=observed,
        available_at=instant,
        updated_time=observed if number > 1 else None,
        deleted_time=(
            BASE_TIME
            + timedelta(seconds=deleted_after if deleted_after is not None else available_after)
            if deleted
            else None
        ),
    )


def claim(
    claim_id: str,
    *,
    revision_number: int,
    claim_type: ClaimType,
    available_after: int,
    text: str,
) -> AtomicClaim:
    instant = BASE_TIME + timedelta(seconds=available_after)
    return AtomicClaim(
        claim_id=ClaimId(claim_id),
        source_document_id=SourceDocumentId("doc-1"),
        source_identity_id=SourceIdentityId("source-1"),
        revision_id=ArtifactId(f"revision-{revision_number}"),
        claim_type=claim_type,
        original_text=text,
        normalized_text=text.casefold(),
        span=ClaimSpan(start=0, end=len(text), text=text),
        language="zh-CN",
        entity_ids=("asset:BTC",),
        published_time=instant,
        first_seen_time=instant,
        available_at=instant,
        ingested_time=instant,
    )


def assessment(
    source_claim: AtomicClaim,
    *,
    revision_number: int,
    available_after: int,
    graph_hash: str,
) -> TruthAssessment:
    instant = BASE_TIME + timedelta(seconds=available_after)
    return TruthAssessment(
        assessment_id=ArtifactId(f"assessment-{revision_number}"),
        claim_id=source_claim.claim_id,
        claim_type=source_claim.claim_type,
        assessment_scope=TruthAssessmentScope.CLAIM_TRUTH,
        source_document_ids=(SourceDocumentId("doc-1"),),
        source_revision_ids=(ArtifactId(f"revision-{revision_number}"),),
        source_identity_probability=Decimal("0.99"),
        content_integrity_probability=Decimal("0.98"),
        claim_truth_probability=Decimal("0.8"),
        claim_current_probability=Decimal("0.9"),
        evidence_independence_probability=Decimal("0.5"),
        manipulation_probability=Decimal("0.1"),
        revision_probability=Decimal("0.2"),
        source_compromised_probability=Decimal("0.01"),
        independent_evidence_count=1,
        evidence_dependency_score=Decimal("0.5"),
        contradiction_probability=Decimal("0.1"),
        calibration_bucket="UNVALIDATED_CONTRACT_ONLY",
        truth_state=TruthState.UNVERIFIED,
        reason_codes=("AQ-TRUTH-CONTRACT-NOT-CALIBRATED",),
        evidence_graph_hash=graph_hash,
        model_version="contract-only-v1",
        policy_version="v5-p01",
        assessed_at=instant,
        available_at=instant,
    )


def test_claim_types_are_separated_before_truth_adjudication() -> None:
    source_revision = revision(1, available_after=0)
    fact = claim(
        "fact-1",
        revision_number=1,
        claim_type=ClaimType.FACT,
        available_after=0,
        text="公司已发布公告",
    )
    opinion = claim(
        "opinion-1",
        revision_number=1,
        claim_type=ClaimType.OPINION,
        available_after=0,
        text="这家公司前景真棒",
    )

    partition = partition_claims_as_of(
        revisions=(source_revision,),
        claims=(opinion, fact),
        decision_time=BASE_TIME,
    )
    assert partition.truth_claims == (fact,)
    assert partition.impact_claims == (opinion,)

    invalid = json.loads(
        assessment(
            fact,
            revision_number=1,
            available_after=0,
            graph_hash=HASH_A,
        ).model_dump_json()
    )
    invalid["claim_id"] = str(opinion.claim_id)
    invalid["claim_type"] = ClaimType.OPINION.value
    with pytest.raises(ValidationError, match="AQ-TRUTH-NON-ADJUDICABLE-CLAIM-TYPE"):
        TruthAssessment.model_validate_json(json.dumps(invalid))


def test_future_revision_and_deletion_never_backfill_pit_view() -> None:
    first = revision(1, available_after=0)
    corrected = revision(2, available_after=20)
    deleted = revision(
        3,
        available_after=40,
        observed_after=35,
        deleted_after=30,
        deleted=True,
    )
    first_claim = claim(
        "claim-v1",
        revision_number=1,
        claim_type=ClaimType.FACT,
        available_after=0,
        text="利润增长百分之十",
    )
    corrected_claim = claim(
        "claim-v2",
        revision_number=2,
        claim_type=ClaimType.FACT,
        available_after=20,
        text="利润下降百分之十",
    )
    revisions = (deleted, corrected, first)
    claims = (corrected_claim, first_claim)

    before_correction = partition_claims_as_of(
        revisions=revisions,
        claims=claims,
        decision_time=BASE_TIME + timedelta(seconds=10),
    )
    assert before_correction.truth_claims == (first_claim,)
    assert select_revisions_as_of(revisions, decision_time=BASE_TIME + timedelta(seconds=10)) == (
        first,
    )

    after_correction = partition_claims_as_of(
        revisions=revisions,
        claims=claims,
        decision_time=BASE_TIME + timedelta(seconds=30),
    )
    assert after_correction.truth_claims == (corrected_claim,)

    before_deletion_is_available = partition_claims_as_of(
        revisions=revisions,
        claims=claims,
        decision_time=BASE_TIME + timedelta(seconds=37),
    )
    assert before_deletion_is_available.truth_claims == (corrected_claim,)

    after_deletion = partition_claims_as_of(
        revisions=revisions,
        claims=claims,
        decision_time=BASE_TIME + timedelta(seconds=50),
    )
    assert after_deletion.truth_claims == ()
    assert after_deletion.tombstoned_document_ids == (SourceDocumentId("doc-1"),)


def test_graph_dependency_and_assessment_are_revision_bound() -> None:
    nodes = (
        EvidenceGraphNode(
            node_id="document-primary",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=BASE_TIME,
            independence_group="issuer",
        ),
        EvidenceGraphNode(
            node_id="document-copy",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=BASE_TIME,
            independence_group="issuer",
        ),
        EvidenceGraphNode(
            node_id="fact-1",
            node_type=GraphNodeType.CLAIM,
            available_at_utc=BASE_TIME,
        ),
    )
    edges = (
        EvidenceGraphEdge(
            source_node_id="document-primary",
            target_node_id="fact-1",
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=BASE_TIME,
        ),
        EvidenceGraphEdge(
            source_node_id="document-copy",
            target_node_id="document-primary",
            edge_type=GraphEdgeType.COPIES,
            available_at_utc=BASE_TIME,
        ),
        EvidenceGraphEdge(
            source_node_id="document-copy",
            target_node_id="fact-1",
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=BASE_TIME,
        ),
    )
    graph = build_evidence_graph(as_of_time=BASE_TIME, nodes=nodes, edges=edges)
    assert graph.independent_evidence_count == 1
    assert graph.evidence_dependency_score == Decimal("0.5")
    assert graph.evidence_coverage == Decimal("1")

    source_revision = revision(1, available_after=0)
    fact = claim(
        "fact-1",
        revision_number=1,
        claim_type=ClaimType.FACT,
        available_after=0,
        text="监管机构已经批准",
    )
    truth = assessment(
        fact,
        revision_number=1,
        available_after=1,
        graph_hash=graph.content_sha256(),
    )
    selected = select_truth_assessments_as_of(
        revisions=(source_revision,),
        claims=(fact,),
        assessments=(truth,),
        evidence_graphs=(graph,),
        decision_time=BASE_TIME + timedelta(seconds=2),
    )
    assert selected == (truth,)
    assert truth.content_sha256() == truth.model_copy().content_sha256()

    conflicting = truth.model_copy(update={"claim_truth_probability": Decimal("0.7")})
    with pytest.raises(ValueError, match="AQ-TRUTH-ASSESSMENT-ID-CONFLICT"):
        select_truth_assessments_as_of(
            revisions=(source_revision,),
            claims=(fact,),
            assessments=(truth, conflicting),
            evidence_graphs=(graph,),
            decision_time=BASE_TIME + timedelta(seconds=2),
        )
