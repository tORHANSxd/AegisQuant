"""Evidence-bound Event Expert Committee and deterministic Arbiter."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import FiniteDecimal, UnitInterval


class ExpertRole(StrEnum):
    EXTRACTOR = "EXTRACTOR"
    ENTITY = "ENTITY"
    SOURCE = "SOURCE"
    CORROBORATION = "CORROBORATION"
    SKEPTIC = "SKEPTIC"
    MARKET = "MARKET"
    ON_CHAIN = "ON_CHAIN"
    IMPACT = "IMPACT"
    POLICY = "POLICY"
    ARBITER = "ARBITER"


REQUIRED_EXPERTS = frozenset(ExpertRole) - {ExpertRole.ARBITER}


class EvidenceClaim(DomainModel):
    claim_id: str
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    supports: bool


class ExpertFinding(DomainModel):
    role: ExpertRole
    claims: tuple[EvidenceClaim, ...]
    semantic_confidence: UnitInterval
    factual_confidence: UnitInterval
    impact_confidence: UnitInterval
    directional_score: FiniteDecimal = Decimal("0")
    conflicts: tuple[str, ...] = ()
    should_abstain: bool
    abstain_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def validate_finding(self) -> ExpertFinding:
        if not Decimal("-1") <= self.directional_score <= Decimal("1"):
            raise ValueError("expert directional score must be in [-1, 1]")
        if self.should_abstain != bool(self.abstain_reasons):
            raise ValueError("expert abstain flag and reasons must agree")
        return self


class ArbiterDecision(DomainModel):
    accepted_claim_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    semantic_confidence: UnitInterval
    factual_confidence: UnitInterval
    impact_confidence: UnitInterval
    directional_score: FiniteDecimal
    evidence_coverage: UnitInterval
    conflicts: tuple[str, ...]
    should_abstain: bool
    abstain_reasons: tuple[str, ...]
    action: str = "RESEARCH_PROPOSAL_ONLY"

    @model_validator(mode="after")
    def enforce_boundary(self) -> ArbiterDecision:
        if self.action != "RESEARCH_PROPOSAL_ONLY":
            raise ValueError("arbiter cannot publish or execute")
        if self.should_abstain != bool(self.abstain_reasons):
            raise ValueError("arbiter abstain flag and reasons must agree")
        return self


class CommitteeResult(DomainModel):
    findings: tuple[ExpertFinding, ...]
    arbiter: ArbiterDecision

    @model_validator(mode="after")
    def require_committee(self) -> CommitteeResult:
        if {item.role for item in self.findings} != set(REQUIRED_EXPERTS):
            raise ValueError("event committee expert roster is incomplete or duplicated")
        return self


def arbitrate(
    *, findings: tuple[ExpertFinding, ...], allowed_evidence_ids: frozenset[str]
) -> CommitteeResult:
    if {item.role for item in findings} != set(REQUIRED_EXPERTS):
        raise ValueError("event committee expert roster is incomplete or duplicated")
    claims = {claim.claim_id: claim for finding in findings for claim in finding.claims}
    if len(claims) != sum(len(item.claims) for item in findings):
        raise ValueError("committee claim ids must be unique")
    used_evidence = {
        evidence_id
        for finding in findings
        for claim in finding.claims
        for evidence_id in claim.evidence_ids
    }
    if not used_evidence.issubset(allowed_evidence_ids):
        raise ValueError("AQ-ARBITER-EVIDENCE-ESCALATION")
    accepted = tuple(sorted(claim.claim_id for claim in claims.values() if claim.supports))
    coverage = (
        Decimal(len(used_evidence)) / Decimal(len(allowed_evidence_ids))
        if allowed_evidence_ids
        else Decimal("0")
    )
    semantic = min(item.semantic_confidence for item in findings)
    factual = min(item.factual_confidence for item in findings)
    impact = min(item.impact_confidence for item in findings)
    directional_roles = {ExpertRole.MARKET, ExpertRole.ON_CHAIN, ExpertRole.IMPACT}
    directional = sum(
        (item.directional_score for item in findings if item.role in directional_roles),
        Decimal("0"),
    ) / Decimal(len(directional_roles))
    conflicts = tuple(sorted({value for item in findings for value in item.conflicts}))
    reasons = tuple(sorted({reason for item in findings for reason in item.abstain_reasons}))
    if coverage < Decimal("0.5"):
        reasons = tuple(sorted({*reasons, "LOW_EVIDENCE_COVERAGE"}))
    if conflicts:
        reasons = tuple(sorted({*reasons, "UNRESOLVED_CONFLICT"}))
    arbiter = ArbiterDecision(
        accepted_claim_ids=accepted,
        evidence_ids=tuple(sorted(used_evidence)),
        semantic_confidence=semantic,
        factual_confidence=factual,
        impact_confidence=impact,
        directional_score=directional,
        evidence_coverage=coverage,
        conflicts=conflicts,
        should_abstain=bool(reasons),
        abstain_reasons=reasons,
    )
    return CommitteeResult(findings=findings, arbiter=arbiter)
