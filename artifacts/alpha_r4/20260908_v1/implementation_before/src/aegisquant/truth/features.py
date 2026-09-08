"""Auditable evidence-feature extraction for calibrated truth models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final, Self

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    SourceDocumentId,
    SourceIdentityId,
)
from aegisquant.domain.intelligence import Polarity, RightsState
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.truth import AtomicClaim, ClaimType, EvidenceQueryKind, EvidenceRetrievalHit
from aegisquant.domain.values import UnitInterval
from aegisquant.intelligence.graph import (
    EvidenceGraph,
    EvidenceIndependenceModel,
    GraphNodeType,
)

MODEL_FEATURE_NAMES: Final = (
    "primary_source_present",
    "official_signature_valid",
    "source_reliability_prior",
    "independent_source_count",
    "dependency_score",
    "contradiction_count",
    "official_denial_present",
    "temporal_consistency",
    "entity_consistency",
    "quote_consistency",
    "media_provenance",
    "revision_count",
    "retraction_history",
    "language_translation_confidence",
    "manipulation_signals",
)
AUDIT_FEATURE_NAMES: Final = (*MODEL_FEATURE_NAMES, "llm_confidence_audit_only")
_COUNT_NORMALIZATION_CAP: Final = Decimal("10")


class TruthCalibrationKey(DomainModel):
    """The mandatory source/event/language/claim calibration stratum."""

    source_class: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=35)
    claim_type: ClaimType

    @model_validator(mode="after")
    def validate_labels(self) -> Self:
        if any(not value.strip() for value in (self.source_class, self.event_type, self.language)):
            raise ValueError("AQ-TRUTH-EMPTY-CALIBRATION-KEY")
        return self

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class EvidenceFeatureInputSnapshot(DomainModel):
    """PIT-bound external signals used alongside the evidence graph and retrieval hits."""

    snapshot_id: ArtifactId
    claim_id: ClaimId
    source_document_id: SourceDocumentId
    source_identity_id: SourceIdentityId
    source_revision_id: ArtifactId
    lineage_artifact_ids: tuple[ArtifactId, ...] = Field(min_length=1)
    lineage_artifact_sha256s: tuple[str, ...] = Field(min_length=1)
    source_class: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    source_reliability_prior: UnitInterval
    official_signature_valid: bool
    temporal_consistency: UnitInterval
    entity_consistency: UnitInterval
    quote_consistency: UnitInterval
    media_provenance: UnitInterval
    retraction_history: UnitInterval
    language_translation_confidence: UnitInterval
    manipulation_signals: UnitInterval
    llm_confidence_audit_only: UnitInterval | None = None
    observed_at: UtcDateTime
    available_at: UtcDateTime
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if len(self.lineage_artifact_ids) != len(self.lineage_artifact_sha256s):
            raise ValueError("AQ-TRUTH-FEATURE-INPUT-LINEAGE-COUNT-MISMATCH")
        if len(set(self.lineage_artifact_ids)) != len(self.lineage_artifact_ids):
            raise ValueError("AQ-TRUTH-FEATURE-INPUT-DUPLICATE-LINEAGE")
        for sha256 in self.lineage_artifact_sha256s:
            ensure_sha256(sha256, field_name="lineage_artifact_sha256")
        if self.observed_at > self.available_at:
            raise ValueError("AQ-TRUTH-FEATURE-INPUT-TIME-ORDER")
        if not self.source_class.strip() or not self.event_type.strip() or not self.version.strip():
            raise ValueError("AQ-TRUTH-FEATURE-INPUT-EMPTY-FIELD")
        return self

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class EvidenceFeatureVector(DomainModel):
    """One PIT feature row; LLM confidence is retained for audit, not model input."""

    feature_id: ArtifactId
    claim_id: ClaimId
    source_revision_id: ArtifactId
    input_snapshot_id: ArtifactId
    input_snapshot_sha256: str
    calibration_key: TruthCalibrationKey
    primary_source_present: bool
    official_signature_valid: bool
    source_reliability_prior: UnitInterval
    independent_source_count: int = Field(ge=0)
    dependency_score: UnitInterval
    contradiction_count: int = Field(ge=0)
    official_denial_present: bool
    temporal_consistency: UnitInterval
    entity_consistency: UnitInterval
    quote_consistency: UnitInterval
    media_provenance: UnitInterval
    revision_count: int = Field(ge=1)
    retraction_history: UnitInterval
    language_translation_confidence: UnitInterval
    manipulation_signals: UnitInterval
    llm_confidence_audit_only: UnitInterval | None = None
    evidence_graph_sha256: str
    feature_version: str = Field(min_length=1)
    extracted_at: UtcDateTime
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_vector(self) -> Self:
        ensure_sha256(self.evidence_graph_sha256, field_name="evidence_graph_sha256")
        ensure_sha256(self.input_snapshot_sha256, field_name="input_snapshot_sha256")
        if self.extracted_at > self.available_at:
            raise ValueError("AQ-TRUTH-FEATURE-TIME-ORDER")
        if not self.feature_version.strip():
            raise ValueError("AQ-TRUTH-EMPTY-FEATURE-VERSION")
        return self

    def model_values(self) -> tuple[float, ...]:
        """Return only governed model inputs; the LLM audit value is deliberately absent."""

        def normalize_count(value: int) -> float:
            return float(min(Decimal(value), _COUNT_NORMALIZATION_CAP) / _COUNT_NORMALIZATION_CAP)

        return (
            float(self.primary_source_present),
            float(self.official_signature_valid),
            float(self.source_reliability_prior),
            normalize_count(self.independent_source_count),
            float(self.dependency_score),
            normalize_count(self.contradiction_count),
            float(self.official_denial_present),
            float(self.temporal_consistency),
            float(self.entity_consistency),
            float(self.quote_consistency),
            float(self.media_provenance),
            normalize_count(self.revision_count),
            float(self.retraction_history),
            float(self.language_translation_confidence),
            float(self.manipulation_signals),
        )

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def extract_evidence_features(
    *,
    feature_id: ArtifactId,
    claim: AtomicClaim,
    evidence_graph: EvidenceGraph,
    evidence_hits: tuple[EvidenceRetrievalHit, ...],
    input_snapshot: EvidenceFeatureInputSnapshot,
    decision_time: datetime,
    feature_version: str = "v5-p04-evidence-features-v1",
) -> EvidenceFeatureVector:
    """Extract deterministic features from a P03-selected, point-in-time evidence snapshot."""

    decision = ensure_utc(decision_time)
    if (
        claim.available_at > decision
        or input_snapshot.available_at > decision
        or evidence_graph.as_of_time > decision
        or any(node.available_at_utc > decision for node in evidence_graph.nodes)
        or any(edge.available_at_utc > decision for edge in evidence_graph.edges)
    ):
        raise ValueError("AQ-TRUTH-FEATURE-FUTURE-INPUT")
    if input_snapshot.claim_id != claim.claim_id:
        raise ValueError("AQ-TRUTH-FEATURE-INPUT-CLAIM-MISMATCH")
    if (
        input_snapshot.source_document_id != claim.source_document_id
        or input_snapshot.source_identity_id != claim.source_identity_id
        or input_snapshot.source_revision_id != claim.revision_id
    ):
        raise ValueError("AQ-TRUTH-FEATURE-INPUT-SOURCE-REVISION-MISMATCH")
    if input_snapshot.observed_at < claim.available_at:
        raise ValueError("AQ-TRUTH-FEATURE-INPUT-OBSERVED-BEFORE-CLAIM")
    lineage_by_id = dict(
        zip(
            input_snapshot.lineage_artifact_ids,
            input_snapshot.lineage_artifact_sha256s,
            strict=True,
        )
    )
    if lineage_by_id.get(claim.revision_id) != claim.content_sha256():
        raise ValueError("AQ-TRUTH-FEATURE-INPUT-CLAIM-LINEAGE-MISMATCH")
    if not any(
        node.node_id == str(claim.claim_id) and node.node_type is GraphNodeType.CLAIM
        for node in evidence_graph.nodes
    ):
        raise ValueError("AQ-TRUTH-FEATURE-CLAIM-NOT-IN-GRAPH")
    if len({str(hit.evidence_id) for hit in evidence_hits}) != len(evidence_hits):
        raise ValueError("AQ-TRUTH-FEATURE-DUPLICATE-EVIDENCE")
    node_by_id = {node.node_id: node for node in evidence_graph.nodes}
    evidence_node_ids: set[str] = set()
    for hit in evidence_hits:
        if hit.claim_id != claim.claim_id:
            raise ValueError("AQ-TRUTH-FEATURE-EVIDENCE-CLAIM-MISMATCH")
        if hit.available_at > decision or hit.retrieved_at > decision:
            raise ValueError("AQ-TRUTH-FEATURE-FUTURE-EVIDENCE")
        if hit.rights_state not in {RightsState.ALLOWED, RightsState.LIMITED}:
            raise ValueError("AQ-TRUTH-FEATURE-NONUSABLE-EVIDENCE-RIGHTS")
        if hit.deleted_time is not None and hit.deleted_time <= decision:
            raise ValueError("AQ-TRUTH-FEATURE-TOMBSTONED-EVIDENCE")
        graph_node = node_by_id.get(str(hit.source_document_id)) or node_by_id.get(
            str(hit.evidence_id)
        )
        if graph_node is None:
            raise ValueError("AQ-TRUTH-FEATURE-EVIDENCE-NOT-IN-GRAPH")
        if (
            graph_node.revision_id != hit.revision_id
            or graph_node.source_identity_id != hit.source_identity_id
            or graph_node.content_sha256 != hit.content_sha256
        ):
            raise ValueError("AQ-TRUTH-FEATURE-EVIDENCE-REVISION-MISMATCH")
        if lineage_by_id.get(hit.revision_id) != hit.content_sha256:
            raise ValueError("AQ-TRUTH-FEATURE-INPUT-EVIDENCE-LINEAGE-MISMATCH")
        evidence_node_ids.add(graph_node.node_id)

    revision_count = sum(hit.revision_number for hit in evidence_hits)
    independence = EvidenceIndependenceModel().evaluate(
        as_of_time=evidence_graph.as_of_time,
        nodes=evidence_graph.nodes,
        edges=evidence_graph.edges,
        evidence_node_ids=frozenset(evidence_node_ids),
    )
    return EvidenceFeatureVector(
        feature_id=feature_id,
        claim_id=claim.claim_id,
        source_revision_id=claim.revision_id,
        input_snapshot_id=input_snapshot.snapshot_id,
        input_snapshot_sha256=input_snapshot.content_sha256(),
        calibration_key=TruthCalibrationKey(
            source_class=input_snapshot.source_class,
            event_type=input_snapshot.event_type,
            language=claim.language,
            claim_type=claim.claim_type,
        ),
        primary_source_present=any(
            hit.query_kind is EvidenceQueryKind.PRIMARY_SOURCE or hit.is_official_source
            for hit in evidence_hits
        ),
        official_signature_valid=input_snapshot.official_signature_valid,
        source_reliability_prior=input_snapshot.source_reliability_prior,
        independent_source_count=independence.independent_evidence_count,
        dependency_score=independence.evidence_dependency_score,
        contradiction_count=sum(hit.polarity is Polarity.NEGATE for hit in evidence_hits),
        official_denial_present=any(
            hit.query_kind is EvidenceQueryKind.OFFICIAL_DENIAL for hit in evidence_hits
        ),
        temporal_consistency=input_snapshot.temporal_consistency,
        entity_consistency=input_snapshot.entity_consistency,
        quote_consistency=input_snapshot.quote_consistency,
        media_provenance=input_snapshot.media_provenance,
        revision_count=max(revision_count, 1),
        retraction_history=input_snapshot.retraction_history,
        language_translation_confidence=input_snapshot.language_translation_confidence,
        manipulation_signals=input_snapshot.manipulation_signals,
        llm_confidence_audit_only=input_snapshot.llm_confidence_audit_only,
        evidence_graph_sha256=evidence_graph.content_sha256(),
        feature_version=feature_version,
        extracted_at=decision,
        available_at=decision,
    )
