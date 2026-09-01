"""Strict contracts for source provenance, evidence, audits, IR, and translation."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from aegisquant.data.hashing import ensure_sha256, safe_path_segment, safe_relative_path
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime

PositiveLine = Annotated[int, Field(gt=0)]
NonNegativeCount = Annotated[int, Field(ge=0)]


class KnowledgePlatform(StrEnum):
    JOINQUANT = "joinquant"
    RICEQUANT = "ricequant"
    BIGQUANT = "bigquant"
    GITHUB = "github"
    ACADEMIC = "academic"
    OTHER = "other"


class RightsStatus(StrEnum):
    PUBLIC_LICENSE = "public_license"
    PERSONAL_RESEARCH_ONLY = "personal_research_only"
    UNKNOWN = "unknown"
    PROHIBITED = "prohibited"


class ArtifactKind(StrEnum):
    MANIFEST = "manifest"
    HTML = "html"
    MARKDOWN = "markdown"
    PYTHON = "python"
    NOTEBOOK = "notebook"
    COMMENTS = "comments"
    ATTACHMENT = "attachment"
    SCREENSHOT = "screenshot"


class StaticReviewState(StrEnum):
    UNSCANNED = "UNSCANNED"
    QUARANTINED = "QUARANTINED"
    STATIC_ANALYZED = "STATIC_ANALYZED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EvidenceStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class ParameterProvenance(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    MISSING = "missing"


class AuditTag(StrEnum):
    REPRODUCED = "REPRODUCED"
    PARTIAL = "PARTIAL"
    INFORMATION_MISSING = "INFORMATION_MISSING"
    LEAKAGE = "LEAKAGE"
    SURVIVORSHIP_BIAS = "SURVIVORSHIP_BIAS"
    COST_SENSITIVE = "COST_SENSITIVE"
    EXECUTION_UNREALISTIC = "EXECUTION_UNREALISTIC"
    REGIME_DEPENDENT = "REGIME_DEPENDENT"
    DUPLICATE = "DUPLICATE"
    OVERFIT_RISK = "OVERFIT_RISK"
    TAIL_RISK_HIDDEN = "TAIL_RISK_HIDDEN"
    LICENSE_RESTRICTED = "LICENSE_RESTRICTED"
    ROBUST_CANDIDATE = "ROBUST_CANDIDATE"
    REJECTED = "REJECTED"


class SourceManifest(DomainModel):
    schema_version: Literal["1"] = "1"
    source_id: str
    platform: KnowledgePlatform
    url: str
    title: str = Field(min_length=1, max_length=500)
    author: str = Field(min_length=1, max_length=300)
    published_at: UtcDateTime | None = None
    updated_at: UtcDateTime | None = None
    exported_at_utc: UtcDateTime
    export_method: str = Field(min_length=1, max_length=100)
    user_had_access: bool
    content_types: tuple[ArtifactKind, ...]
    rights_status: RightsStatus
    original_language: str = Field(min_length=2, max_length=35)
    notes: str = Field(default="", max_length=2000)

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return safe_path_segment(value, field_name="source_id")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("source URL must use HTTP or HTTPS")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> SourceManifest:
        if not self.user_had_access:
            raise ValueError("manual export requires user_had_access=true")
        if not self.content_types:
            raise ValueError("source manifest requires at least one content type")
        if len(set(self.content_types)) != len(self.content_types):
            raise ValueError("source content types must be unique")
        if (
            self.updated_at is not None
            and self.published_at is not None
            and self.updated_at < self.published_at
        ):
            raise ValueError("source update cannot precede publication")
        return self


class SourceArtifact(DomainModel):
    artifact_id: str
    source_id: str
    relative_path: str
    kind: ArtifactKind
    sha256: str
    size_bytes: NonNegativeCount
    media_type: str
    sanitized_relative_path: str | None = None
    static_review_state: StaticReviewState
    execution_allowed: Literal[False] = False

    @field_validator("artifact_id", "sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="artifact hash")

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return safe_path_segment(value, field_name="source_id")

    @field_validator("relative_path", "sanitized_relative_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        return safe_relative_path(value) if value is not None else None


class RightsRecord(DomainModel):
    source_id: str
    status: RightsStatus
    license_identifier: str | None = None
    evidence_url: str | None = None
    public_text_export_allowed: bool = False
    internal_research_allowed: bool
    reviewed_at_utc: UtcDateTime

    @model_validator(mode="after")
    def enforce_rights(self) -> RightsRecord:
        if self.public_text_export_allowed and self.status is not RightsStatus.PUBLIC_LICENSE:
            raise ValueError("only public-license sources may export public text")
        if self.status is RightsStatus.PROHIBITED and self.internal_research_allowed:
            raise ValueError("prohibited sources cannot enter internal research")
        if self.status is RightsStatus.PUBLIC_LICENSE and not self.license_identifier:
            raise ValueError("public-license source requires a license identifier")
        return self


class EvidenceSpan(DomainModel):
    evidence_id: str
    source_id: str
    artifact_id: str
    artifact_sha256: str
    start_line: PositiveLine
    end_line: PositiveLine
    selector: str = Field(min_length=1, max_length=300)
    excerpt: str = Field(min_length=1, max_length=400)
    excerpt_sha256: str
    status: EvidenceStatus = EvidenceStatus.SUPPORTED

    @field_validator("artifact_id", "artifact_sha256", "excerpt_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="evidence hash")

    @model_validator(mode="after")
    def validate_lines(self) -> EvidenceSpan:
        if self.end_line < self.start_line:
            raise ValueError("evidence line range is reversed")
        return self


class FeatureIR(DomainModel):
    feature_id: str
    formula: str | None
    lookback: str | None
    availability_lag: str | None
    evidence_ids: tuple[str, ...]
    status: EvidenceStatus

    @model_validator(mode="after")
    def require_evidence_or_missing(self) -> FeatureIR:
        if self.status is EvidenceStatus.SUPPORTED and not self.evidence_ids:
            raise ValueError("supported feature requires evidence")
        if self.status is EvidenceStatus.UNSUPPORTED and self.evidence_ids:
            raise ValueError("unsupported feature cannot claim evidence")
        return self


class StrategyRuleIR(DomainModel):
    rule_id: str
    expression: str | None
    evidence_ids: tuple[str, ...]
    status: EvidenceStatus

    @model_validator(mode="after")
    def require_evidence_or_missing(self) -> StrategyRuleIR:
        if self.status is EvidenceStatus.SUPPORTED and not self.evidence_ids:
            raise ValueError("supported rule requires evidence")
        if self.status is EvidenceStatus.UNSUPPORTED and self.evidence_ids:
            raise ValueError("unsupported rule cannot claim evidence")
        return self


class ParameterIR(DomainModel):
    name: str
    value: JsonValue | None
    provenance: ParameterProvenance
    evidence_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_provenance(self) -> ParameterIR:
        if self.provenance is ParameterProvenance.MISSING:
            if self.value is not None or self.evidence_ids:
                raise ValueError("missing parameter cannot carry value or evidence")
        elif self.value is None or not self.evidence_ids:
            raise ValueError("explicit/inferred parameter requires value and evidence")
        return self


class StrategyIR(DomainModel):
    strategy_ir_version: Literal["1"] = "1"
    strategy_id: str
    source_ids: tuple[str, ...] = Field(min_length=1)
    universe_selection_time: str | None
    universe_eligibility_rules: tuple[StrategyRuleIR, ...]
    data_requirements: tuple[str, ...]
    features: tuple[FeatureIR, ...]
    signals: tuple[StrategyRuleIR, ...]
    entries: tuple[StrategyRuleIR, ...]
    exits: tuple[StrategyRuleIR, ...]
    position_sizing: tuple[StrategyRuleIR, ...]
    rebalance: tuple[StrategyRuleIR, ...]
    execution_assumptions: tuple[StrategyRuleIR, ...]
    risk_controls: tuple[StrategyRuleIR, ...]
    parameters: tuple[ParameterIR, ...]
    backtest_evidence: dict[str, JsonValue]
    known_unknowns: tuple[str, ...]

    @model_validator(mode="after")
    def validate_ir(self) -> StrategyIR:
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("strategy source IDs must be unique")
        parameter_names = [item.name for item in self.parameters]
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("strategy parameter names must be unique")
        evidence_ids = [
            evidence_id
            for group in (
                self.universe_eligibility_rules,
                self.features,
                self.signals,
                self.entries,
                self.exits,
                self.position_sizing,
                self.rebalance,
                self.execution_assumptions,
                self.risk_controls,
                self.parameters,
            )
            for item in group
            for evidence_id in item.evidence_ids
        ]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("each evidence span may support only one IR assertion")
        return self


class StaticFinding(DomainModel):
    finding_id: str
    category: str
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    line: PositiveLine
    symbol: str
    message: str


class StaticAnalysisReport(DomainModel):
    schema_version: Literal["1"] = "1"
    source_id: str
    artifact_id: str
    artifact_sha256: str
    language: Literal["python", "python-notebook"]
    syntax_valid: bool
    imports: tuple[str, ...]
    platform_apis: tuple[str, ...]
    parameters: tuple[str, ...]
    scheduled_callbacks: tuple[str, ...]
    data_calls: tuple[str, ...]
    trade_calls: tuple[str, ...]
    risk_calls: tuple[str, ...]
    findings: tuple[StaticFinding, ...]
    review_state: StaticReviewState
    executable_allowed: Literal[False] = False

    @field_validator("artifact_id", "artifact_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="static analysis hash")

    @model_validator(mode="after")
    def validate_review_state(self) -> StaticAnalysisReport:
        dangerous = any(item.severity in {"HIGH", "CRITICAL"} for item in self.findings)
        expected = (
            StaticReviewState.QUARANTINED
            if not self.syntax_valid or dangerous
            else StaticReviewState.REVIEW_REQUIRED
        )
        if self.review_state is not expected:
            raise ValueError("static review state does not match findings")
        return self


class AuditFinding(DomainModel):
    tag: AuditTag
    code: str
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    message: str
    evidence_ids: tuple[str, ...]


class StrategyAudit(DomainModel):
    strategy_id: str
    findings: tuple[AuditFinding, ...]
    tags: tuple[AuditTag, ...]
    publication_allowed: Literal[False] = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def tags_match_findings(self) -> StrategyAudit:
        expected = tuple(sorted({item.tag for item in self.findings}, key=str))
        if self.tags != expected:
            raise ValueError("audit tags must be the sorted unique finding tags")
        return self


class DedupeFingerprint(DomainModel):
    strategy_id: str
    content_sha256: str
    normalized_ast_sha256: str
    strategy_ir_sha256: str
    signal_fingerprint: tuple[str, ...]
    trade_holding_fingerprint: tuple[str, ...]
    factor_regime_fingerprint: tuple[str, ...]
    residual_alpha_fingerprint: tuple[str, ...]

    @field_validator("content_sha256", "normalized_ast_sha256", "strategy_ir_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="dedupe hash")


class DuplicateCluster(DomainModel):
    cluster_id: str
    strategy_ids: tuple[str, ...] = Field(min_length=1)
    matching_layers: tuple[str, ...] = Field(min_length=1)
    independent_alpha_count: Literal[1] = 1


class TranslationRecord(DomainModel):
    translation_id: str
    source_strategy_id: str
    target_strategy_id: str
    source_market_concept: str
    crypto_mapping: str
    semantic_changes: tuple[str, ...] = Field(min_length=1)
    required_rechecks: tuple[str, ...] = Field(min_length=1)
    source_code_reused: Literal[False] = False
    external_return_used_as_evidence: Literal[False] = False
    execution_allowed: Literal[False] = False


class KnowledgeProposal(DomainModel):
    proposal_id: str
    strategy_id: str
    source_ids: tuple[str, ...] = Field(min_length=1)
    claimed_evidence_ids: tuple[str, ...] = Field(min_length=1)
    candidate_ir: StrategyIR
    state: Literal["PROPOSED"] = "PROPOSED"
    action: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"
    ai_generated: Literal[True] = True
