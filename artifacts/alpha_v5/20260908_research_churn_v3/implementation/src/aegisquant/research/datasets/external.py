"""Content-addressed immutable registration for user-provided external baselines."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Literal

from pydantic import field_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256, sha256_file
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime


class ExternalBaselineManifest(DomainModel):
    baseline_id: str
    source_sha256: str
    data_scope: str
    cost_scope: str
    rights_status: Literal["personal_research_only", "public_license"]
    imported_at: UtcDateTime
    immutable: Literal[True] = True

    @field_validator("source_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="external baseline hash")


class ExternalBaselineRecord(DomainModel):
    record_id: str
    manifest: ExternalBaselineManifest
    stored_path: str


def register_external_baseline(
    *,
    source: Path,
    manifest: ExternalBaselineManifest,
    registry_directory: Path,
) -> ExternalBaselineRecord:
    if not source.is_file() or source.is_symlink():
        raise ValueError("external baseline must be a regular non-symlink file")
    actual_hash = sha256_file(source)
    if actual_hash != manifest.source_sha256:
        raise ValueError("AQ-EXTERNAL-BASELINE-HASH-MISMATCH")
    registry_directory.mkdir(parents=True, exist_ok=True)
    destination = registry_directory / f"{actual_hash}{source.suffix.lower()}"
    if destination.exists():
        if not destination.is_file() or destination.is_symlink():
            raise ValueError("external baseline registry contains unsafe path")
        if sha256_file(destination) != actual_hash:
            raise ValueError("external baseline registry content conflict")
    else:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
        try:
            with source.open("rb") as input_stream, os.fdopen(descriptor, "wb") as output_stream:
                while block := input_stream.read(1024 * 1024):
                    output_stream.write(block)
        except BaseException:
            if destination.exists():
                destination.unlink()
            raise
        destination.chmod(stat.S_IREAD)
    record_payload = {
        "manifest": manifest.model_dump(mode="json"),
        "stored_path": destination.name,
    }
    return ExternalBaselineRecord(
        record_id=canonical_sha256(record_payload),
        manifest=manifest,
        stored_path=destination.name,
    )
