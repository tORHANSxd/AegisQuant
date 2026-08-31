"""Machine-executable source processing policy with fail-closed boundaries."""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.errors import DomainError, ErrorDisposition
from aegisquant.domain.identifiers import ProviderId, SourcePolicyId
from aegisquant.domain.time import UtcDateTime


class PolicyStatus(StrEnum):
    APPROVED = "APPROVED"
    RESTRICTED = "RESTRICTED"
    DENIED = "DENIED"


class AccessMethod(StrEnum):
    NONE = "NONE"
    OFFICIAL_API = "OFFICIAL_API"
    PUBLIC_FEED = "PUBLIC_FEED"
    LICENSED_EXPORT = "LICENSED_EXPORT"
    LOCAL_FILE = "LOCAL_FILE"


class RawStorageMode(StrEnum):
    ENCRYPTED_LOCAL = "ENCRYPTED_LOCAL"
    METADATA_ONLY = "METADATA_ONLY"
    PROHIBITED = "PROHIBITED"


class DerivedStorageMode(StrEnum):
    ALLOWED = "ALLOWED"
    AGGREGATE_ONLY = "AGGREGATE_ONLY"
    PROHIBITED = "PROHIBITED"


class CloudInferenceMode(StrEnum):
    ALLOWED = "ALLOWED"
    LOCAL_ONLY = "LOCAL_ONLY"
    PROHIBITED = "PROHIBITED"


class FineTuningMode(StrEnum):
    PROHIBITED = "PROHIBITED"
    EXPLICIT_APPROVAL_REQUIRED = "EXPLICIT_APPROVAL_REQUIRED"


class DisplayMode(StrEnum):
    REHYDRATE = "REHYDRATE"
    DERIVED_ONLY = "DERIVED_ONLY"
    FULL_WHEN_LICENSED = "FULL_WHEN_LICENSED"
    NONE = "NONE"


class RedistributionMode(StrEnum):
    IDS_ONLY = "IDS_ONLY"
    PROHIBITED = "PROHIBITED"
    LICENSED = "LICENSED"


class PiiMode(StrEnum):
    MINIMIZE_AND_PSEUDONYMIZE = "MINIMIZE_AND_PSEUDONYMIZE"
    PROHIBITED = "PROHIBITED"


class PolicyBoundary(StrEnum):
    COLLECTION = "COLLECTION"
    ARCHIVE = "ARCHIVE"
    CLOUD_INFERENCE = "CLOUD_INFERENCE"
    TRAINING = "TRAINING"
    DISPLAY = "DISPLAY"
    EXPORT = "EXPORT"
    DELETION = "DELETION"


class PolicyDecision(DomainModel):
    boundary: PolicyBoundary
    allowed: bool
    required_actions: tuple[str, ...] = ()
    reason_code: str


class SourceProcessingPolicy(DomainModel):
    source_policy_id: SourcePolicyId
    provider_id: ProviderId
    policy_status: PolicyStatus
    access_method: AccessMethod
    approved_use_case: str
    content_scope: str
    raw_storage: RawStorageMode
    derived_storage: DerivedStorageMode
    cloud_inference: CloudInferenceMode
    foundation_model_training: str = "PROHIBITED"
    fine_tuning: FineTuningMode
    display_mode: DisplayMode
    deletion_sync_required: bool
    revision_sync_required: bool
    redistribution: RedistributionMode
    retention_days: int
    pii_mode: PiiMode
    policy_checked_at: UtcDateTime
    terms_version_hash: str | None = None

    @model_validator(mode="after")
    def validate_policy(self) -> SourceProcessingPolicy:
        if self.foundation_model_training != "PROHIBITED":
            raise ValueError("foundation model training is always prohibited")
        if self.retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        if self.terms_version_hash is not None and len(self.terms_version_hash) != 64:
            raise ValueError("terms version hash must be SHA-256")
        if self.policy_status is PolicyStatus.DENIED:
            denied_shape = (
                self.access_method is AccessMethod.NONE
                and self.raw_storage is RawStorageMode.PROHIBITED
                and self.derived_storage is DerivedStorageMode.PROHIBITED
                and self.cloud_inference is CloudInferenceMode.PROHIBITED
                and self.fine_tuning is FineTuningMode.PROHIBITED
                and self.display_mode is DisplayMode.NONE
                and self.redistribution is RedistributionMode.PROHIBITED
                and self.retention_days == 0
            )
            if not denied_shape:
                raise ValueError("denied policy must deny every processing capability")
        return self

    def evaluate(self, boundary: PolicyBoundary) -> PolicyDecision:
        """Evaluate one processing boundary without implicit policy fallback."""
        if boundary is PolicyBoundary.DELETION:
            actions = ("SYNC_DELETION_AND_APPEND_TOMBSTONE",) if self.deletion_sync_required else ()
            return PolicyDecision(
                boundary=boundary,
                allowed=True,
                required_actions=actions,
                reason_code="AQ-PROVIDER-DELETION-REQUIRED",
            )
        if self.policy_status is not PolicyStatus.APPROVED:
            return self._denied(boundary, "AQ-PROVIDER-POLICY-NOT-APPROVED")
        allowed = {
            PolicyBoundary.COLLECTION: self.access_method is not AccessMethod.NONE,
            PolicyBoundary.ARCHIVE: self.raw_storage is not RawStorageMode.PROHIBITED,
            PolicyBoundary.CLOUD_INFERENCE: self.cloud_inference is CloudInferenceMode.ALLOWED,
            PolicyBoundary.TRAINING: False,
            PolicyBoundary.DISPLAY: self.display_mode is not DisplayMode.NONE,
            PolicyBoundary.EXPORT: self.redistribution is not RedistributionMode.PROHIBITED,
        }[boundary]
        if not allowed:
            return self._denied(boundary, "AQ-PROVIDER-BOUNDARY-DENIED")
        actions: tuple[str, ...] = ()
        if boundary is PolicyBoundary.ARCHIVE and self.revision_sync_required:
            actions = ("SYNC_REVISIONS",)
        return PolicyDecision(
            boundary=boundary,
            allowed=True,
            required_actions=actions,
            reason_code="AQ-PROVIDER-BOUNDARY-APPROVED",
        )

    def require(self, boundary: PolicyBoundary) -> PolicyDecision:
        decision = self.evaluate(boundary)
        if not decision.allowed:
            raise DomainError(decision.reason_code, ErrorDisposition.NO_RETRY, boundary.value)
        return decision

    @staticmethod
    def _denied(boundary: PolicyBoundary, reason_code: str) -> PolicyDecision:
        return PolicyDecision(boundary=boundary, allowed=False, reason_code=reason_code)
