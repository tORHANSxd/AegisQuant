"""Immutable, versioned source registry with point-in-time lookup semantics."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import cast

import yaml
from cryptography.hazmat.primitives import serialization

from aegisquant.data.hashing import canonical_json_bytes
from aegisquant.domain.errors import DomainError, ErrorDisposition
from aegisquant.domain.identifiers import SourceId
from aegisquant.domain.time import ensure_utc
from aegisquant.truth.contracts import SourceRegistryDocument, SourceRegistryEntry


def public_key_fingerprint_sha256(public_key_pem: str) -> str:
    """Hash canonical SubjectPublicKeyInfo bytes, never the PEM presentation."""

    key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    der = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("source registry root must be a mapping")
    mapping = cast(dict[object, object], raw)
    if not all(isinstance(key, str) for key in mapping):
        raise ValueError("source registry keys must be strings")
    return {cast(str, key): value for key, value in mapping.items()}


@dataclass(frozen=True, slots=True)
class SourceRegistry:
    """A validated registry snapshot; source tiers remain priors, never verdicts."""

    document: SourceRegistryDocument
    _entries: Mapping[str, tuple[SourceRegistryEntry, ...]]

    @classmethod
    def from_document(cls, document: SourceRegistryDocument) -> SourceRegistry:
        grouped: dict[str, list[SourceRegistryEntry]] = defaultdict(list)
        for entry in document.entries:
            grouped[str(entry.source_id)].append(entry)
            for public_key in entry.public_keys:
                actual = public_key_fingerprint_sha256(public_key.public_key_pem)
                if actual != public_key.fingerprint_sha256:
                    raise ValueError("AQ-TRUTH-SOURCE-REGISTRY-PUBLIC-KEY-FINGERPRINT-MISMATCH")

        ordered: dict[str, tuple[SourceRegistryEntry, ...]] = {}
        for source_id, entries in grouped.items():
            history = tuple(sorted(entries, key=lambda item: item.version))
            for index, entry in enumerate(history, start=1):
                if entry.version != index:
                    raise ValueError("AQ-TRUTH-SOURCE-REGISTRY-VERSION-GAP")
                previous = history[index - 2] if index > 1 else None
                expected_predecessor = previous.registry_entry_id if previous is not None else None
                if entry.supersedes_registry_entry_id != expected_predecessor:
                    raise ValueError("AQ-TRUTH-SOURCE-REGISTRY-PREDECESSOR-MISMATCH")
                if previous is not None and entry.available_at < previous.available_at:
                    raise ValueError("AQ-TRUTH-SOURCE-REGISTRY-TIME-REGRESSION")
            ordered[source_id] = history
        return cls(document=document, _entries=MappingProxyType(ordered))

    @classmethod
    def from_yaml(cls, path: Path) -> SourceRegistry:
        raw = _load_yaml_mapping(path)
        document = SourceRegistryDocument.model_validate_json(canonical_json_bytes(raw))
        return cls.from_document(document)

    def content_hash(self) -> str:
        return self.document.content_sha256()

    def history(self, source_id: SourceId) -> tuple[SourceRegistryEntry, ...]:
        return self._entries.get(str(source_id), ())

    def entry_as_of(self, source_id: SourceId, *, decision_time: datetime) -> SourceRegistryEntry:
        decision = ensure_utc(decision_time)
        candidates = [
            entry
            for entry in self.history(source_id)
            if entry.available_at <= decision
            and entry.valid_from <= decision
            and (entry.valid_to is None or decision < entry.valid_to)
        ]
        if not candidates:
            raise DomainError(
                "AQ-TRUTH-SOURCE-NOT-REGISTERED-AS-OF",
                ErrorDisposition.NO_RETRY,
                str(source_id),
            )
        return max(candidates, key=lambda item: (item.available_at, item.version))
