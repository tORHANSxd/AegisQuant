"""Immutable content revisions, AES-GCM restricted storage, and tombstones."""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import Field, field_validator

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, ensure_sha256
from aegisquant.data.provider_registry import ProviderRegistry
from aegisquant.domain.base import DomainModel
from aegisquant.domain.errors import DomainError, ErrorDisposition
from aegisquant.domain.identifiers import (
    ArtifactId,
    ProviderId,
    ProviderNativeId,
    SourceDocumentId,
)
from aegisquant.domain.policy import PolicyBoundary, RawStorageMode, SourceProcessingPolicy
from aegisquant.domain.time import UtcDateTime, ensure_utc


class EncryptedContent(DomainModel):
    algorithm: str = "AES-256-GCM"
    key_id: str
    nonce_b64: str
    ciphertext_b64: str
    aad_sha256: str

    @field_validator("aad_sha256")
    @classmethod
    def validate_aad_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="aad_sha256")


class RevisionRecord(DomainModel):
    record_id: ArtifactId
    source_document_id: SourceDocumentId
    provider_id: ProviderId
    provider_native_id: ProviderNativeId
    revision: int = Field(ge=1)
    content_sha256: str
    storage_mode: RawStorageMode
    payload_path: str | None
    parent_record_id: ArtifactId | None = None
    available_time: UtcDateTime
    ingest_time: UtcDateTime

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="content_sha256")


class TombstoneRecord(DomainModel):
    tombstone_id: ArtifactId
    source_document_id: SourceDocumentId
    provider_id: ProviderId
    deleted_at: UtcDateTime
    reason_code: str
    supersedes_record_id: ArtifactId | None = None
    required_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RestrictedContentCipher:
    """AES-GCM cipher whose key exists only in the caller-owned object."""

    key_id: str
    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) != 32:
            raise ValueError("AES-256-GCM requires exactly 32 key bytes")
        if not self.key_id or len(self.key_id) > 128:
            raise ValueError("key_id is required and must be at most 128 characters")

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> EncryptedContent:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext, aad)
        return EncryptedContent(
            key_id=self.key_id,
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
            ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
            aad_sha256=hashlib.sha256(aad).hexdigest(),
        )

    def decrypt(self, encrypted: EncryptedContent, *, aad: bytes) -> bytes:
        if encrypted.key_id != self.key_id:
            raise ValueError("encryption key ID does not match")
        if hashlib.sha256(aad).hexdigest() != encrypted.aad_sha256:
            raise ValueError("authenticated data hash does not match")
        nonce = base64.b64decode(encrypted.nonce_b64, validate=True)
        ciphertext = base64.b64decode(encrypted.ciphertext_b64, validate=True)
        return AESGCM(self.key).decrypt(nonce, ciphertext, aad)


def _opaque_segment(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RevisionArchive:
    root: Path
    provider_registry: ProviderRegistry

    def _document_root(self, provider_id: ProviderId, source_document_id: SourceDocumentId) -> Path:
        return (
            self.root
            / "revisions"
            / _opaque_segment(provider_id)
            / _opaque_segment(source_document_id)
        )

    @staticmethod
    def _aad(
        *,
        provider_id: ProviderId,
        source_document_id: SourceDocumentId,
        provider_native_id: ProviderNativeId,
        revision: int,
        content_sha256: str,
    ) -> bytes:
        return canonical_json_bytes(
            {
                "provider_id": str(provider_id),
                "source_document_id": str(source_document_id),
                "provider_native_id": str(provider_native_id),
                "revision": revision,
                "content_sha256": content_sha256,
            }
        )

    def archive_revision(
        self,
        *,
        policy: SourceProcessingPolicy,
        source_document_id: SourceDocumentId,
        provider_native_id: ProviderNativeId,
        revision: int,
        content: bytes,
        available_time: datetime,
        ingest_time: datetime,
        cipher: RestrictedContentCipher | None = None,
        parent_record_id: ArtifactId | None = None,
    ) -> RevisionRecord:
        """Append one immutable revision without ever persisting a plaintext key."""
        provider_id = policy.provider_id
        self.provider_registry.require_archive(provider_id, policy)
        if revision < 1:
            raise ValueError("revision must be positive")
        available = ensure_utc(available_time)
        ingested = ensure_utc(ingest_time)
        if available > ingested:
            raise ValueError("available_time cannot exceed ingest_time")
        content_hash = hashlib.sha256(content).hexdigest()
        if policy.raw_storage is RawStorageMode.PROHIBITED:
            raise DomainError(
                "AQ-PROVIDER-BOUNDARY-DENIED",
                ErrorDisposition.NO_RETRY,
                PolicyBoundary.ARCHIVE.value,
            )
        if policy.raw_storage is RawStorageMode.ENCRYPTED_LOCAL and cipher is None:
            raise DomainError(
                "AQ-SECURITY-ENCRYPTION-KEY-REQUIRED",
                ErrorDisposition.NO_RETRY,
                str(source_document_id),
            )
        identity = {
            "source_document_id": str(source_document_id),
            "provider_id": str(provider_id),
            "provider_native_id": str(provider_native_id),
            "revision": revision,
            "content_sha256": content_hash,
            "storage_mode": policy.raw_storage.value,
            "parent_record_id": str(parent_record_id) if parent_record_id else None,
            "available_time": available.isoformat().replace("+00:00", "Z"),
            "ingest_time": ingested.isoformat().replace("+00:00", "Z"),
        }
        record_id = ArtifactId(canonical_sha256(identity))
        document_root = self._document_root(provider_id, source_document_id)
        final_directory = document_root / f"{revision:08d}-{record_id}"
        payload_path = (
            "content.enc.json" if policy.raw_storage is RawStorageMode.ENCRYPTED_LOCAL else None
        )
        record = RevisionRecord(
            record_id=record_id,
            source_document_id=source_document_id,
            provider_id=provider_id,
            provider_native_id=provider_native_id,
            revision=revision,
            content_sha256=content_hash,
            storage_mode=policy.raw_storage,
            payload_path=payload_path,
            parent_record_id=parent_record_id,
            available_time=available,
            ingest_time=ingested,
        )
        if final_directory.exists():
            existing = RevisionRecord.model_validate_json(
                (final_directory / "record.json").read_bytes()
            )
            if existing != record:
                raise ValueError("AQ-DATA-REVISION-CONFLICT: immutable revision differs")
            return existing
        document_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="revision-", dir=document_root))
        try:
            if payload_path is not None:
                if cipher is None:
                    raise RuntimeError("encrypted archive reached storage without a cipher")
                aad = self._aad(
                    provider_id=provider_id,
                    source_document_id=source_document_id,
                    provider_native_id=provider_native_id,
                    revision=revision,
                    content_sha256=content_hash,
                )
                encrypted = cipher.encrypt(content, aad=aad)
                (staging / payload_path).write_bytes(
                    canonical_json_bytes(encrypted.model_dump(mode="json"))
                )
            (staging / "record.json").write_bytes(
                canonical_json_bytes(record.model_dump(mode="json"))
            )
            os.replace(staging, final_directory)
            return record
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def append_tombstone(
        self,
        *,
        policy: SourceProcessingPolicy,
        source_document_id: SourceDocumentId,
        deleted_at: datetime,
        reason_code: str,
        supersedes_record_id: ArtifactId | None = None,
    ) -> TombstoneRecord:
        decision = policy.require(PolicyBoundary.DELETION)
        deleted = ensure_utc(deleted_at)
        identity = {
            "source_document_id": str(source_document_id),
            "provider_id": str(policy.provider_id),
            "deleted_at": deleted.isoformat().replace("+00:00", "Z"),
            "reason_code": reason_code,
            "supersedes_record_id": (str(supersedes_record_id) if supersedes_record_id else None),
            "required_actions": list(decision.required_actions),
        }
        record = TombstoneRecord(
            tombstone_id=ArtifactId(canonical_sha256(identity)),
            source_document_id=source_document_id,
            provider_id=policy.provider_id,
            deleted_at=deleted,
            reason_code=reason_code,
            supersedes_record_id=supersedes_record_id,
            required_actions=decision.required_actions,
        )
        directory = (
            self.root
            / "tombstones"
            / _opaque_segment(policy.provider_id)
            / _opaque_segment(source_document_id)
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{record.tombstone_id}.json"
        if path.exists():
            existing = TombstoneRecord.model_validate_json(path.read_bytes())
            if existing != record:
                raise ValueError("AQ-DATA-TOMBSTONE-CONFLICT: tombstone differs")
            return existing
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(canonical_json_bytes(record.model_dump(mode="json")))
        os.replace(temporary, path)
        return record

    def rehydrate(
        self,
        *,
        record: RevisionRecord,
        cipher: RestrictedContentCipher,
    ) -> bytes | None:
        tombstones = (
            self.root
            / "tombstones"
            / _opaque_segment(record.provider_id)
            / _opaque_segment(record.source_document_id)
        )
        if tombstones.is_dir() and any(tombstones.glob("*.json")):
            raise DomainError(
                "AQ-DATA-CONTENT-DELETED",
                ErrorDisposition.NO_RETRY,
                str(record.source_document_id),
            )
        if record.storage_mode is RawStorageMode.METADATA_ONLY:
            return None
        document_root = self._document_root(record.provider_id, record.source_document_id)
        directory = document_root / f"{record.revision:08d}-{record.record_id}"
        if record.payload_path is None:
            raise ValueError("encrypted revision is missing its payload path")
        encrypted = EncryptedContent.model_validate_json(
            (directory / record.payload_path).read_bytes()
        )
        aad = self._aad(
            provider_id=record.provider_id,
            source_document_id=record.source_document_id,
            provider_native_id=record.provider_native_id,
            revision=record.revision,
            content_sha256=record.content_sha256,
        )
        plaintext = cipher.decrypt(encrypted, aad=aad)
        if hashlib.sha256(plaintext).hexdigest() != record.content_sha256:
            raise ValueError("AQ-DATA-CONTENT-HASH-MISMATCH: decrypted content differs")
        return plaintext
