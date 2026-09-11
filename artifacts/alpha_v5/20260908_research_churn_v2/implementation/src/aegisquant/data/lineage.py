"""Deterministic transformation-lineage records."""

from __future__ import annotations

from pydantic import field_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel


class TransformationLineage(DomainModel):
    transform_name: str
    transform_version: str
    input_manifest_hashes: tuple[str, ...]
    code_commit: str
    config_hash: str
    source_request_hash: str

    @field_validator("input_manifest_hashes")
    @classmethod
    def validate_input_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("lineage requires at least one input manifest")
        return tuple(ensure_sha256(value, field_name="input_manifest_hash") for value in values)

    @field_validator("config_hash", "source_request_hash")
    @classmethod
    def validate_hash(cls, value: str, info: object) -> str:
        return ensure_sha256(value, field_name=str(getattr(info, "field_name", "hash")))

    @field_validator("code_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("code_commit must be a full lowercase Git SHA")
        return value

    def content_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))
