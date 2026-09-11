"""Append-only dataset catalog that verifies manifests before registration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, field_validator

from aegisquant.data.hashing import canonical_json_bytes, ensure_sha256, sha256_file
from aegisquant.data.models import DatasetManifest, LakeLayer
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import DatasetId, ProviderId


class CatalogEntry(DomainModel):
    dataset_id: DatasetId
    manifest_hash: str
    manifest_path: str
    dataset_name: str
    provider_id: ProviderId
    layer: LakeLayer
    schema_version: str
    row_count: int = Field(ge=0)

    @field_validator("manifest_hash")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="manifest_hash")


@dataclass(frozen=True, slots=True)
class DataCatalog:
    lake_root: Path
    index_path: Path

    def _entries(self) -> list[CatalogEntry]:
        if not self.index_path.is_file():
            return []
        entries: list[CatalogEntry] = []
        with self.index_path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if line.strip():
                    try:
                        entries.append(CatalogEntry.model_validate_json(line))
                    except ValueError as error:
                        raise ValueError(f"AQ-DATA-CATALOG-INVALID: line {line_number}") from error
        return entries

    def verify_manifest(self, manifest_path: Path) -> DatasetManifest:
        root = self.lake_root.resolve(strict=True)
        resolved_manifest = manifest_path.resolve(strict=True)
        try:
            resolved_manifest.relative_to(root)
        except ValueError as error:
            raise ValueError("AQ-DATA-CATALOG-PATH-ESCAPE: manifest outside lake") from error
        manifest = DatasetManifest.model_validate_json(resolved_manifest.read_bytes())
        bundle_root = resolved_manifest.parent
        for file in manifest.files:
            artifact = (bundle_root / file.path).resolve(strict=True)
            try:
                artifact.relative_to(bundle_root)
            except ValueError as error:
                raise ValueError("AQ-DATA-CATALOG-FILE-ESCAPE: artifact outside bundle") from error
            if artifact.stat().st_size != file.size_bytes or sha256_file(artifact) != file.sha256:
                raise ValueError(f"AQ-DATA-CATALOG-HASH-MISMATCH: {file.path}")
        return manifest

    def register(self, manifest_path: Path) -> CatalogEntry:
        """Register only after the committed manifest and every artifact verify."""
        manifest = self.verify_manifest(manifest_path)
        root = self.lake_root.resolve(strict=True)
        relative_manifest = manifest_path.resolve(strict=True).relative_to(root).as_posix()
        entry = CatalogEntry(
            dataset_id=manifest.dataset_id,
            manifest_hash=manifest.manifest_hash(),
            manifest_path=relative_manifest,
            dataset_name=manifest.dataset_name,
            provider_id=manifest.provider_id,
            layer=manifest.layer,
            schema_version=manifest.schema_version,
            row_count=manifest.row_count,
        )
        entries = self._entries()
        existing = next((item for item in entries if item.dataset_id == manifest.dataset_id), None)
        if existing is not None:
            if existing != entry:
                raise ValueError("AQ-DATA-CATALOG-ID-CONFLICT: dataset ID metadata differs")
            return existing
        entries.append(entry)
        entries.sort(key=lambda item: str(item.dataset_id))
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_name(f".{self.index_path.name}.tmp")
        with temporary.open("wb") as output:
            for item in entries:
                output.write(canonical_json_bytes(item.model_dump(mode="json")))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.index_path)
        return entry

    def query(
        self,
        *,
        provider_id: ProviderId | None = None,
        dataset_name: str | None = None,
        layer: LakeLayer | None = None,
        schema_version: str | None = None,
        manifest_hash: str | None = None,
    ) -> tuple[CatalogEntry, ...]:
        if manifest_hash is not None:
            ensure_sha256(manifest_hash, field_name="manifest_hash")
        return tuple(
            entry
            for entry in self._entries()
            if (provider_id is None or entry.provider_id == provider_id)
            and (dataset_name is None or entry.dataset_name == dataset_name)
            and (layer is None or entry.layer is layer)
            and (schema_version is None or entry.schema_version == schema_version)
            and (manifest_hash is None or entry.manifest_hash == manifest_hash)
        )
