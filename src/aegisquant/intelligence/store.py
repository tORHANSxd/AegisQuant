"""Append-only content projections with revision, tombstone, and engagement PIT semantics."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aegisquant.data.archive import TombstoneRecord
from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ArtifactId, ContentId, SourceDocumentId
from aegisquant.domain.intelligence import (
    EngagementSnapshot,
    RawContentEnvelope,
    SourceIdentity,
)
from aegisquant.domain.policy import PolicyBoundary, SourceProcessingPolicy
from aegisquant.domain.time import ensure_utc


def _opaque(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IntelligenceMetadataArchive:
    """Persistent append-only identities and engagement; raw revisions use RevisionArchive."""

    root: Path

    def append_identity(self, identity: SourceIdentity) -> Path:
        directory = (
            self.root
            / "source-identities"
            / _opaque(identity.provider_id)
            / _opaque(identity.provider_native_id)
        )
        path = directory / f"{identity.version:08d}-{identity.source_identity_id}.json"
        self._write_once(path, identity)
        return path

    def append_engagement(self, snapshot: EngagementSnapshot) -> Path:
        directory = self.root / "engagement" / _opaque(snapshot.content_id)
        observed = snapshot.observed_time.strftime("%Y%m%dT%H%M%S.%fZ")
        path = directory / f"{observed}-{snapshot.engagement_snapshot_id}.json"
        self._write_once(path, snapshot)
        return path

    def engagement_history(self, content_id: ContentId) -> tuple[EngagementSnapshot, ...]:
        directory = self.root / "engagement" / _opaque(content_id)
        if not directory.is_dir():
            return ()
        return tuple(
            EngagementSnapshot.model_validate_json(path.read_bytes())
            for path in sorted(directory.glob("*.json"), key=lambda item: item.name)
        )

    def engagement_as_of(
        self, content_id: ContentId, *, decision_time: datetime
    ) -> EngagementSnapshot | None:
        decision = ensure_utc(decision_time)
        visible = [
            item
            for item in self.engagement_history(content_id)
            if item.observed_time <= decision and item.available_time <= decision
        ]
        return max(visible, key=lambda item: item.available_time) if visible else None

    @staticmethod
    def _write_once(path: Path, model: DomainModel) -> None:
        content = canonical_json_bytes(model.model_dump(mode="json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError("AQ-INTELLIGENCE-IMMUTABLE-METADATA-CONFLICT")
            return
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)


class ContentProjectionStore:
    """Deterministic replay store; raw bytes remain owned by the existing RevisionArchive."""

    def __init__(self) -> None:
        self._revisions: dict[ContentId, list[RawContentEnvelope]] = defaultdict(list)
        self._read_model: dict[ContentId, RawContentEnvelope] = {}
        self._cache: dict[ContentId, RawContentEnvelope] = {}
        self._tombstones: dict[ContentId, TombstoneRecord] = {}
        self._engagement: dict[ContentId, list[EngagementSnapshot]] = defaultdict(list)
        self._identities: dict[tuple[str, str], list[SourceIdentity]] = defaultdict(list)

    def apply_identity(self, identity: SourceIdentity) -> None:
        key = (str(identity.provider_id), str(identity.provider_native_id))
        history = self._identities[key]
        if history and identity == history[-1]:
            return
        expected_version = len(history) + 1
        if identity.version != expected_version:
            raise ValueError("AQ-INTELLIGENCE-IDENTITY-VERSION-GAP")
        if history and identity.supersedes_source_identity_id != history[-1].source_identity_id:
            raise ValueError("AQ-INTELLIGENCE-IDENTITY-PREDECESSOR-MISMATCH")
        if any(item.source_identity_id == identity.source_identity_id for item in history):
            raise ValueError("AQ-INTELLIGENCE-IDENTITY-DUPLICATE")
        if history and identity.available_time < history[-1].available_time:
            raise ValueError("AQ-INTELLIGENCE-IDENTITY-TIME-REGRESSION")
        history.append(identity)

    def apply_revision(
        self, envelope: RawContentEnvelope, *, policy: SourceProcessingPolicy
    ) -> TombstoneRecord | None:
        if (
            policy.provider_id != envelope.provider_id
            or policy.source_policy_id != envelope.source_policy_id
        ):
            raise ValueError("AQ-INTELLIGENCE-POLICY-MISMATCH")
        history = self._revisions[envelope.content_id]
        if history:
            previous = history[-1]
            if envelope.revision != previous.revision + 1:
                raise ValueError("AQ-INTELLIGENCE-REVISION-GAP")
            if envelope.available_time < previous.available_time:
                raise ValueError("AQ-INTELLIGENCE-REVISION-TIME-REGRESSION")
        elif envelope.revision != 1:
            raise ValueError("AQ-INTELLIGENCE-FIRST-REVISION-MUST-BE-ONE")
        history.append(envelope)
        if envelope.deleted_time is None:
            self._read_model[envelope.content_id] = envelope
            self._cache[envelope.content_id] = envelope
            return None
        decision = policy.require(PolicyBoundary.DELETION)
        self._read_model.pop(envelope.content_id, None)
        self._cache.pop(envelope.content_id, None)
        source_document_id = SourceDocumentId(str(envelope.content_id))
        identity = {
            "content_id": str(envelope.content_id),
            "provider_id": str(envelope.provider_id),
            "deleted_at": envelope.deleted_time.isoformat(),
            "revision": envelope.revision,
            "required_actions": decision.required_actions,
        }
        tombstone = TombstoneRecord(
            tombstone_id=ArtifactId(canonical_sha256(identity)),
            source_document_id=source_document_id,
            provider_id=envelope.provider_id,
            deleted_at=envelope.deleted_time,
            reason_code="AQ-INTELLIGENCE-SOURCE-DELETED",
            required_actions=decision.required_actions,
        )
        self._tombstones[envelope.content_id] = tombstone
        return tombstone

    def record_engagement(self, snapshot: EngagementSnapshot) -> None:
        history = self._engagement[snapshot.content_id]
        if history and snapshot.available_time <= history[-1].available_time:
            raise ValueError("AQ-INTELLIGENCE-ENGAGEMENT-TIME-NOT-INCREASING")
        history.append(snapshot)

    def current(self, content_id: ContentId) -> RawContentEnvelope | None:
        return self._read_model.get(content_id)

    def cached(self, content_id: ContentId) -> RawContentEnvelope | None:
        return self._cache.get(content_id)

    def tombstone(self, content_id: ContentId) -> TombstoneRecord | None:
        return self._tombstones.get(content_id)

    def revision_history(self, content_id: ContentId) -> tuple[RawContentEnvelope, ...]:
        return tuple(self._revisions.get(content_id, ()))

    def identity_history(
        self, *, provider_id: object, provider_native_id: object
    ) -> tuple[SourceIdentity, ...]:
        return tuple(self._identities.get((str(provider_id), str(provider_native_id)), ()))

    def identity_as_of(
        self,
        *,
        provider_id: object,
        provider_native_id: object,
        decision_time: datetime,
    ) -> SourceIdentity | None:
        decision = ensure_utc(decision_time)
        visible = [
            item
            for item in self._identities.get((str(provider_id), str(provider_native_id)), ())
            if item.first_observed_time <= decision and item.available_time <= decision
        ]
        return (
            max(visible, key=lambda item: (item.available_time, item.version)) if visible else None
        )

    def as_of(self, content_id: ContentId, *, decision_time: datetime) -> RawContentEnvelope | None:
        decision = ensure_utc(decision_time)
        candidates = [
            item
            for item in self._revisions.get(content_id, ())
            if item.available_time <= decision
            and (item.modified_time is None or item.modified_time <= decision)
        ]
        if not candidates:
            return None
        visible = max(candidates, key=lambda item: (item.available_time, item.revision))
        if visible.deleted_time is not None and visible.deleted_time <= decision:
            return None
        return visible

    def engagement_as_of(
        self, content_id: ContentId, *, decision_time: datetime
    ) -> EngagementSnapshot | None:
        decision = ensure_utc(decision_time)
        candidates = [
            item
            for item in self._engagement.get(content_id, ())
            if item.available_time <= decision and item.observed_time <= decision
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.available_time, item.observed_time))

    def feature_snapshot(
        self, content_id: ContentId, *, decision_time: datetime
    ) -> tuple[RawContentEnvelope | None, EngagementSnapshot | None]:
        return (
            self.as_of(content_id, decision_time=decision_time),
            self.engagement_as_of(content_id, decision_time=decision_time),
        )
