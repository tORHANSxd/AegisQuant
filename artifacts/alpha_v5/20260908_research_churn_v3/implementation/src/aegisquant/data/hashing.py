"""Streaming and canonical hashes used by the immutable data foundation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Final

HASH_BUFFER_BYTES: Final = 1024 * 1024
PATH_SEGMENT_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic UTF-8 JSON without non-standard numbers."""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    """Hash one JSON-compatible value deterministically."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path, *, buffer_size: int = HASH_BUFFER_BYTES) -> str:
    """Hash a regular file with bounded memory and no mutation."""
    if buffer_size < 4096:
        raise ValueError("hash buffer must be at least 4096 bytes")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"AQ-DATA-SCAN-UNSAFE: regular non-symlink file required: {path}")
    digest = hashlib.sha256()
    buffer = bytearray(buffer_size)
    view = memoryview(buffer)
    with path.open("rb", buffering=0) as source:
        while count := source.readinto(buffer):
            digest.update(view[:count])
    return digest.hexdigest()


def ensure_sha256(value: str, *, field_name: str) -> str:
    """Validate a lowercase SHA-256 string."""
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def safe_relative_path(value: str) -> str:
    """Normalize and validate a portable relative artifact path."""
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError("artifact path must be relative and cannot traverse parents")
    normalized = candidate.as_posix()
    if normalized in {".", ""}:
        raise ValueError("artifact path cannot be empty")
    return normalized


def safe_path_segment(value: str, *, field_name: str) -> str:
    """Require one filesystem-safe, non-traversing path segment."""
    if PATH_SEGMENT_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} is not a safe path segment")
    return value
