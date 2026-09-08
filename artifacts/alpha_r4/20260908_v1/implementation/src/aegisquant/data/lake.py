"""Atomic immutable Parquet dataset publication and catalog registration."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

import pyarrow as pa
import pyarrow.parquet as pq

from aegisquant.data.catalog import CatalogEntry, DataCatalog
from aegisquant.data.hashing import canonical_json_bytes, safe_path_segment
from aegisquant.data.lineage import TransformationLineage
from aegisquant.data.manifest import build_dataset_manifest, inspect_parquet_file
from aegisquant.data.models import DatasetFile, DatasetManifest, LakeLayer, QualityReport
from aegisquant.data.provider_registry import ProviderRegistry
from aegisquant.data.quality import enforce_layer_quality
from aegisquant.data.schema_registry import ArrowSchemaRegistry
from aegisquant.domain.errors import DomainError, ErrorDisposition
from aegisquant.domain.identifiers import ProviderId
from aegisquant.domain.policy import DerivedStorageMode, RawStorageMode, SourceProcessingPolicy
from aegisquant.domain.time import Clock

FaultHook = Callable[[str], None]
Compression = Literal["brotli", "gzip", "lz4", "none", "snappy", "zstd"]


class _ParquetWrite(Protocol):
    def __call__(
        self,
        table: pa.Table,
        where: Path,
        *,
        compression: Compression,
        row_group_size: int,
        version: Literal["2.6"],
        use_dictionary: bool,
        write_statistics: bool,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PublishedDataset:
    manifest: DatasetManifest
    manifest_path: Path
    catalog_entry: CatalogEntry


@dataclass(frozen=True, slots=True)
class AtomicDatasetWriter:
    lake_root: Path
    catalog: DataCatalog
    schema_registry: ArrowSchemaRegistry
    provider_registry: ProviderRegistry
    clock: Clock
    row_group_size: int = 65_536
    compression: Compression = "zstd"

    def _write_manifest(self, path: Path, manifest: DatasetManifest) -> None:
        with path.open("wb") as output:
            output.write(canonical_json_bytes(manifest.model_dump(mode="json")))
            output.flush()
            os.fsync(output.fileno())

    def write_table(
        self,
        *,
        table: pa.Table,
        provider_id: ProviderId,
        policy: SourceProcessingPolicy,
        dataset_name: str,
        schema_version: str,
        requested_layer: LakeLayer,
        available_time_policy: str,
        lineage: TransformationLineage,
        quality_report: QualityReport,
        time_column: str | None = None,
        fault_hook: FaultHook | None = None,
    ) -> PublishedDataset:
        """Stage, verify, atomically publish, then register one immutable dataset."""
        if self.catalog.lake_root.resolve() != self.lake_root.resolve():
            raise ValueError("catalog and writer must share one lake root")
        safe_path_segment(dataset_name, field_name="dataset_name")
        provider_segment = safe_path_segment(str(provider_id), field_name="provider_id")
        self.provider_registry.require_collection(provider_id, policy)
        if requested_layer in {LakeLayer.RAW, LakeLayer.BRONZE}:
            self.provider_registry.require_archive(provider_id, policy)
            if policy.raw_storage is RawStorageMode.METADATA_ONLY and table.num_rows:
                raise DomainError(
                    "AQ-PROVIDER-RAW-METADATA-ONLY",
                    ErrorDisposition.NO_RETRY,
                    str(provider_id),
                )
            if policy.raw_storage is RawStorageMode.ENCRYPTED_LOCAL:
                raise DomainError(
                    "AQ-DATA-USE-ENCRYPTED-REVISION-ARCHIVE",
                    ErrorDisposition.NO_RETRY,
                    str(provider_id),
                )
        elif policy.derived_storage is not DerivedStorageMode.ALLOWED:
            raise DomainError(
                "AQ-PROVIDER-DERIVED-STORAGE-DENIED",
                ErrorDisposition.NO_RETRY,
                str(provider_id),
            )
        actual_layer = enforce_layer_quality(requested_layer=requested_layer, report=quality_report)
        if self.row_group_size < 1:
            raise ValueError("row_group_size must be positive")
        self.lake_root.mkdir(parents=True, exist_ok=True)
        staging_root = self.lake_root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="dataset-", dir=staging_root))
        try:
            parquet_path = staging / "part-00000.parquet"
            cast(_ParquetWrite, getattr(pq, "write_table"))(  # noqa: B009
                table,
                parquet_path,
                compression=self.compression,
                row_group_size=self.row_group_size,
                version="2.6",
                use_dictionary=True,
                write_statistics=True,
            )
            with parquet_path.open("r+b") as source:
                os.fsync(source.fileno())
            if fault_hook is not None:
                fault_hook("after_parquet_fsync")
            inspected = inspect_parquet_file(
                root=staging, path=parquet_path, time_column=time_column
            )
            file_entry = DatasetFile(
                path="part-00000.parquet",
                sha256=inspected.sha256,
                size_bytes=inspected.size_bytes,
                rows=inspected.rows,
                schema_sha256=inspected.schema_sha256,
                min_time=inspected.min_time,
                max_time=inspected.max_time,
            )
            self.schema_registry.register(
                schema_name=dataset_name,
                schema_version=schema_version,
                schema=table.schema,
            )
            manifest = build_dataset_manifest(
                dataset_name=dataset_name,
                schema_version=schema_version,
                provider_id=provider_id,
                layer=actual_layer,
                files=(file_entry,),
                available_time_policy=available_time_policy,
                lineage=lineage,
                quality_report_id=quality_report.quality_report_id,
                created_at_utc=self.clock.now(),
            )
            self._write_manifest(staging / "manifest.json", manifest)
            if fault_hook is not None:
                fault_hook("before_atomic_publish")
            final_directory = (
                self.lake_root
                / actual_layer.value
                / provider_segment
                / dataset_name
                / str(manifest.dataset_id)
            )
            final_directory.parent.mkdir(parents=True, exist_ok=True)
            manifest_path = final_directory / "manifest.json"
            if final_directory.exists():
                existing = self.catalog.verify_manifest(manifest_path)
                if existing.manifest_hash() != manifest.manifest_hash():
                    raise ValueError("AQ-DATA-IMMUTABLE-CONFLICT: dataset ID already exists")
                shutil.rmtree(staging)
                entry = self.catalog.register(manifest_path)
                return PublishedDataset(existing, manifest_path, entry)
            os.replace(staging, final_directory)
            if fault_hook is not None:
                fault_hook("after_atomic_publish")
            entry = self.catalog.register(manifest_path)
            return PublishedDataset(manifest, manifest_path, entry)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
