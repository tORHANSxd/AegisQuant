"""Strict P10 world-intelligence contracts with fail-closed rights and time semantics."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.config.models import SECRET_KEY_RE
from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import RightsState
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, UnitInterval


class WorldSource(StrEnum):
    FRED_ALFRED = "fred_alfred"
    COIN_METRICS = "coin_metrics_community"
    DUNE = "dune"
    DEFILLAMA = "defillama"
    OFFICIAL = "official"
    GDELT = "gdelt"
    X = "x"
    TELEGRAM = "telegram"
    BLUESKY = "bluesky"
    YOUTUBE = "youtube"
    GITHUB = "github"
    REDDIT = "reddit"
    DISCORD = "discord"


class SourceTier(StrEnum):
    OFFICIAL_PRIMARY = "OFFICIAL_PRIMARY"
    STRUCTURED_PRIMARY = "STRUCTURED_PRIMARY"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    SOCIAL_OBSERVATION = "SOCIAL_OBSERVATION"
    DISABLED = "DISABLED"


class RuntimeSourceState(StrEnum):
    READY = "READY"
    AWAITING_CREDENTIALS = "AWAITING_CREDENTIALS"
    AWAITING_USER_APPROVAL = "AWAITING_USER_APPROVAL"
    DISABLED_BY_POLICY = "DISABLED_BY_POLICY"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"


class UsePermission(StrEnum):
    ALLOWED = "ALLOWED"
    LOCAL_ONLY = "LOCAL_ONLY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    PROHIBITED = "PROHIBITED"


class SourceUsePolicy(DomainModel):
    policy_id: str = Field(min_length=1)
    source: WorldSource
    rights_state: RightsState
    raw_local_storage: UsePermission
    cloud_inference: UsePermission
    embedding: UsePermission
    training: UsePermission
    fine_tuning: UsePermission
    display: UsePermission
    export: UsePermission
    deletion_sync_required: bool
    revision_sync_required: bool
    retention_days: int = Field(ge=0)
    approved_scopes: tuple[str, ...]
    checked_at: UtcDateTime
    terms_hash: str | None = None

    @model_validator(mode="after")
    def fail_closed_for_unknown_or_prohibited_rights(self) -> SourceUsePolicy:
        if self.terms_hash is not None and len(self.terms_hash) != 64:
            raise ValueError("terms_hash must be a SHA-256 digest")
        if self.training is not UsePermission.PROHIBITED:
            raise ValueError("foundation-model training is prohibited for every source")
        if self.rights_state in {RightsState.UNKNOWN, RightsState.PROHIBITED}:
            sensitive = (
                self.cloud_inference,
                self.embedding,
                self.fine_tuning,
                self.display,
                self.export,
            )
            if any(value is not UsePermission.PROHIBITED for value in sensitive):
                raise ValueError("unknown or prohibited rights must deny sensitive uses")
        if self.rights_state is RightsState.PROHIBITED and (
            self.raw_local_storage is not UsePermission.PROHIBITED
            or self.retention_days != 0
            or self.approved_scopes
        ):
            raise ValueError("prohibited source must deny collection and retention")
        return self

    def allows(self, use: str, *, cloud: bool = False) -> bool:
        field_by_use = {
            "raw_local_storage": self.raw_local_storage,
            "cloud_inference": self.cloud_inference,
            "embedding": self.embedding,
            "training": self.training,
            "fine_tuning": self.fine_tuning,
            "display": self.display,
            "export": self.export,
        }
        permission = field_by_use.get(use)
        if permission is None:
            raise ValueError(f"unknown source use: {use}")
        if permission is UsePermission.ALLOWED:
            return True
        return permission is UsePermission.LOCAL_ONLY and not cloud


class SourceCatalogEntry(DomainModel):
    source_id: str = Field(min_length=1)
    source: WorldSource
    tier: SourceTier
    authority_type: str = Field(min_length=1)
    canonical_host: str = Field(min_length=1)
    jurisdiction: str
    policy_id: str = Field(min_length=1)
    approved_capabilities: tuple[str, ...]
    runtime_state: RuntimeSourceState
    credentials_required: bool
    secret_key_name: str | None = None

    @model_validator(mode="after")
    def validate_access_state(self) -> SourceCatalogEntry:
        if (
            self.secret_key_name is not None
            and SECRET_KEY_RE.fullmatch(self.secret_key_name) is None
        ):
            raise ValueError("source catalog accepts a secret key name, never a secret value")
        if (
            self.credentials_required != (self.secret_key_name is not None)
            and self.runtime_state is not RuntimeSourceState.AWAITING_CREDENTIALS
        ):
            raise ValueError("credentialed source state and secret reference disagree")
        if self.source in {WorldSource.REDDIT, WorldSource.DISCORD} and (
            self.tier is not SourceTier.DISABLED
            or self.runtime_state is not RuntimeSourceState.DISABLED_BY_POLICY
        ):
            raise ValueError("Reddit and Discord must remain disabled by policy")
        return self


class ContentRevision(DomainModel):
    content_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    provider_id: str = Field(min_length=1)
    source_family_id: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    original_language: str = Field(min_length=2)
    published_at: UtcDateTime
    observed_at: UtcDateTime
    available_at: UtcDateTime
    body_sha256: str
    original_text: str | None = None
    modified_at: UtcDateTime | None = None
    deleted_at: UtcDateTime | None = None
    supersedes_revision: int | None = None
    policy_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_revision_chain(self) -> ContentRevision:
        if len(self.body_sha256) != 64:
            raise ValueError("body_sha256 must be a SHA-256 digest")
        if self.observed_at > self.available_at:
            raise ValueError("content cannot be available before observation")
        if self.revision == 1 and self.supersedes_revision is not None:
            raise ValueError("first revision cannot supersede another revision")
        if self.revision > 1 and self.supersedes_revision != self.revision - 1:
            raise ValueError("later revision must supersede its immediate predecessor")
        if self.modified_at is not None and self.modified_at < self.published_at:
            raise ValueError("modification cannot precede publication")
        if self.deleted_at is not None:
            if self.deleted_at < self.published_at:
                raise ValueError("deletion cannot precede publication")
            if self.original_text is not None:
                raise ValueError("deletion tombstone cannot retain public body text")
        elif not self.original_text:
            raise ValueError("non-deleted revision requires original text")
        return self


class TranslationAudit(DomainModel):
    translation_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    source_language: str = Field(min_length=2)
    target_language: str = Field(min_length=2)
    model_provider: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    procedure_version: str = Field(min_length=1)
    input_sha256: str
    output_sha256: str
    translated_text: str = Field(min_length=1)
    confidence: UnitInterval
    human_reviewed: bool
    created_at: UtcDateTime

    @model_validator(mode="after")
    def validate_translation(self) -> TranslationAudit:
        if self.source_language.casefold() == self.target_language.casefold():
            raise ValueError("translation languages must differ")
        if len(self.input_sha256) != 64 or len(self.output_sha256) != 64:
            raise ValueError("translation hashes must be SHA-256 digests")
        return self


class SourceCredibilityProfile(DomainModel):
    source_identity_id: str = Field(min_length=1)
    source_family_id: str = Field(min_length=1)
    domain_accuracy: UnitInterval
    correction_quality: UnitInterval
    officiality: UnitInterval
    manipulation_risk: UnitInterval
    identity_confidence: UnitInterval
    as_of_time: UtcDateTime
    evidence_count: int = Field(ge=0)

    @property
    def score(self) -> Decimal:
        positive = (
            self.domain_accuracy * Decimal("0.35")
            + self.correction_quality * Decimal("0.15")
            + self.officiality * Decimal("0.30")
            + self.identity_confidence * Decimal("0.20")
        )
        return max(Decimal("0"), positive * (Decimal("1") - self.manipulation_risk))


class EvidenceRelation(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"


class ClaimEvidence(DomainModel):
    claim_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    relation: EvidenceRelation
    source_family_id: str = Field(min_length=1)
    available_at: UtcDateTime
    policy_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)


class OntologyVersion(DomainModel):
    ontology_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    event_types: tuple[str, ...] = Field(min_length=1)
    relation_types: tuple[str, ...] = Field(min_length=1)
    published_at: UtcDateTime
    supersedes_version: str | None = None

    @model_validator(mode="after")
    def require_unique_terms(self) -> OntologyVersion:
        if len(set(self.event_types)) != len(self.event_types):
            raise ValueError("ontology event types must be unique")
        if len(set(self.relation_types)) != len(self.relation_types):
            raise ValueError("ontology relation types must be unique")
        return self


class AnnotationLabel(StrEnum):
    CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"
    AMBIGUOUS = "AMBIGUOUS"
    DUPLICATE = "DUPLICATE"
    MANIPULATION = "MANIPULATION"


class HumanAnnotation(DomainModel):
    annotation_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    ontology_version: str = Field(min_length=1)
    label: AnnotationLabel
    annotator_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    created_at: UtcDateTime


class ActiveLearningCandidate(DomainModel):
    target_id: str = Field(min_length=1)
    uncertainty: UnitInterval
    impact: UnitInterval
    novelty: UnitInterval
    policy_allowed: bool
    priority_score: FiniteDecimal

    @model_validator(mode="after")
    def validate_priority(self) -> ActiveLearningCandidate:
        expected = (
            (
                self.uncertainty * Decimal("0.5")
                + self.impact * Decimal("0.3")
                + self.novelty * Decimal("0.2")
            )
            if self.policy_allowed
            else Decimal("0")
        )
        if self.priority_score != expected:
            raise ValueError("active-learning priority must use the fixed audited formula")
        if not self.policy_allowed and self.priority_score != Decimal("0"):
            raise ValueError("policy-denied annotation candidate must have zero priority")
        return self
