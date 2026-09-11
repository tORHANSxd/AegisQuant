"""V5 source authenticity, provenance, integrity, and compromise contracts."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal, Self, cast
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    ArtifactId,
    ContentId,
    SourceDocumentId,
    SourceId,
    SourceIdentityId,
)
from aegisquant.domain.serialization import canonical_content_hash
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import UnitInterval

_DOMAIN_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)


def _require_sha256(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")


def _require_nonblank_unique(values: tuple[str, ...], *, field_name: str) -> None:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} cannot contain blank values")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")


def _require_https_url(value: str, *, field_name: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"{field_name} must be a credential-free HTTPS URL")


def _serialized_registry_entry_sort_key(value: JsonValue) -> tuple[str, int]:
    if not isinstance(value, dict):
        raise TypeError("registry entry must serialize as an object")
    source_id = value.get("source_id")
    version = value.get("version")
    if not isinstance(source_id, str) or not isinstance(version, int):
        raise TypeError("serialized registry entry identity is invalid")
    return source_id, version


class SourceType(StrEnum):
    REGULATOR = "REGULATOR"
    COURT = "COURT"
    CENTRAL_BANK = "CENTRAL_BANK"
    EXCHANGE = "EXCHANGE"
    PROJECT_OFFICIAL = "PROJECT_OFFICIAL"
    WIRE_SERVICE = "WIRE_SERVICE"
    NEWS_OUTLET = "NEWS_OUTLET"
    SOCIAL_ACCOUNT = "SOCIAL_ACCOUNT"
    INDIVIDUAL = "INDIVIDUAL"
    ANONYMOUS = "ANONYMOUS"


class SourceTier(StrEnum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class PublicKeyAlgorithm(StrEnum):
    ED25519 = "ED25519"


class IdentityFactor(StrEnum):
    DOMAIN = "DOMAIN"
    SOCIAL_ACCOUNT = "SOCIAL_ACCOUNT"
    API_ENDPOINT = "API_ENDPOINT"
    DETACHED_SIGNATURE = "DETACHED_SIGNATURE"


class OfficialIdentityState(StrEnum):
    AUTHENTIC = "AUTHENTIC"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DetachedSignatureState(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    KEY_NOT_FOUND = "KEY_NOT_FOUND"
    KEY_NOT_ACTIVE = "KEY_NOT_ACTIVE"
    UNSUPPORTED_ALGORITHM = "UNSUPPORTED_ALGORITHM"
    ERROR = "ERROR"


class C2paValidationState(StrEnum):
    ABSENT = "ABSENT"
    INVALID = "INVALID"
    VALID = "VALID"
    TRUSTED = "TRUSTED"
    UNSUPPORTED = "UNSUPPORTED"
    SDK_UNAVAILABLE = "SDK_UNAVAILABLE"
    ERROR = "ERROR"


class C2paSpecCompatibility(StrEnum):
    PREFERRED_2_3 = "PREFERRED_2_3"
    COMPATIBLE_2_X = "COMPATIBLE_2_X"
    LEGACY = "LEGACY"
    FUTURE_UNSUPPORTED = "FUTURE_UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class CertificateState(StrEnum):
    TRUSTED = "TRUSTED"
    VALID_UNTRUSTED = "VALID_UNTRUSTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"
    NOT_PRESENT = "NOT_PRESENT"


class ContentIntegrityState(StrEnum):
    VERIFIED_TRUSTED = "VERIFIED_TRUSTED"
    VERIFIED_UNTRUSTED = "VERIFIED_UNTRUSTED"
    INVALID = "INVALID"
    NO_CREDENTIALS = "NO_CREDENTIALS"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


class SourceCompromiseStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    NORMAL = "NORMAL"
    SUSPECTED = "SUSPECTED"
    COMPROMISED = "COMPROMISED"
    RECOVERED = "RECOVERED"


class OfficialSocialAccount(DomainModel):
    platform: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    canonical_url: str

    @model_validator(mode="after")
    def validate_account(self) -> Self:
        _require_https_url(self.canonical_url, field_name="canonical_url")
        return self


class OfficialPublicKey(DomainModel):
    key_id: str = Field(min_length=1)
    algorithm: PublicKeyAlgorithm
    public_key_pem: str = Field(min_length=1)
    fingerprint_sha256: str
    valid_from: UtcDateTime
    valid_to: UtcDateTime | None = None
    revoked_at: UtcDateTime | None = None
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_key(self) -> Self:
        _require_sha256(self.fingerprint_sha256, field_name="fingerprint_sha256")
        if "-----BEGIN PUBLIC KEY-----" not in self.public_key_pem:
            raise ValueError("public_key_pem must contain a SubjectPublicKeyInfo PEM key")
        if self.valid_from > self.available_at:
            raise ValueError("key cannot be available before valid_from")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("key valid_to must be after valid_from")
        if self.revoked_at is not None and self.revoked_at < self.valid_from:
            raise ValueError("key revoked_at cannot precede valid_from")
        return self


class SourceRegistryEntry(DomainModel):
    registry_entry_id: ArtifactId
    source_id: SourceId
    version: int = Field(ge=1)
    supersedes_registry_entry_id: ArtifactId | None = None
    canonical_name: str = Field(min_length=1)
    source_type: SourceType
    source_tier: SourceTier
    official_domains: tuple[str, ...] = ()
    official_social_accounts: tuple[OfficialSocialAccount, ...] = ()
    public_keys: tuple[OfficialPublicKey, ...] = ()
    known_api_endpoints: tuple[str, ...] = ()
    jurisdiction: str = Field(min_length=1)
    topic_domains: tuple[str, ...] = Field(min_length=1)
    license_policy: str = Field(min_length=1)
    historical_accuracy: UnitInterval | None = None
    historical_correction_rate: UnitInterval | None = None
    historical_retraction_rate: UnitInterval | None = None
    first_report_latency_seconds: int | None = Field(default=None, ge=0)
    compromise_incident_ids: tuple[ArtifactId, ...] = ()
    evidence_references: tuple[str, ...] = Field(min_length=1)
    valid_from: UtcDateTime
    valid_to: UtcDateTime | None = None
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_entry(self) -> Self:
        if self.version == 1 and self.supersedes_registry_entry_id is not None:
            raise ValueError("first source-registry version cannot supersede another entry")
        if self.version > 1 and self.supersedes_registry_entry_id is None:
            raise ValueError("later source-registry versions require a predecessor")
        if self.valid_from > self.available_at:
            raise ValueError("registry entry cannot be available before valid_from")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("registry valid_to must be after valid_from")
        for domain in self.official_domains:
            if domain != domain.lower() or _DOMAIN_RE.fullmatch(domain) is None:
                raise ValueError("official_domains must be canonical lowercase ASCII domains")
        for endpoint in self.known_api_endpoints:
            _require_https_url(endpoint, field_name="known_api_endpoints")
        for reference in self.evidence_references:
            _require_https_url(reference, field_name="evidence_references")
        _require_nonblank_unique(self.official_domains, field_name="official_domains")
        _require_nonblank_unique(self.known_api_endpoints, field_name="known_api_endpoints")
        _require_nonblank_unique(self.topic_domains, field_name="topic_domains")
        if len(self.official_social_accounts) != len(
            {(item.platform.casefold(), item.account_id) for item in self.official_social_accounts}
        ):
            raise ValueError("official_social_accounts must be unique")
        if len(self.public_keys) != len({item.key_id for item in self.public_keys}):
            raise ValueError("public key IDs must be unique")
        if self.source_tier is SourceTier.S and not any(
            (
                self.official_domains,
                self.official_social_accounts,
                self.public_keys,
                self.known_api_endpoints,
            )
        ):
            raise ValueError("tier S sources require at least one official identity signal")
        return self


class SourceRegistryDocument(DomainModel):
    schema_version: Literal["1.0.0"]
    registry_version: int = Field(ge=1)
    published_at: UtcDateTime
    available_at: UtcDateTime
    entries: tuple[SourceRegistryEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        if self.published_at > self.available_at:
            raise ValueError("source registry cannot be available before publication")
        if any(entry.available_at > self.available_at for entry in self.entries):
            raise ValueError("registry entry cannot postdate the containing registry")
        entry_ids = [str(entry.registry_entry_id) for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("source registry contains duplicate entry IDs")
        source_versions = [(str(entry.source_id), entry.version) for entry in self.entries]
        if len(source_versions) != len(set(source_versions)):
            raise ValueError("source registry contains duplicate source versions")
        return self

    def content_sha256(self) -> str:
        payload = cast(dict[str, JsonValue], self.model_dump(mode="json"))
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries must serialize as a list")
        payload["entries"] = sorted(
            entries,
            key=_serialized_registry_entry_sort_key,
        )
        return canonical_content_hash(payload)


class DetachedSignatureVerification(DomainModel):
    verification_id: ArtifactId
    source_id: SourceId
    source_identity_id: SourceIdentityId
    key_id: str = Field(min_length=1)
    key_fingerprint_sha256: str | None = None
    payload_sha256: str
    signature_sha256: str
    state: DetachedSignatureState
    reason_codes: tuple[str, ...] = Field(min_length=1)
    observed_at: UtcDateTime
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_verification(self) -> Self:
        for field_name, value in (
            ("payload_sha256", self.payload_sha256),
            ("signature_sha256", self.signature_sha256),
        ):
            _require_sha256(value, field_name=field_name)
        if self.key_fingerprint_sha256 is not None:
            _require_sha256(
                self.key_fingerprint_sha256,
                field_name="key_fingerprint_sha256",
            )
        if self.state is DetachedSignatureState.VALID and self.key_fingerprint_sha256 is None:
            raise ValueError("valid signature verification requires a key fingerprint")
        if self.observed_at > self.available_at:
            raise ValueError("signature verification cannot predate observation")
        _require_nonblank_unique(self.reason_codes, field_name="reason_codes")
        return self


class OfficialIdentityObservation(DomainModel):
    source_id: SourceId
    source_identity_id: SourceIdentityId
    observed_url: str | None = None
    social_platform: str | None = None
    social_account_id: str | None = None
    api_endpoint: str | None = None
    detached_signature_verification_id: ArtifactId | None = None
    observed_at: UtcDateTime
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.observed_at > self.available_at:
            raise ValueError("identity observation cannot be available before observation")
        if (self.social_platform is None) != (self.social_account_id is None):
            raise ValueError("social platform and account ID must be supplied together")
        if self.observed_url is not None:
            _require_https_url(self.observed_url, field_name="observed_url")
        if self.api_endpoint is not None:
            _require_https_url(self.api_endpoint, field_name="api_endpoint")
        if not any(
            (
                self.observed_url,
                self.social_account_id,
                self.api_endpoint,
                self.detached_signature_verification_id,
            )
        ):
            raise ValueError("official identity observation requires evidence")
        return self


class OfficialIdentityAssessment(DomainModel):
    assessment_id: ArtifactId
    source_id: SourceId
    source_identity_id: SourceIdentityId
    registry_entry_id: ArtifactId
    state: OfficialIdentityState
    matched_factors: tuple[IdentityFactor, ...] = ()
    mismatched_factors: tuple[IdentityFactor, ...] = ()
    reason_codes: tuple[str, ...] = Field(min_length=1)
    observed_at: UtcDateTime
    available_at: UtcDateTime
    tier_is_prior_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_assessment(self) -> Self:
        if self.observed_at > self.available_at:
            raise ValueError("identity assessment cannot be available before observation")
        if set(self.matched_factors) & set(self.mismatched_factors):
            raise ValueError("identity factors cannot both match and mismatch")
        if len(self.matched_factors) != len(set(self.matched_factors)):
            raise ValueError("matched identity factors must be unique")
        if len(self.mismatched_factors) != len(set(self.mismatched_factors)):
            raise ValueError("mismatched identity factors must be unique")
        _require_nonblank_unique(self.reason_codes, field_name="reason_codes")
        if self.state is OfficialIdentityState.AUTHENTIC:
            if self.mismatched_factors:
                raise ValueError("authentic identity cannot contain mismatches")
            if not set(self.matched_factors) & {
                IdentityFactor.SOCIAL_ACCOUNT,
                IdentityFactor.API_ENDPOINT,
                IdentityFactor.DETACHED_SIGNATURE,
            }:
                raise ValueError("domain-only evidence cannot authenticate an official source")
        elif self.state is OfficialIdentityState.REJECTED and not self.mismatched_factors:
            raise ValueError("rejected identity requires a mismatched factor")
        elif self.state is OfficialIdentityState.INSUFFICIENT_EVIDENCE and self.mismatched_factors:
            raise ValueError("mismatches must be rejected rather than called insufficient")
        return self


class C2paVerificationResult(DomainModel):
    verification_id: ArtifactId
    asset_sha256: str
    media_type: str = Field(min_length=1)
    sdk_name: Literal["c2pa-python"] = "c2pa-python"
    package_version: str | None = None
    sdk_version: str | None = None
    specification_version: str | None = None
    spec_compatibility: C2paSpecCompatibility
    validation_state: C2paValidationState
    manifest_present: bool | None
    signature_valid: bool | None
    trust_list_valid: bool | None
    timestamp_valid: bool | None
    ingredient_chain_valid: bool | None
    content_binding_valid: bool | None
    generator_information: tuple[str, ...] = ()
    ai_assertions: tuple[str, ...] = ()
    certificate_state: CertificateState
    tamper_detected: bool | None
    validation_codes: tuple[str, ...] = ()
    manifest_store_sha256: str | None = None
    verified_at: UtcDateTime
    available_at: UtcDateTime
    claim_truth_implied: Literal[False] = False
    remote_manifest_fetch_enabled: Literal[False] = False
    ocsp_fetch_enabled: Literal[False] = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        _require_sha256(self.asset_sha256, field_name="asset_sha256")
        if self.manifest_store_sha256 is not None:
            _require_sha256(self.manifest_store_sha256, field_name="manifest_store_sha256")
        if self.verified_at > self.available_at:
            raise ValueError("C2PA result cannot be available before verification")
        _require_nonblank_unique(self.validation_codes, field_name="validation_codes")
        if self.validation_state is C2paValidationState.ABSENT:
            if self.manifest_present is not False or self.manifest_store_sha256 is not None:
                raise ValueError("absent C2PA must not claim a manifest")
            if any(
                value is not None
                for value in (
                    self.signature_valid,
                    self.trust_list_valid,
                    self.timestamp_valid,
                    self.ingredient_chain_valid,
                    self.content_binding_valid,
                    self.tamper_detected,
                )
            ):
                raise ValueError("absent C2PA has unknown validation signals")
        if self.validation_state in {
            C2paValidationState.VALID,
            C2paValidationState.TRUSTED,
        } and (
            self.manifest_present is not True
            or self.signature_valid is not True
            or self.content_binding_valid is not True
            or self.tamper_detected is not False
        ):
            raise ValueError("valid C2PA requires signature and content binding")
        if self.validation_state is C2paValidationState.TRUSTED and (
            self.trust_list_valid is not True
            or self.certificate_state is not CertificateState.TRUSTED
        ):
            raise ValueError("trusted C2PA requires trusted signing credentials")
        return self


class ContentIntegrityAssessment(DomainModel):
    assessment_id: ArtifactId
    asset_sha256: str
    c2pa_verification_id: ArtifactId
    state: ContentIntegrityState
    credentials_present: bool | None
    tamper_detected: bool | None
    reason_codes: tuple[str, ...] = Field(min_length=1)
    assessed_at: UtcDateTime
    available_at: UtcDateTime
    implies_claim_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_assessment(self) -> Self:
        _require_sha256(self.asset_sha256, field_name="asset_sha256")
        if self.assessed_at > self.available_at:
            raise ValueError("integrity assessment cannot be available before assessment")
        _require_nonblank_unique(self.reason_codes, field_name="reason_codes")
        if self.state is ContentIntegrityState.NO_CREDENTIALS and (
            self.credentials_present is not False or self.tamper_detected is not None
        ):
            raise ValueError("no credentials is unknown integrity, not invalid content")
        if self.state in {
            ContentIntegrityState.VERIFIED_TRUSTED,
            ContentIntegrityState.VERIFIED_UNTRUSTED,
        } and (self.credentials_present is not True or self.tamper_detected is not False):
            raise ValueError("verified integrity requires present credentials and no tamper")
        return self


class ContentAuthenticityBinding(DomainModel):
    binding_id: ArtifactId
    content_id: ContentId
    source_identity_id: SourceIdentityId
    source_identity_assessment_id: ArtifactId
    content_integrity_assessment_id: ArtifactId
    source_compromise_event_id: ArtifactId | None = None
    asset_sha256: str
    identity_state: OfficialIdentityState
    integrity_state: ContentIntegrityState
    source_compromise_status: SourceCompromiseStatus | None = None
    reason_codes: tuple[str, ...] = Field(min_length=1)
    available_at: UtcDateTime
    claim_truth_implied: Literal[False] = False

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        _require_sha256(self.asset_sha256, field_name="asset_sha256")
        _require_nonblank_unique(self.reason_codes, field_name="reason_codes")
        if (self.source_compromise_event_id is None) != (self.source_compromise_status is None):
            raise ValueError("compromise event ID and status must be present together")
        return self


class SourceCompromiseEvent(DomainModel):
    event_id: ArtifactId
    source_id: SourceId
    version: int = Field(ge=1)
    previous_event_id: ArtifactId | None = None
    status: SourceCompromiseStatus
    reason_codes: tuple[str, ...] = Field(min_length=1)
    evidence_document_ids: tuple[SourceDocumentId, ...] = ()
    effective_at: UtcDateTime
    observed_at: UtcDateTime
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if not self.effective_at <= self.observed_at <= self.available_at:
            raise ValueError("compromise effective/observed/available times must be monotonic")
        if self.version == 1 and self.previous_event_id is not None:
            raise ValueError("first compromise event cannot have a predecessor")
        if self.version > 1 and self.previous_event_id is None:
            raise ValueError("later compromise events require a predecessor")
        _require_nonblank_unique(self.reason_codes, field_name="reason_codes")
        if len(self.evidence_document_ids) != len(set(self.evidence_document_ids)):
            raise ValueError("compromise evidence documents must be unique")
        return self
