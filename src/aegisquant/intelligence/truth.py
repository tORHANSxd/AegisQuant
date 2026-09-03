"""Fail-closed point-in-time queries for versioned truth contracts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Self

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ClaimId, SourceDocumentId
from aegisquant.domain.intelligence import RightsState
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.truth import (
    IMPACT_ONLY_CLAIM_TYPES,
    TRUTH_ADJUDICABLE_CLAIM_TYPES,
    AtomicClaim,
    EvidenceRetrievalHit,
    EvidenceSearchPlan,
    TemporalRevision,
    TruthAssessment,
)
from aegisquant.intelligence.graph import EvidenceGraph, GraphNodeType
from aegisquant.truth.contracts import OfficialIdentityAssessment, OfficialIdentityState


class TruthClaimPartition(DomainModel):
    """Auditable PIT snapshot; truth and impact lanes are mutually exclusive."""

    as_of_time: UtcDateTime
    selected_revisions: tuple[TemporalRevision, ...]
    tombstoned_document_ids: tuple[SourceDocumentId, ...]
    truth_claims: tuple[AtomicClaim, ...]
    impact_claims: tuple[AtomicClaim, ...]

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        truth_ids = {item.claim_id for item in self.truth_claims}
        impact_ids = {item.claim_id for item in self.impact_claims}
        if truth_ids & impact_ids:
            raise ValueError("AQ-TRUTH-CLAIM-LANE-OVERLAP")
        if len(truth_ids) != len(self.truth_claims) or len(impact_ids) != len(self.impact_claims):
            raise ValueError("AQ-TRUTH-DUPLICATE-CLAIM-ID")
        if any(item.claim_type not in TRUTH_ADJUDICABLE_CLAIM_TYPES for item in self.truth_claims):
            raise ValueError("AQ-TRUTH-INVALID-TRUTH-LANE")
        if any(item.claim_type not in IMPACT_ONLY_CLAIM_TYPES for item in self.impact_claims):
            raise ValueError("AQ-TRUTH-INVALID-IMPACT-LANE")
        if any(item.available_at > self.as_of_time for item in self.all_claims):
            raise ValueError("AQ-TRUTH-FUTURE-CLAIM-IN-PARTITION")
        if any(item.available_at > self.as_of_time for item in self.selected_revisions):
            raise ValueError("AQ-TRUTH-FUTURE-REVISION-IN-PARTITION")
        return self

    @property
    def all_claims(self) -> tuple[AtomicClaim, ...]:
        return self.truth_claims + self.impact_claims


def select_evidence_as_of(
    *,
    plan: EvidenceSearchPlan,
    hits: tuple[EvidenceRetrievalHit, ...],
    official_identity_assessments: tuple[OfficialIdentityAssessment, ...] = (),
) -> tuple[EvidenceRetrievalHit, ...]:
    """Return each document's latest usable revision visible at the plan decision time."""

    unique_hits: dict[str, EvidenceRetrievalHit] = {}
    for hit in hits:
        if hit.search_plan_id != plan.search_plan_id or hit.claim_id != plan.claim_id:
            raise ValueError("AQ-TRUTH-EVIDENCE-HIT-PLAN-MISMATCH")
        if hit.query_fingerprint_sha256 not in plan.query_hashes(hit.query_kind):
            raise ValueError("AQ-TRUTH-EVIDENCE-HIT-QUERY-MISMATCH")
        key = str(hit.evidence_id)
        existing = unique_hits.get(key)
        if existing is not None and existing != hit:
            raise ValueError("AQ-TRUTH-EVIDENCE-HIT-ID-CONFLICT")
        unique_hits[key] = hit

    assessment_by_id: dict[str, OfficialIdentityAssessment] = {}
    for assessment in official_identity_assessments:
        assessment_id = str(assessment.assessment_id)
        existing_assessment = assessment_by_id.get(assessment_id)
        if existing_assessment is not None and existing_assessment != assessment:
            raise ValueError("AQ-TRUTH-OFFICIAL-IDENTITY-ASSESSMENT-ID-CONFLICT")
        assessment_by_id[assessment_id] = assessment

    visible = [
        hit
        for hit in unique_hits.values()
        if hit.available_at <= plan.decision_time and hit.retrieved_at <= plan.decision_time
    ]
    latest: dict[str, EvidenceRetrievalHit] = {}
    by_document: dict[str, list[EvidenceRetrievalHit]] = defaultdict(list)
    for hit in visible:
        if hit.official_identity_assessment_id is not None:
            assessment = assessment_by_id.get(str(hit.official_identity_assessment_id))
            if assessment is None:
                raise ValueError("AQ-TRUTH-OFFICIAL-IDENTITY-ASSESSMENT-MISSING")
            if (
                assessment.state is not OfficialIdentityState.AUTHENTIC
                or assessment.source_identity_id != hit.source_identity_id
            ):
                raise ValueError("AQ-TRUTH-OFFICIAL-IDENTITY-ASSESSMENT-MISMATCH")
            if assessment.available_at > hit.available_at:
                raise ValueError("AQ-TRUTH-OFFICIAL-IDENTITY-ASSESSMENT-FUTURE")
        document_id = str(hit.source_document_id)
        by_document[document_id].append(hit)

    for document_id, history in by_document.items():
        if len({hit.source_identity_id for hit in history}) != 1:
            raise ValueError("AQ-TRUTH-EVIDENCE-DOCUMENT-IDENTITY-CONFLICT")
        by_revision: dict[int, EvidenceRetrievalHit] = {}
        for hit in sorted(history, key=lambda item: str(item.evidence_id)):
            existing_revision = by_revision.get(hit.revision_number)
            if existing_revision is not None and (
                existing_revision.revision_id != hit.revision_id
                or existing_revision.previous_revision_id != hit.previous_revision_id
                or existing_revision.content_sha256 != hit.content_sha256
            ):
                raise ValueError("AQ-TRUTH-EVIDENCE-REVISION-NUMBER-CONFLICT")
            by_revision.setdefault(hit.revision_number, hit)
        ordered = [by_revision[number] for number in sorted(by_revision)]
        for expected_number, hit in enumerate(ordered, start=1):
            if hit.revision_number != expected_number:
                raise ValueError("AQ-TRUTH-EVIDENCE-VISIBLE-REVISION-GAP")
            expected_predecessor = (
                None if expected_number == 1 else ordered[expected_number - 2].revision_id
            )
            if hit.previous_revision_id != expected_predecessor:
                raise ValueError("AQ-TRUTH-EVIDENCE-REVISION-PREDECESSOR-MISMATCH")
            if expected_number > 1 and hit.available_at < ordered[expected_number - 2].available_at:
                raise ValueError("AQ-TRUTH-EVIDENCE-REVISION-AVAILABILITY-REGRESSION")
        latest[document_id] = ordered[-1]

    return tuple(
        hit
        for document_id in sorted(latest)
        if (hit := latest[document_id]).rights_state in {RightsState.ALLOWED, RightsState.LIMITED}
        and (hit.deleted_time is None or hit.deleted_time > plan.decision_time)
    )


def _visible_revision_state(
    revisions: tuple[TemporalRevision, ...], *, decision_time: datetime
) -> tuple[dict[str, TemporalRevision], dict[str, TemporalRevision]]:
    decision = ensure_utc(decision_time)
    visible = [item for item in revisions if item.available_at <= decision]
    revision_by_id: dict[str, TemporalRevision] = {}
    by_document: dict[str, list[TemporalRevision]] = defaultdict(list)
    for revision in visible:
        revision_key = str(revision.revision_id)
        if revision_key in revision_by_id:
            raise ValueError("AQ-TRUTH-DUPLICATE-REVISION-ID")
        revision_by_id[revision_key] = revision
        by_document[str(revision.source_document_id)].append(revision)

    selected: dict[str, TemporalRevision] = {}
    for document_id, history in by_document.items():
        ordered = sorted(history, key=lambda item: item.revision_number)
        for expected_number, revision in enumerate(ordered, start=1):
            if revision.revision_number != expected_number:
                raise ValueError("AQ-TRUTH-VISIBLE-REVISION-GAP")
            expected_predecessor = (
                None if expected_number == 1 else ordered[expected_number - 2].revision_id
            )
            if revision.previous_revision_id != expected_predecessor:
                raise ValueError("AQ-TRUTH-REVISION-PREDECESSOR-MISMATCH")
            if (
                expected_number > 1
                and revision.available_at < ordered[expected_number - 2].available_at
            ):
                raise ValueError("AQ-TRUTH-REVISION-AVAILABILITY-REGRESSION")
        selected[document_id] = ordered[-1]
    return revision_by_id, selected


def select_revisions_as_of(
    revisions: tuple[TemporalRevision, ...], *, decision_time: datetime
) -> tuple[TemporalRevision, ...]:
    """Return only the latest revision visible for each document at decision time."""

    _, selected = _visible_revision_state(revisions, decision_time=decision_time)
    return tuple(selected[key] for key in sorted(selected))


def partition_claims_as_of(
    *,
    revisions: tuple[TemporalRevision, ...],
    claims: tuple[AtomicClaim, ...],
    decision_time: datetime,
) -> TruthClaimPartition:
    """Select current visible claims and route opinion-like content away from Truth."""

    decision = ensure_utc(decision_time)
    revision_by_id, selected = _visible_revision_state(revisions, decision_time=decision)
    selected_revision_ids = {str(item.revision_id) for item in selected.values()}
    tombstoned = {
        str(item.source_document_id) for item in selected.values() if item.deleted_time is not None
    }
    visible_truth: list[AtomicClaim] = []
    visible_impact: list[AtomicClaim] = []
    seen_claim_ids: set[ClaimId] = set()

    all_revision_ids = {str(item.revision_id) for item in revisions}
    for claim in sorted(claims, key=lambda item: (item.available_at, str(item.claim_id))):
        if claim.available_at > decision:
            continue
        revision_key = str(claim.revision_id)
        revision = revision_by_id.get(revision_key)
        if revision is None:
            reason = (
                "AQ-TRUTH-CLAIM-REFERENCES-FUTURE-REVISION"
                if revision_key in all_revision_ids
                else "AQ-TRUTH-CLAIM-REFERENCES-UNKNOWN-REVISION"
            )
            raise ValueError(reason)
        if claim.source_document_id != revision.source_document_id:
            raise ValueError("AQ-TRUTH-CLAIM-DOCUMENT-REVISION-MISMATCH")
        if claim.available_at < revision.available_at:
            raise ValueError("AQ-TRUTH-CLAIM-PREDATES-REVISION")
        if revision_key not in selected_revision_ids:
            continue
        if str(claim.source_document_id) in tombstoned:
            continue
        if claim.claim_id in seen_claim_ids:
            raise ValueError("AQ-TRUTH-DUPLICATE-CLAIM-ID")
        seen_claim_ids.add(claim.claim_id)
        if claim.claim_type in TRUTH_ADJUDICABLE_CLAIM_TYPES:
            visible_truth.append(claim)
        else:
            visible_impact.append(claim)

    selected_revisions = tuple(selected[key] for key in sorted(selected))
    return TruthClaimPartition(
        as_of_time=decision,
        selected_revisions=selected_revisions,
        tombstoned_document_ids=tuple(SourceDocumentId(item) for item in sorted(tombstoned)),
        truth_claims=tuple(visible_truth),
        impact_claims=tuple(visible_impact),
    )


def select_truth_assessments_as_of(
    *,
    revisions: tuple[TemporalRevision, ...],
    claims: tuple[AtomicClaim, ...],
    assessments: tuple[TruthAssessment, ...],
    evidence_graphs: tuple[EvidenceGraph, ...],
    decision_time: datetime,
) -> tuple[TruthAssessment, ...]:
    """Return latest visible assessments backed only by current visible revisions."""

    decision = ensure_utc(decision_time)
    partition = partition_claims_as_of(revisions=revisions, claims=claims, decision_time=decision)
    truth_claims = {item.claim_id: item for item in partition.truth_claims}
    visible_revision_by_id, selected = _visible_revision_state(revisions, decision_time=decision)
    selected_revision_ids = {str(item.revision_id) for item in selected.values()}
    graph_by_hash: dict[str, EvidenceGraph] = {}
    for graph in evidence_graphs:
        graph_hash = graph.content_sha256()
        existing_graph = graph_by_hash.get(graph_hash)
        if existing_graph is not None and existing_graph != graph:
            raise ValueError("AQ-TRUTH-EVIDENCE-GRAPH-HASH-CONFLICT")
        graph_by_hash[graph_hash] = graph
    visible_assessment_by_id: dict[str, TruthAssessment] = {}
    for assessment in assessments:
        if assessment.available_at > decision:
            continue
        assessment_id = str(assessment.assessment_id)
        existing = visible_assessment_by_id.get(assessment_id)
        if existing is not None and existing != assessment:
            raise ValueError("AQ-TRUTH-ASSESSMENT-ID-CONFLICT")
        visible_assessment_by_id[assessment_id] = assessment
    latest: dict[ClaimId, TruthAssessment] = {}
    for assessment in sorted(
        visible_assessment_by_id.values(),
        key=lambda item: (item.available_at, item.assessed_at, str(item.assessment_id)),
    ):
        claim = truth_claims.get(assessment.claim_id)
        if claim is None:
            continue
        if assessment.claim_type is not claim.claim_type:
            raise ValueError("AQ-TRUTH-ASSESSMENT-CLAIM-TYPE-MISMATCH")
        graph = graph_by_hash.get(assessment.evidence_graph_hash)
        if graph is None:
            raise ValueError("AQ-TRUTH-ASSESSMENT-EVIDENCE-GRAPH-MISSING")
        if graph.as_of_time > assessment.available_at or graph.as_of_time > decision:
            raise ValueError("AQ-TRUTH-ASSESSMENT-EVIDENCE-GRAPH-FUTURE")
        if not any(
            node.node_id == str(claim.claim_id) and node.node_type is GraphNodeType.CLAIM
            for node in graph.nodes
        ):
            raise ValueError("AQ-TRUTH-ASSESSMENT-CLAIM-NOT-IN-GRAPH")
        if (
            assessment.independent_evidence_count != graph.independent_evidence_count
            or assessment.evidence_dependency_score != graph.evidence_dependency_score
        ):
            raise ValueError("AQ-TRUTH-ASSESSMENT-GRAPH-METRIC-MISMATCH")
        evidence_revisions: list[TemporalRevision] = []
        for revision_id in assessment.source_revision_ids:
            revision = visible_revision_by_id.get(str(revision_id))
            if revision is None:
                raise ValueError("AQ-TRUTH-ASSESSMENT-REFERENCES-NONVISIBLE-REVISION")
            if revision.available_at > assessment.available_at:
                raise ValueError("AQ-TRUTH-ASSESSMENT-PREDATES-EVIDENCE")
            evidence_revisions.append(revision)
        evidence_documents = {item.source_document_id for item in evidence_revisions}
        if evidence_documents != set(assessment.source_document_ids):
            raise ValueError("AQ-TRUTH-ASSESSMENT-EVIDENCE-SET-MISMATCH")
        if any(str(item.revision_id) not in selected_revision_ids for item in evidence_revisions):
            continue
        if assessment.available_at < claim.available_at:
            raise ValueError("AQ-TRUTH-ASSESSMENT-PREDATES-CLAIM")
        latest[assessment.claim_id] = assessment
    return tuple(latest[key] for key in sorted(latest, key=str))
