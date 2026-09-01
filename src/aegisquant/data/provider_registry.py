"""Provider registry loading and fail-closed collection/archive gates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import cast

import yaml

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256
from aegisquant.data.models import (
    LicenseStatus,
    ProviderAccessState,
    ProviderRegistryDocument,
    ProviderRegistryEntry,
    ProviderStatus,
)
from aegisquant.domain.errors import DomainError, ErrorDisposition
from aegisquant.domain.identifiers import ProviderId
from aegisquant.domain.policy import PolicyBoundary, SourceProcessingPolicy


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    raw = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
    if not isinstance(raw, dict):
        raise ValueError("registry root must be a mapping")
    raw_mapping = cast(dict[object, object], raw)
    if not all(isinstance(key, str) for key in raw_mapping):
        raise ValueError("registry keys must be strings")
    return {cast(str, key): value for key, value in raw_mapping.items()}


@dataclass(frozen=True, slots=True)
class SourcePolicyRegistry:
    """Immutable lookup of machine-executable source policies."""

    schema_version: str
    _policies: Mapping[str, SourceProcessingPolicy]

    @classmethod
    def from_yaml(cls, path: Path) -> SourcePolicyRegistry:
        raw = _load_yaml_mapping(path)
        if set(raw) != {"schema_version", "policies"}:
            raise ValueError("source policy registry has unknown or missing fields")
        policies_raw = raw["policies"]
        if not isinstance(policies_raw, list):
            raise ValueError("source policy registry policies must be a list")
        policy_items = cast(list[object], policies_raw)
        policies = tuple(
            SourceProcessingPolicy.model_validate_json(canonical_json_bytes(item))
            for item in policy_items
        )
        policy_map = {str(policy.source_policy_id): policy for policy in policies}
        if len(policy_map) != len(policies):
            raise ValueError("source policy registry contains duplicate policy IDs")
        return cls(
            schema_version=str(raw["schema_version"]),
            _policies=MappingProxyType(policy_map),
        )

    def get(self, policy_id: object) -> SourceProcessingPolicy:
        policy = self._policies.get(str(policy_id))
        if policy is None:
            raise DomainError(
                "AQ-PROVIDER-POLICY-NOT-REGISTERED",
                ErrorDisposition.NO_RETRY,
                str(policy_id),
            )
        return policy


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    """Immutable provider lookup with explicit policy enforcement."""

    document: ProviderRegistryDocument
    _entries: Mapping[str, ProviderRegistryEntry]

    @classmethod
    def from_document(cls, document: ProviderRegistryDocument) -> ProviderRegistry:
        entries = MappingProxyType({str(entry.provider_id): entry for entry in document.providers})
        return cls(document=document, _entries=entries)

    @classmethod
    def from_yaml(cls, path: Path) -> ProviderRegistry:
        raw = _load_yaml_mapping(path)
        document = ProviderRegistryDocument.model_validate_json(canonical_json_bytes(raw))
        return cls.from_document(document)

    def content_hash(self) -> str:
        return canonical_sha256(self.document.model_dump(mode="json"))

    def get(self, provider_id: ProviderId) -> ProviderRegistryEntry:
        entry = self._entries.get(str(provider_id))
        if entry is None:
            raise DomainError(
                "AQ-PROVIDER-NOT-REGISTERED",
                ErrorDisposition.NO_RETRY,
                str(provider_id),
            )
        return entry

    def require(
        self, provider_id: ProviderId, policy: SourceProcessingPolicy, boundary: PolicyBoundary
    ) -> ProviderRegistryEntry:
        """Require registry approval, approved licensing, matching policy, and boundary access."""
        entry = self.get(provider_id)
        if entry.access_state is not ProviderAccessState.READY:
            raise DomainError(
                f"AQ-PROVIDER-ACCESS-{entry.access_state.value.upper()}",
                ErrorDisposition.NO_RETRY,
                str(provider_id),
            )
        if entry.status is not ProviderStatus.APPROVED:
            raise DomainError(
                "AQ-PROVIDER-STATUS-NOT-APPROVED",
                ErrorDisposition.NO_RETRY,
                entry.status.value,
            )
        if entry.license_status is not LicenseStatus.APPROVED:
            raise DomainError(
                "AQ-PROVIDER-LICENSE-NOT-APPROVED",
                ErrorDisposition.NO_RETRY,
                entry.license_status.value,
            )
        if (
            policy.provider_id != entry.provider_id
            or policy.source_policy_id != entry.source_policy_id
        ):
            raise DomainError(
                "AQ-PROVIDER-POLICY-MISMATCH",
                ErrorDisposition.NO_RETRY,
                str(provider_id),
            )
        policy.require(boundary)
        return entry

    def require_collection(
        self, provider_id: ProviderId, policy: SourceProcessingPolicy
    ) -> ProviderRegistryEntry:
        return self.require(provider_id, policy, PolicyBoundary.COLLECTION)

    def require_archive(
        self, provider_id: ProviderId, policy: SourceProcessingPolicy
    ) -> ProviderRegistryEntry:
        return self.require(provider_id, policy, PolicyBoundary.ARCHIVE)
