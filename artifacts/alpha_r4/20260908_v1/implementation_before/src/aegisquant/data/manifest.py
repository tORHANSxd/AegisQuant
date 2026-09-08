"""Parquet file inspection and deterministic dataset-manifest construction."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

import pyarrow as pa
import pyarrow.parquet as pq

from aegisquant.data.hashing import canonical_sha256, sha256_file
from aegisquant.data.lineage import TransformationLineage
from aegisquant.data.models import DatasetFile, DatasetManifest, LakeLayer
from aegisquant.domain.identifiers import ArtifactId, DatasetId, ProviderId
from aegisquant.domain.time import UtcDateTime, ensure_utc


class _ParquetBatchIterator(Protocol):
    def __call__(self, *, batch_size: int, columns: list[str]) -> Iterator[pa.RecordBatch]: ...


class _PythonListColumn(Protocol):
    def to_pylist(self) -> list[object]: ...


def _iter_parquet_batches(
    parquet_file: pq.ParquetFile, *, columns: list[str]
) -> Iterator[pa.RecordBatch]:
    iterator = cast(
        _ParquetBatchIterator,
        getattr(parquet_file, "iter_batches"),  # noqa: B009
    )(
        batch_size=65_536,
        columns=columns,
    )
    return iterator


def _batch_time_range(batch: pa.RecordBatch, index: int) -> tuple[datetime | None, datetime | None]:
    values = cast(_PythonListColumn, batch.column(index)).to_pylist()
    aware_values: list[datetime] = []
    for value in values:
        if value is None:
            continue
        if not isinstance(value, datetime):
            raise ValueError("time column must contain timestamps")
        aware_values.append(ensure_utc(value))
    if not aware_values:
        return None, None
    return min(aware_values), max(aware_values)


def arrow_schema_hash(schema: pa.Schema) -> str:
    """Hash a stable textual Arrow schema including field and schema metadata."""
    payload = {
        "schema": schema.to_string(show_field_metadata=True, show_schema_metadata=True),
    }
    return canonical_sha256(payload)


def _parquet_time_range(
    parquet_file: pq.ParquetFile, time_column: str | None
) -> tuple[datetime | None, datetime | None]:
    if time_column is None or time_column not in parquet_file.schema_arrow.names:
        return None, None
    minimum: datetime | None = None
    maximum: datetime | None = None
    for batch in _iter_parquet_batches(parquet_file, columns=[time_column]):
        batch_min, batch_max = _batch_time_range(batch, 0)
        if batch_min is None or batch_max is None:
            continue
        minimum = batch_min if minimum is None else min(minimum, batch_min)
        maximum = batch_max if maximum is None else max(maximum, batch_max)
    return minimum, maximum


def inspect_parquet_file(*, root: Path, path: Path, time_column: str | None = None) -> DatasetFile:
    """Inspect one local Parquet file without materializing it in memory."""
    resolved_root = root.resolve(strict=True)
    resolved_path = path.resolve(strict=True)
    try:
        relative = resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as error:
        raise ValueError(
            "AQ-DATA-PATH-ESCAPE: Parquet file is outside the declared root"
        ) from error
    parquet_file = pq.ParquetFile(resolved_path)
    minimum, maximum = _parquet_time_range(parquet_file, time_column)
    return DatasetFile(
        path=relative,
        sha256=sha256_file(resolved_path),
        size_bytes=resolved_path.stat().st_size,
        rows=parquet_file.metadata.num_rows,
        schema_sha256=arrow_schema_hash(parquet_file.schema_arrow),
        min_time=minimum,
        max_time=maximum,
    )


def build_dataset_manifest(
    *,
    dataset_name: str,
    schema_version: str,
    provider_id: ProviderId,
    layer: LakeLayer,
    files: tuple[DatasetFile, ...],
    available_time_policy: str,
    lineage: TransformationLineage,
    quality_report_id: ArtifactId,
    created_at_utc: UtcDateTime,
) -> DatasetManifest:
    """Build a manifest whose dataset ID is its stable identity hash."""
    minimums = [file.min_time for file in files if file.min_time is not None]
    maximums = [file.max_time for file in files if file.max_time is not None]
    time_range: tuple[datetime | None, datetime | None] = (
        min(minimums) if minimums else None,
        max(maximums) if maximums else None,
    )
    identity = {
        "manifest_version": "1.0.0",
        "dataset_name": dataset_name,
        "schema_version": schema_version,
        "provider_id": str(provider_id),
        "layer": layer.value,
        "time_range": [
            value.isoformat().replace("+00:00", "Z") if value else None for value in time_range
        ],
        "available_time_policy": available_time_policy,
        "files": [file.model_dump(mode="json") for file in files],
        "row_count": sum(file.rows for file in files),
        "transform_commit": lineage.code_commit,
        "transform_config_hash": lineage.config_hash,
        "source_request_hash": lineage.source_request_hash,
        "quality_report_id": str(quality_report_id),
        "lineage_hash": lineage.content_hash(),
    }
    dataset_id = DatasetId(canonical_sha256(identity))
    return DatasetManifest(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        schema_version=schema_version,
        provider_id=provider_id,
        layer=layer,
        time_range=time_range,
        available_time_policy=available_time_policy,
        files=files,
        row_count=sum(file.rows for file in files),
        transform_commit=lineage.code_commit,
        transform_config_hash=lineage.config_hash,
        source_request_hash=lineage.source_request_hash,
        quality_report_id=quality_report_id,
        lineage_hash=lineage.content_hash(),
        created_at_utc=created_at_utc,
    )
