"""Strict P02 provider, dataset, quality, inventory, and time contracts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256, safe_relative_path
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ArtifactId, DatasetId, ProviderId, SourcePolicyId
from aegisquant.domain.time import UtcDateTime


class ProviderType(StrEnum):
    EXCHANGE = "exchange"
    MACRO = "macro"
    ONCHAIN = "onchain"
    NEWS = "news"
    COMMUNITY = "community"
    VENDOR = "vendor"
    LOCAL = "local"


class ProviderAccessMethod(StrEnum):
    REST = "rest"
    WEBSOCKET = "websocket"
    SDK = "sdk"
    FILE = "file"
    MANUAL_EXPORT = "manual_export"


class AuthorityLevel(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DERIVED = "derived"


class LicenseStatus(StrEnum):
    APPROVED = "approved"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


class ProviderStatus(StrEnum):
    CANDIDATE = "candidate"
    TRIAL = "trial"
    APPROVED = "approved"
    DEGRADED = "degraded"
    RETIRED = "retired"


class LakeLayer(StrEnum):
    RAW = "raw"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    QUARANTINE = "quarantine"


class QualitySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ImportAction(StrEnum):
    REVIEW = "REVIEW"
    REJECT = "REJECT"
    ELIGIBLE_AFTER_APPROVAL = "ELIGIBLE_AFTER_APPROVAL"


class ProviderRegistryEntry(DomainModel):
    provider_id: ProviderId
    provider_name: str
    provider_type: ProviderType
    access_method: ProviderAccessMethod
    authority_level: AuthorityLevel
    license_status: LicenseStatus
    credentials_required: bool
    regions_or_account_constraints: tuple[str, ...] = ()
    rate_limits: dict[str, int] = Field(default_factory=dict)
    latency_expectation_ms: int | None = None
    revision_policy: str
    supported_datasets: tuple[str, ...] = ()
    time_semantics_documented: bool
    retention_policy: str
    quality_score: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    incremental_value_score: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    status: ProviderStatus
    owner: str
    source_policy_id: SourcePolicyId

    @model_validator(mode="after")
    def validate_registry_entry(self) -> ProviderRegistryEntry:
        if not self.provider_name.strip() or not self.owner.strip():
            raise ValueError("provider name and owner cannot be blank")
        if self.latency_expectation_ms is not None and self.latency_expectation_ms < 0:
            raise ValueError("latency expectation cannot be negative")
        if any(limit < 1 for limit in self.rate_limits.values()):
            raise ValueError("rate limits must be positive")
        if (
            self.status is ProviderStatus.APPROVED
            and self.license_status is not LicenseStatus.APPROVED
        ):
            raise ValueError("approved provider requires approved license status")
        if self.status is ProviderStatus.APPROVED and not self.time_semantics_documented:
            raise ValueError("approved provider requires documented time semantics")
        return self


class ProviderRegistryDocument(DomainModel):
    schema_version: str
    providers: tuple[ProviderRegistryEntry, ...]

    @model_validator(mode="after")
    def require_unique_providers(self) -> ProviderRegistryDocument:
        provider_ids = [str(entry.provider_id) for entry in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider registry contains duplicate provider IDs")
        policy_ids = [str(entry.source_policy_id) for entry in self.providers]
        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("provider registry contains duplicate policy IDs")
        return self


class ContentTimeSemantics(DomainModel):
    event_time: UtcDateTime
    available_time: UtcDateTime
    ingest_time: UtcDateTime
    revision_time: UtcDateTime | None = None
    published_time: UtcDateTime | None = None
    observed_time: UtcDateTime | None = None
    modified_time: UtcDateTime | None = None
    deleted_time: UtcDateTime | None = None
    engagement_snapshot_time: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_time_order(self) -> ContentTimeSemantics:
        if not self.event_time <= self.available_time <= self.ingest_time:
            raise ValueError("event_time <= available_time <= ingest_time is required")
        bounded_by_available = (
            self.revision_time,
            self.published_time,
            self.observed_time,
            self.modified_time,
            self.deleted_time,
            self.engagement_snapshot_time,
        )
        if any(value is not None and value > self.available_time for value in bounded_by_available):
            raise ValueError("content observation times cannot exceed available_time")
        if (
            self.published_time is not None
            and self.observed_time is not None
            and self.published_time > self.observed_time
        ):
            raise ValueError("published_time cannot exceed observed_time")
        return self


class DatasetFile(DomainModel):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    rows: int = Field(ge=0)
    schema_sha256: str
    min_time: UtcDateTime | None = None
    max_time: UtcDateTime | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return safe_relative_path(value)

    @field_validator("sha256", "schema_sha256")
    @classmethod
    def validate_hash(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "hash")
        return ensure_sha256(value, field_name=str(field_name))

    @model_validator(mode="after")
    def validate_time_range(self) -> DatasetFile:
        if (
            self.min_time is not None
            and self.max_time is not None
            and self.min_time > self.max_time
        ):
            raise ValueError("file min_time cannot exceed max_time")
        return self


class DatasetManifest(DomainModel):
    manifest_version: str = "1.0.0"
    dataset_id: DatasetId
    dataset_name: str
    schema_version: str
    provider_id: ProviderId
    layer: LakeLayer
    time_range: tuple[UtcDateTime | None, UtcDateTime | None]
    available_time_policy: str
    files: tuple[DatasetFile, ...]
    row_count: int = Field(ge=0)
    transform_commit: str
    transform_config_hash: str
    source_request_hash: str
    quality_report_id: ArtifactId
    lineage_hash: str
    created_at_utc: UtcDateTime

    @field_validator("transform_config_hash", "source_request_hash", "lineage_hash")
    @classmethod
    def validate_manifest_hashes(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "hash")
        return ensure_sha256(value, field_name=str(field_name))

    @field_validator("transform_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("transform_commit must be a full lowercase Git SHA")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> DatasetManifest:
        if not self.files:
            raise ValueError("dataset manifest must contain at least one file")
        if self.row_count != sum(file.rows for file in self.files):
            raise ValueError("manifest row_count must equal the file row sum")
        paths = [file.path for file in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest file paths must be unique")
        start, end = self.time_range
        if start is not None and end is not None and start > end:
            raise ValueError("manifest time range is reversed")
        expected = DatasetId(self.identity_hash())
        if self.dataset_id != expected:
            raise ValueError("dataset_id must equal the deterministic manifest identity hash")
        return self

    def identity_payload(self) -> dict[str, object]:
        """Return immutable identity fields, excluding operational creation time and ID."""
        return self.model_dump(mode="json", exclude={"dataset_id", "created_at_utc"})

    def identity_hash(self) -> str:
        return canonical_sha256(self.identity_payload())

    def manifest_hash(self) -> str:
        """Return the stable identity hash used by training, backtests, and reports."""
        return self.identity_hash()


class QualityIssue(DomainModel):
    rule_id: str
    severity: QualitySeverity
    message: str
    affected_rows: int = Field(ge=0)


class QualityReport(DomainModel):
    quality_report_id: ArtifactId
    dataset_name: str
    evaluated_at: UtcDateTime
    passed: bool
    issues: tuple[QualityIssue, ...] = ()

    @model_validator(mode="after")
    def match_status_to_issues(self) -> QualityReport:
        has_error = any(issue.severity is QualitySeverity.ERROR for issue in self.issues)
        if self.passed == has_error:
            raise ValueError("quality report passed flag disagrees with ERROR issues")
        return self


class InventoryRecord(DomainModel):
    dataset_id: DatasetId
    root_label: str
    relative_path: str
    extension: str
    mime_type: str | None = None
    size_bytes: int = Field(ge=0)
    modified_time: UtcDateTime
    sha256: str
    row_count: int | None = Field(default=None, ge=0)
    arrow_schema_json: str | None = Field(default=None, alias="schema_json")
    schema_sha256: str | None = None
    min_time: UtcDateTime | None = None
    max_time: UtcDateTime | None = None
    duplicate_group: str | None = None
    possible_strategy_result: bool

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return safe_relative_path(value)

    @field_validator("sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="sha256")

    @field_validator("schema_sha256")
    @classmethod
    def validate_optional_schema_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name="schema_sha256")


class ImportProposal(DomainModel):
    dataset_id: DatasetId
    relative_path: str
    action: ImportAction
    reasons: tuple[str, ...]
    requires_static_analysis: bool
    requires_user_approval: bool = True

    @field_validator("relative_path")
    @classmethod
    def validate_proposal_path(cls, value: str) -> str:
        return safe_relative_path(value)

    @model_validator(mode="after")
    def require_reason(self) -> ImportProposal:
        if not self.reasons:
            raise ValueError("import proposal must explain its action")
        if not self.requires_user_approval:
            raise ValueError("unknown assets always require explicit user approval")
        return self
