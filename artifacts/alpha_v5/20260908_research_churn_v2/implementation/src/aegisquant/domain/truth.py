"""Versioned truth contracts with explicit point-in-time availability semantics."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Self, cast
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    SourceDocumentId,
    SourceIdentityId,
    SourcePolicyId,
)
from aegisquant.domain.intelligence import Polarity, RightsState
from aegisquant.domain.serialization import canonical_content_hash
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import UnitInterval


def _require_sha256(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")


def _model_hash(model: DomainModel, *, unordered_fields: tuple[str, ...] = ()) -> str:
    payload = cast(dict[str, JsonValue], model.model_dump(mode="json"))
    for field_name in unordered_fields:
        values = payload[field_name]
        if not isinstance(values, list):
            raise TypeError(f"{field_name} must serialize as a list")
        payload[field_name] = sorted(
            values,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    return canonical_content_hash(payload)


class ClaimType(StrEnum):
    """Semantic class assigned before truth adjudication."""

    FACT = "FACT"
    FORWARD_FACT = "FORWARD_FACT"
    INTERPRETATION = "INTERPRETATION"
    OPINION = "OPINION"
    PREDICTION = "PREDICTION"
    QUOTE = "QUOTE"
    RUMOR = "RUMOR"


TRUTH_ADJUDICABLE_CLAIM_TYPES = frozenset({ClaimType.FACT, ClaimType.FORWARD_FACT, ClaimType.QUOTE})
IMPACT_ONLY_CLAIM_TYPES = frozenset(set(ClaimType) - TRUTH_ADJUDICABLE_CLAIM_TYPES)


class EvidenceQueryKind(StrEnum):
    """Why a query exists; retrieval intent is not evidence polarity."""

    SUPPORT = "SUPPORT"
    CONTRADICTION = "CONTRADICTION"
    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    OFFICIAL_DENIAL = "OFFICIAL_DENIAL"
    REVISION = "REVISION"
    TIMELINE = "TIMELINE"


class EvidenceQuery(DomainModel):
    """One bounded retrieval query in its original language."""

    text: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=35)
    start_time: UtcDateTime | None = None
    end_time: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        if not self.text.strip():
            raise ValueError("AQ-TRUTH-EMPTY-EVIDENCE-QUERY")
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time > self.end_time
        ):
            raise ValueError("AQ-TRUTH-EVIDENCE-QUERY-TIME-ORDER")
        return self

    def content_sha256(self) -> str:
        return _model_hash(self)


_QUERY_FIELDS = (
    "support_queries",
    "contradiction_queries",
    "primary_source_queries",
    "official_denial_queries",
    "revision_queries",
    "timeline_queries",
)


class EvidenceSearchPlan(DomainModel):
    """PIT search plan that requires both confirming and disconfirming work."""

    search_plan_id: ArtifactId
    claim_id: ClaimId
    generated_at: UtcDateTime
    available_at: UtcDateTime
    decision_time: UtcDateTime
    support_queries: tuple[EvidenceQuery, ...] = Field(min_length=1)
    contradiction_queries: tuple[EvidenceQuery, ...] = Field(min_length=1)
    primary_source_queries: tuple[EvidenceQuery, ...] = Field(min_length=1)
    official_denial_queries: tuple[EvidenceQuery, ...] = Field(min_length=1)
    revision_queries: tuple[EvidenceQuery, ...] = Field(min_length=1)
    timeline_queries: tuple[EvidenceQuery, ...] = Field(min_length=1)
    probability_aggregation: Literal["CALIBRATED_MODEL_NOT_AGENT_VOTE"] = (
        "CALIBRATED_MODEL_NOT_AGENT_VOTE"
    )

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if not self.generated_at <= self.available_at <= self.decision_time:
            raise ValueError("AQ-TRUTH-EVIDENCE-PLAN-TIME-ORDER")
        for field_name in _QUERY_FIELDS:
            queries = cast(tuple[EvidenceQuery, ...], getattr(self, field_name))
            hashes = tuple(query.content_sha256() for query in queries)
            if len(hashes) != len(set(hashes)):
                raise ValueError(f"AQ-TRUTH-DUPLICATE-{field_name.upper()}")
            if any(
                query.end_time is not None and query.end_time > self.decision_time
                for query in queries
            ):
                raise ValueError("AQ-TRUTH-EVIDENCE-QUERY-AFTER-DECISION")
        support = {query.content_sha256() for query in self.support_queries}
        contradiction = {query.content_sha256() for query in self.contradiction_queries}
        if support & contradiction:
            raise ValueError("AQ-TRUTH-SUPPORT-CONTRADICTION-QUERY-OVERLAP")
        return self

    def query_hashes(self, kind: EvidenceQueryKind) -> frozenset[str]:
        field_name = {
            EvidenceQueryKind.SUPPORT: "support_queries",
            EvidenceQueryKind.CONTRADICTION: "contradiction_queries",
            EvidenceQueryKind.PRIMARY_SOURCE: "primary_source_queries",
            EvidenceQueryKind.OFFICIAL_DENIAL: "official_denial_queries",
            EvidenceQueryKind.REVISION: "revision_queries",
            EvidenceQueryKind.TIMELINE: "timeline_queries",
        }[kind]
        queries = cast(tuple[EvidenceQuery, ...], getattr(self, field_name))
        return frozenset(query.content_sha256() for query in queries)


class EvidenceRetrievalHit(DomainModel):
    """One immutable, rights-labelled search hit bound to a source revision."""

    evidence_id: ArtifactId
    search_plan_id: ArtifactId
    claim_id: ClaimId
    query_kind: EvidenceQueryKind
    query_fingerprint_sha256: str
    source_document_id: SourceDocumentId
    source_identity_id: SourceIdentityId
    source_policy_id: SourcePolicyId
    revision_id: ArtifactId
    revision_number: int = Field(ge=1)
    previous_revision_id: ArtifactId | None = None
    canonical_url: str
    content_sha256: str
    polarity: Polarity
    published_time: UtcDateTime
    observed_time: UtcDateTime
    available_at: UtcDateTime
    retrieved_at: UtcDateTime
    deleted_time: UtcDateTime | None = None
    rights_state: RightsState
    is_official_source: bool
    official_identity_verified: bool
    official_identity_assessment_id: ArtifactId | None = None
    lineage_node_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_hit(self) -> Self:
        _require_sha256(
            self.query_fingerprint_sha256,
            field_name="query_fingerprint_sha256",
        )
        _require_sha256(self.content_sha256, field_name="content_sha256")
        parsed = urlsplit(self.canonical_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("AQ-TRUTH-EVIDENCE-HIT-URL-BOUNDARY")
        if not (
            self.published_time <= self.observed_time <= self.available_at <= self.retrieved_at
        ):
            raise ValueError("AQ-TRUTH-EVIDENCE-HIT-TIME-ORDER")
        if self.deleted_time is not None and not (
            self.published_time <= self.deleted_time <= self.observed_time
        ):
            raise ValueError("AQ-TRUTH-EVIDENCE-HIT-DELETION-TIME")
        if self.revision_number == 1 and self.previous_revision_id is not None:
            raise ValueError("AQ-TRUTH-FIRST-EVIDENCE-REVISION-HAS-PREDECESSOR")
        if self.revision_number > 1 and self.previous_revision_id is None:
            raise ValueError("AQ-TRUTH-LATER-EVIDENCE-REVISION-MISSING-PREDECESSOR")
        if any(not node_id.strip() for node_id in self.lineage_node_ids):
            raise ValueError("AQ-TRUTH-EMPTY-LINEAGE-NODE")
        if len(self.lineage_node_ids) != len(set(self.lineage_node_ids)):
            raise ValueError("AQ-TRUTH-DUPLICATE-LINEAGE-NODE")
        if self.official_identity_verified != (self.official_identity_assessment_id is not None):
            raise ValueError("AQ-TRUTH-OFFICIAL-IDENTITY-ASSESSMENT-BINDING")
        if self.query_kind is EvidenceQueryKind.OFFICIAL_DENIAL and (
            not self.is_official_source
            or not self.official_identity_verified
            or self.polarity is not Polarity.NEGATE
        ):
            raise ValueError("AQ-TRUTH-UNVERIFIED-OFFICIAL-DENIAL")
        return self


class TruthAssessmentScope(StrEnum):
    CLAIM_TRUTH = "CLAIM_TRUTH"
    FORWARD_FACT_STATUS = "FORWARD_FACT_STATUS"
    QUOTE_AUTHENTICITY = "QUOTE_AUTHENTICITY"


class TruthState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    RUMOR = "RUMOR"
    PARTIALLY_CORROBORATED = "PARTIALLY_CORROBORATED"
    VERIFIED_PRIMARY = "VERIFIED_PRIMARY"
    VERIFIED_MULTI_SOURCE = "VERIFIED_MULTI_SOURCE"
    CONTRADICTED = "CONTRADICTED"
    RETRACTED = "RETRACTED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ClaimSpan(DomainModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.end <= self.start:
            raise ValueError("AQ-TRUTH-SPAN-ORDER")
        return self


class RevisionDelta(DomainModel):
    """Hash-only revision delta; raw source material stays in the governed archive."""

    field_path: str = Field(min_length=1)
    previous_value_sha256: str | None = None
    current_value_sha256: str | None = None

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        if self.previous_value_sha256 is None and self.current_value_sha256 is None:
            raise ValueError("AQ-TRUTH-EMPTY-REVISION-DELTA")
        for field_name, value in (
            ("previous_value_sha256", self.previous_value_sha256),
            ("current_value_sha256", self.current_value_sha256),
        ):
            if value is not None:
                _require_sha256(value, field_name=field_name)
        return self


class TemporalRevision(DomainModel):
    """One immutable source-document revision and when it became knowable."""

    source_document_id: SourceDocumentId
    revision_id: ArtifactId
    previous_revision_id: ArtifactId | None = None
    revision_number: int = Field(ge=1)
    content_hash: str
    observed_at: UtcDateTime
    effective_at: UtcDateTime
    available_at: UtcDateTime
    updated_time: UtcDateTime | None = None
    deleted_time: UtcDateTime | None = None
    diff: tuple[RevisionDelta, ...] = ()

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        _require_sha256(self.content_hash, field_name="content_hash")
        if self.effective_at > self.observed_at or self.observed_at > self.available_at:
            raise ValueError("AQ-TRUTH-REVISION-TIME-ORDER")
        if self.updated_time is not None and self.updated_time > self.observed_at:
            raise ValueError("AQ-TRUTH-UPDATE-AFTER-OBSERVATION")
        if self.deleted_time is not None and self.deleted_time > self.observed_at:
            raise ValueError("AQ-TRUTH-DELETION-AFTER-OBSERVATION")
        if self.revision_number == 1 and self.previous_revision_id is not None:
            raise ValueError("AQ-TRUTH-FIRST-REVISION-HAS-PREDECESSOR")
        if self.revision_number > 1 and self.previous_revision_id is None:
            raise ValueError("AQ-TRUTH-LATER-REVISION-MISSING-PREDECESSOR")
        return self

    def content_sha256(self) -> str:
        return _model_hash(self, unordered_fields=("diff",))


class AtomicClaim(DomainModel):
    """An exact text span classified before it reaches truth or impact logic."""

    claim_id: ClaimId
    source_document_id: SourceDocumentId
    source_identity_id: SourceIdentityId
    revision_id: ArtifactId
    claim_type: ClaimType
    original_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    span: ClaimSpan
    language: str = Field(min_length=2, max_length=35)
    translation: str | None = None
    entity_ids: tuple[str, ...] = Field(min_length=1)
    event_time: UtcDateTime | None = None
    published_time: UtcDateTime
    first_seen_time: UtcDateTime
    available_at: UtcDateTime
    ingested_time: UtcDateTime

    @model_validator(mode="after")
    def validate_claim(self) -> Self:
        if not (
            self.published_time <= self.first_seen_time <= self.available_at <= self.ingested_time
        ):
            raise ValueError("AQ-TRUTH-CLAIM-TIME-ORDER")
        if self.span.end > len(self.original_text):
            raise ValueError("AQ-TRUTH-SPAN-OUT-OF-BOUNDS")
        if self.original_text[self.span.start : self.span.end] != self.span.text:
            raise ValueError("AQ-TRUTH-SPAN-TEXT-MISMATCH")
        if len(set(self.entity_ids)) != len(self.entity_ids):
            raise ValueError("AQ-TRUTH-DUPLICATE-ENTITY")
        if (
            self.claim_type in {ClaimType.FACT, ClaimType.QUOTE}
            and self.event_time is not None
            and self.event_time > self.published_time
        ):
            raise ValueError("AQ-TRUTH-NONFORWARD-CLAIM-HAS-FUTURE-EVENT")
        return self

    @property
    def truth_adjudicable(self) -> bool:
        return self.claim_type in TRUTH_ADJUDICABLE_CLAIM_TYPES

    def content_sha256(self) -> str:
        return _model_hash(self, unordered_fields=("entity_ids",))


_SCOPE_BY_CLAIM_TYPE = {
    ClaimType.FACT: TruthAssessmentScope.CLAIM_TRUTH,
    ClaimType.FORWARD_FACT: TruthAssessmentScope.FORWARD_FACT_STATUS,
    ClaimType.QUOTE: TruthAssessmentScope.QUOTE_AUTHENTICITY,
}


class TruthAssessment(DomainModel):
    """Calibratable truth output that never accepts opinion-like claim classes."""

    assessment_id: ArtifactId
    claim_id: ClaimId
    claim_type: ClaimType
    assessment_scope: TruthAssessmentScope
    source_document_ids: tuple[SourceDocumentId, ...] = Field(min_length=1)
    source_revision_ids: tuple[ArtifactId, ...] = Field(min_length=1)
    source_identity_probability: UnitInterval
    content_integrity_probability: UnitInterval
    claim_truth_probability: UnitInterval
    claim_current_probability: UnitInterval
    evidence_independence_probability: UnitInterval
    manipulation_probability: UnitInterval
    revision_probability: UnitInterval
    source_compromised_probability: UnitInterval
    independent_evidence_count: int = Field(ge=0)
    evidence_dependency_score: UnitInterval
    contradiction_probability: UnitInterval
    calibration_bucket: str = Field(min_length=1)
    truth_state: TruthState
    reason_codes: tuple[str, ...] = Field(min_length=1)
    evidence_graph_hash: str
    model_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    assessed_at: UtcDateTime
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_assessment(self) -> Self:
        required_scope = _SCOPE_BY_CLAIM_TYPE.get(self.claim_type)
        if required_scope is None:
            raise ValueError("AQ-TRUTH-NON-ADJUDICABLE-CLAIM-TYPE")
        if self.assessment_scope is not required_scope:
            raise ValueError("AQ-TRUTH-ASSESSMENT-SCOPE-MISMATCH")
        if self.assessed_at > self.available_at:
            raise ValueError("AQ-TRUTH-ASSESSMENT-TIME-ORDER")
        if len(set(self.source_document_ids)) != len(self.source_document_ids):
            raise ValueError("AQ-TRUTH-DUPLICATE-SOURCE-DOCUMENT")
        if len(set(self.source_revision_ids)) != len(self.source_revision_ids):
            raise ValueError("AQ-TRUTH-DUPLICATE-SOURCE-REVISION")
        if self.independent_evidence_count > len(self.source_document_ids):
            raise ValueError("AQ-TRUTH-INDEPENDENCE-COUNT-EXCEEDS-DOCUMENTS")
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("AQ-TRUTH-EMPTY-REASON-CODE")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("AQ-TRUTH-DUPLICATE-REASON-CODE")
        _require_sha256(self.evidence_graph_hash, field_name="evidence_graph_hash")
        return self

    def content_sha256(self) -> str:
        return _model_hash(
            self,
            unordered_fields=("source_document_ids", "source_revision_ids", "reason_codes"),
        )
