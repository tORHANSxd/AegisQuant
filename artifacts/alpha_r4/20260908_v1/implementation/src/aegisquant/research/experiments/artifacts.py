"""Small content-addressed artifact registry with immutable writes."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pydantic import Field, field_validator

from aegisquant.data.hashing import ensure_sha256, sha256_file
from aegisquant.domain.base import DomainModel


class ArtifactRecord(DomainModel):
    sha256: str
    size_bytes: int = Field(ge=0)
    media_type: str
    relative_path: str

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="artifact hash")


class ArtifactRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        if root.exists() and (not root.is_dir() or root.is_symlink()):
            raise ValueError("artifact registry root must be a regular directory")

    def _path(self, digest: str) -> Path:
        ensure_sha256(digest, field_name="artifact hash")
        return self.root / digest[:2] / digest

    def put_bytes(
        self, content: bytes, *, media_type: str = "application/octet-stream"
    ) -> ArtifactRecord:
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
                raise ValueError("AQ-ARTIFACT-REGISTRY-CORRUPTION")
        else:
            temporary = path.with_name(f".{path.name}.tmp")
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        return ArtifactRecord(
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
            relative_path=path.relative_to(self.root).as_posix(),
        )

    def resolve(self, digest: str) -> Path:
        path = self._path(digest)
        if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
            raise FileNotFoundError("artifact is missing or corrupt")
        return path
