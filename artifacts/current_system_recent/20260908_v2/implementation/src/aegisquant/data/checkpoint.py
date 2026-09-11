"""Atomic resumable-ingest checkpoints; checkpoints never register datasets."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, field_validator

from aegisquant.data.hashing import canonical_json_bytes, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ProviderId
from aegisquant.domain.time import UtcDateTime


class IngestCheckpoint(DomainModel):
    provider_id: ProviderId
    dataset_name: str
    cursor: str | None = None
    byte_offset: int = Field(ge=0)
    source_request_hash: str
    last_completed_content_hash: str | None = None
    updated_at: UtcDateTime

    @field_validator("source_request_hash")
    @classmethod
    def validate_request_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="source_request_hash")

    @field_validator("last_completed_content_hash")
    @classmethod
    def validate_optional_content_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name="last_completed_content_hash")


@dataclass(frozen=True, slots=True)
class CheckpointStore:
    root: Path

    def _path(self, provider_id: ProviderId, dataset_name: str) -> Path:
        if not dataset_name or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in dataset_name
        ):
            raise ValueError("invalid checkpoint dataset name")
        provider_segment = hashlib.sha256(str(provider_id).encode("utf-8")).hexdigest()
        return self.root / provider_segment / f"{dataset_name}.json"

    def save(self, checkpoint: IngestCheckpoint) -> Path:
        path = self._path(checkpoint.provider_id, checkpoint.dataset_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("wb") as output:
            output.write(canonical_json_bytes(checkpoint.model_dump(mode="json")))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        return path

    def load(self, provider_id: ProviderId, dataset_name: str) -> IngestCheckpoint | None:
        path = self._path(provider_id, dataset_name)
        if not path.is_file():
            return None
        return IngestCheckpoint.model_validate_json(path.read_bytes())
