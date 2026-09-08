"""Auditable multilingual normalization, event evidence, credibility, and committee paths."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import NarrativeId
from aegisquant.domain.intelligence import EventClusterStatus, NarrativeState
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.values import FiniteDecimal, UnitInterval
from aegisquant.intelligence.committee import (
    CommitteeResult,
    ExpertFinding,
    ExpertRole,
    arbitrate,
)
from aegisquant.intelligence.graph import transition_event_state
from aegisquant.intelligence.pipeline import detect_language, link_entities, normalize_text
from aegisquant.intelligence.world.models import (
    ActiveLearningCandidate,
    ClaimEvidence,
    ContentRevision,
    EvidenceRelation,
    SourceCredibilityProfile,
    TranslationAudit,
)


class NormalizedContent(DomainModel):
    content_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    provider_id: str = Field(min_length=1)
    source_family_hint: str = Field(min_length=1)
    original_language: str = Field(min_length=2)
    detected_language: str = Field(min_length=2)
    normalized_text: str = Field(min_length=1)
    original_sha256: str
    normalized_sha256: str
    available_at: UtcDateTime
    upstream_content_id: str | None = None

    @model_validator(mode="after")
    def validate_hashes(self) -> NormalizedContent:
        if len(self.original_sha256) != 64 or len(self.normalized_sha256) != 64:
            raise ValueError("normalized content hashes must be SHA-256")
        return self


def normalize_revision(
    revision: ContentRevision, *, upstream_content_id: str | None = None
) -> NormalizedContent:
    if revision.deleted_at is not None or revision.original_text is None:
        raise ValueError("deletion tombstone has no text to normalize")
    normalized = normalize_text(revision.original_text)
    if not normalized:
        raise ValueError("normalized content cannot be empty")
    original_hash = hashlib.sha256(revision.original_text.encode("utf-8")).hexdigest()
    if original_hash != revision.body_sha256:
        raise ValueError("content body hash does not match original text")
    return NormalizedContent(
        content_id=revision.content_id,
        revision=revision.revision,
        provider_id=revision.provider_id,
        source_family_hint=revision.source_family_id,
        original_language=revision.original_language,
        detected_language=detect_language(revision.original_text, revision.original_language),
        normalized_text=normalized,
        original_sha256=original_hash,
        normalized_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        available_at=revision.available_at,
        upstream_content_id=upstream_content_id,
    )


def record_translation(
    *,
    content: NormalizedContent,
    translated_text: str,
    target_language: str,
    model_provider: str,
    model_version: str,
    procedure_version: str,
    confidence: Decimal,
    human_reviewed: bool,
    created_at: datetime,
) -> TranslationAudit:
    clean_output = translated_text.strip()
    if not clean_output:
        raise ValueError("translated text cannot be empty")
    output_hash = hashlib.sha256(clean_output.encode("utf-8")).hexdigest()
    identity = {
        "content_id": content.content_id,
        "revision": content.revision,
        "input_sha256": content.original_sha256,
        "output_sha256": output_hash,
        "model_provider": model_provider,
        "model_version": model_version,
        "procedure_version": procedure_version,
    }
    return TranslationAudit(
        translation_id=canonical_sha256(identity),
        content_id=content.content_id,
        revision=content.revision,
        source_language=content.detected_language,
        target_language=target_language,
        model_provider=model_provider,
        model_version=model_version,
        procedure_version=procedure_version,
        input_sha256=content.original_sha256,
        output_sha256=output_hash,
        translated_text=clean_output,
        confidence=confidence,
        human_reviewed=human_reviewed,
        created_at=ensure_utc(created_at),
    )


class RepostFamily(DomainModel):
    family_id: str
    member_content_ids: tuple[str, ...] = Field(min_length=1)
    providers: tuple[str, ...] = Field(min_length=1)
    canonical_content_id: str
    independent_evidence_count: int = 1
    exact_duplicate_count: int = Field(ge=0)
    near_duplicate_count: int = Field(ge=0)
    explicit_repost_count: int = Field(ge=0)

    @model_validator(mode="after")
    def one_family_is_one_witness(self) -> RepostFamily:
        if self.independent_evidence_count != 1:
            raise ValueError("one repost family contributes exactly one independent witness")
        if self.canonical_content_id not in self.member_content_ids:
            raise ValueError("repost family canonical content must be a member")
        return self


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[\w]+", value, flags=re.UNICODE))


def _jaccard(left: str, right: str) -> Decimal:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    union = left_tokens | right_tokens
    if not union:
        return Decimal("1")
    return Decimal(len(left_tokens & right_tokens)) / Decimal(len(union))


def build_repost_families(
    contents: Sequence[NormalizedContent], *, near_duplicate_threshold: Decimal = Decimal("0.8")
) -> tuple[RepostFamily, ...]:
    if not Decimal("0.5") <= near_duplicate_threshold <= Decimal("1"):
        raise ValueError("near-duplicate threshold must be in [0.5, 1]")
    by_id = {item.content_id: item for item in contents}
    if len(by_id) != len(contents):
        raise ValueError("normalized content ids must be unique")
    parent = {item.content_id: item.content_id for item in contents}

    def root(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = root(left)
        right_root = root(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    ordered = sorted(contents, key=lambda item: item.content_id)
    for index, left in enumerate(ordered):
        if left.upstream_content_id is not None:
            if left.upstream_content_id not in by_id:
                raise ValueError("explicit repost references unknown content")
            union(left.content_id, left.upstream_content_id)
        for right in ordered[index + 1 :]:
            if (
                left.normalized_sha256 == right.normalized_sha256
                or _jaccard(left.normalized_text, right.normalized_text) >= near_duplicate_threshold
            ):
                union(left.content_id, right.content_id)

    grouped: dict[str, list[NormalizedContent]] = defaultdict(list)
    for item in ordered:
        grouped[root(item.content_id)].append(item)
    families: list[RepostFamily] = []
    for members in grouped.values():
        member_ids = tuple(sorted(item.content_id for item in members))
        canonical_id = min(
            members,
            key=lambda item: (item.available_at, item.content_id),
        ).content_id
        exact = sum(
            1
            for item in members
            if item.content_id != canonical_id
            and item.normalized_sha256 == by_id[canonical_id].normalized_sha256
        )
        explicit = sum(item.upstream_content_id is not None for item in members)
        near = len(members) - 1 - exact
        families.append(
            RepostFamily(
                family_id=canonical_sha256({"members": member_ids}),
                member_content_ids=member_ids,
                providers=tuple(sorted({item.provider_id for item in members})),
                canonical_content_id=canonical_id,
                exact_duplicate_count=exact,
                near_duplicate_count=max(0, near),
                explicit_repost_count=explicit,
            )
        )
    return tuple(sorted(families, key=lambda item: item.family_id))


class EntityResolution(DomainModel):
    content_id: str
    canonical_entity_ids: tuple[str, ...]
    alias_version: str
    evidence_text_sha256: str


def link_cross_platform_entities(
    content: NormalizedContent,
    *,
    approved_aliases: Mapping[str, str] | None = None,
    alias_version: str = "entities-p10-v1",
) -> EntityResolution:
    entities = set(link_entities(content.normalized_text))
    for alias, entity_id in dict(approved_aliases or {}).items():
        if re.search(rf"(?<!\w){re.escape(normalize_text(alias))}(?!\w)", content.normalized_text):
            entities.add(entity_id)
    return EntityResolution(
        content_id=content.content_id,
        canonical_entity_ids=tuple(sorted(entities)),
        alias_version=alias_version,
        evidence_text_sha256=content.normalized_sha256,
    )


class IndependentEvidenceSummary(DomainModel):
    profile_count: int = Field(ge=0)
    independent_family_count: int = Field(ge=0)
    mean_family_score: UnitInterval
    official_family_count: int = Field(ge=0)
    high_manipulation_family_count: int = Field(ge=0)


def summarize_independent_evidence(
    profiles: Sequence[SourceCredibilityProfile],
) -> IndependentEvidenceSummary:
    best_by_family: dict[str, SourceCredibilityProfile] = {}
    for profile in profiles:
        current = best_by_family.get(profile.source_family_id)
        if current is None or profile.score > current.score:
            best_by_family[profile.source_family_id] = profile
    selected = tuple(best_by_family.values())
    mean = (
        sum((profile.score for profile in selected), Decimal("0")) / Decimal(len(selected))
        if selected
        else Decimal("0")
    )
    return IndependentEvidenceSummary(
        profile_count=len(profiles),
        independent_family_count=len(selected),
        mean_family_score=mean,
        official_family_count=sum(profile.officiality >= Decimal("0.8") for profile in selected),
        high_manipulation_family_count=sum(
            profile.manipulation_risk >= Decimal("0.7") for profile in selected
        ),
    )


def next_event_state(
    *,
    current: EventClusterStatus,
    evidence: IndependentEvidenceSummary,
    official_confirmation: bool,
    official_denial: bool,
    resolved: bool,
) -> EventClusterStatus:
    return transition_event_state(
        current=current,
        independent_sources=evidence.independent_family_count,
        official_confirmation=official_confirmation,
        official_denial=official_denial,
        resolved=resolved,
    )


class CommitteePath(StrEnum):
    FAST = "FAST"
    DEEP = "DEEP"


class AuditedCommitteeDecision(DomainModel):
    path: CommitteePath
    committee: CommitteeResult
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    policy_ids: tuple[str, ...] = Field(min_length=1)
    model_versions: tuple[str, ...] = Field(min_length=1)
    max_context_items: int = Field(gt=0)
    reasoning_passes: int = Field(gt=0)
    action: str = "RESEARCH_PROPOSAL_ONLY"

    @model_validator(mode="after")
    def enforce_research_boundary(self) -> AuditedCommitteeDecision:
        if self.action != "RESEARCH_PROPOSAL_ONLY":
            raise ValueError("event committee cannot construct or submit orders")
        roles = {finding.role for finding in self.committee.findings}
        if ExpertRole.SKEPTIC not in roles:
            raise ValueError("event committee requires Skeptic")
        if set(self.committee.arbiter.evidence_ids) - set(self.evidence_ids):
            raise ValueError("committee used evidence outside audited bundle")
        expected = (24, 1) if self.path is CommitteePath.FAST else (128, 3)
        if (self.max_context_items, self.reasoning_passes) != expected:
            raise ValueError("committee path budget is not the fixed audited budget")
        return self


def run_committee_path(
    *,
    path: CommitteePath,
    findings: tuple[ExpertFinding, ...],
    evidence_ids: tuple[str, ...],
    policy_ids: tuple[str, ...],
    model_versions: tuple[str, ...],
) -> AuditedCommitteeDecision:
    if not evidence_ids or not policy_ids or not model_versions:
        raise ValueError("committee requires evidence, policy, and model provenance")
    committee = arbitrate(findings=findings, allowed_evidence_ids=frozenset(evidence_ids))
    max_context_items, reasoning_passes = (24, 1) if path is CommitteePath.FAST else (128, 3)
    return AuditedCommitteeDecision(
        path=path,
        committee=committee,
        evidence_ids=tuple(sorted(set(evidence_ids))),
        policy_ids=tuple(sorted(set(policy_ids))),
        model_versions=tuple(sorted(set(model_versions))),
        max_context_items=max_context_items,
        reasoning_passes=reasoning_passes,
    )


class EventAuditBundle(DomainModel):
    event_cluster_id: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[ClaimEvidence, ...] = Field(min_length=1)
    independent_source_families: tuple[str, ...] = Field(min_length=1)
    policy_ids: tuple[str, ...] = Field(min_length=1)
    model_versions: tuple[str, ...] = Field(min_length=1)
    conflicts: tuple[str, ...]
    skeptic_claim_ids: tuple[str, ...]
    should_abstain: bool
    abstain_reasons: tuple[str, ...]
    as_of_time: UtcDateTime

    @model_validator(mode="after")
    def validate_high_impact_trace(self) -> EventAuditBundle:
        if self.should_abstain != bool(self.abstain_reasons):
            raise ValueError("event audit abstention flag and reasons disagree")
        if any(item.available_at > self.as_of_time for item in self.evidence):
            raise ValueError("event audit bundle contains future evidence")
        evidence_claims = {item.claim_id for item in self.evidence}
        if not set(self.claim_ids).issubset(evidence_claims):
            raise ValueError("event claim lacks support/refute evidence")
        if {item.policy_id for item in self.evidence} != set(self.policy_ids):
            raise ValueError("event policy provenance is incomplete")
        if {item.model_version for item in self.evidence} - set(self.model_versions):
            raise ValueError("event model provenance is incomplete")
        return self


def build_event_audit_bundle(
    *,
    event_cluster_id: str,
    claim_ids: tuple[str, ...],
    evidence: tuple[ClaimEvidence, ...],
    committee: AuditedCommitteeDecision,
    as_of_time: datetime,
) -> EventAuditBundle:
    families = tuple(sorted({item.source_family_id for item in evidence}))
    skeptic = next(
        finding for finding in committee.committee.findings if finding.role is ExpertRole.SKEPTIC
    )
    return EventAuditBundle(
        event_cluster_id=event_cluster_id,
        claim_ids=tuple(sorted(set(claim_ids))),
        evidence=evidence,
        independent_source_families=families,
        policy_ids=tuple(sorted({item.policy_id for item in evidence})),
        model_versions=committee.model_versions,
        conflicts=committee.committee.arbiter.conflicts,
        skeptic_claim_ids=tuple(claim.claim_id for claim in skeptic.claims),
        should_abstain=committee.committee.arbiter.should_abstain,
        abstain_reasons=committee.committee.arbiter.abstain_reasons,
        as_of_time=ensure_utc(as_of_time),
    )


class NarrativeObservation(DomainModel):
    content_id: str
    source_family_id: str
    author_id: str
    platform: str
    observed_at: UtcDateTime
    sentiment: FiniteDecimal
    engagement_delta: int = Field(ge=0)

    @model_validator(mode="after")
    def sentiment_is_bounded(self) -> NarrativeObservation:
        if not Decimal("-1") <= self.sentiment <= Decimal("1"):
            raise ValueError("sentiment must be in [-1, 1]")
        return self


def build_narrative_state(
    *,
    topic: str,
    entity_ids: tuple[str, ...],
    observations: Sequence[NarrativeObservation],
    as_of_time: datetime,
    window_hours: Decimal,
) -> NarrativeState:
    as_of = ensure_utc(as_of_time)
    if window_hours <= 0 or not observations:
        raise ValueError("narrative requires observations and a positive window")
    if any(item.observed_at > as_of for item in observations):
        raise ValueError("narrative cannot use future observation")
    families = {item.source_family_id for item in observations}
    authors = {item.author_id for item in observations}
    platforms = {item.platform for item in observations}
    duplicate_ratio = Decimal(len(observations) - len(families)) / Decimal(len(observations))
    sentiment = sum((item.sentiment for item in observations), Decimal("0")) / Decimal(
        len(observations)
    )
    engagement_velocity = (
        Decimal(sum(item.engagement_delta for item in observations)) / window_hours
    )
    first = min(item.observed_at for item in observations)
    identity = {
        "topic": topic,
        "entities": sorted(entity_ids),
        "first": first.isoformat(),
    }
    return NarrativeState(
        narrative_id=NarrativeId(canonical_sha256(identity)),
        topic=topic,
        entity_ids=entity_ids,
        first_observed_time=first,
        as_of_time=as_of,
        propagation_stage="EMERGING" if len(platforms) < 2 else "CROSS_PLATFORM",
        posts_per_hour=Decimal(len(observations)) / window_hours,
        independent_author_count=len(authors),
        platform_count=len(platforms),
        sentiment_score=sentiment,
        contradicting_evidence_count=0,
        engagement_velocity_per_hour=engagement_velocity,
        coordination_risk=duplicate_ratio,
        price_reflection_score=Decimal("0"),
        decay_half_life_hours=window_hours,
        crowding_score=duplicate_ratio,
    )


def active_learning_queue(
    values: Sequence[tuple[str, Decimal, Decimal, Decimal, bool]], *, limit: int
) -> tuple[ActiveLearningCandidate, ...]:
    if limit < 1:
        raise ValueError("active-learning queue limit must be positive")
    candidates: list[ActiveLearningCandidate] = []
    for target_id, uncertainty, impact, novelty, policy_allowed in values:
        score = (
            uncertainty * Decimal("0.5") + impact * Decimal("0.3") + novelty * Decimal("0.2")
            if policy_allowed
            else Decimal("0")
        )
        candidates.append(
            ActiveLearningCandidate(
                target_id=target_id,
                uncertainty=uncertainty,
                impact=impact,
                novelty=novelty,
                policy_allowed=policy_allowed,
                priority_score=score,
            )
        )
    return tuple(
        sorted(candidates, key=lambda item: (-item.priority_score, item.target_id))[:limit]
    )


def evidence_relation_counts(evidence: Sequence[ClaimEvidence]) -> dict[EvidenceRelation, int]:
    counts = {EvidenceRelation.SUPPORTS: 0, EvidenceRelation.REFUTES: 0}
    for item in evidence:
        counts[item.relation] += 1
    return counts
