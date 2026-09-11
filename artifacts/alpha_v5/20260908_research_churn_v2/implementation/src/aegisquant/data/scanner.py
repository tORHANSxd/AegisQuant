"""Read-only streaming local-asset inventory and import-proposal generation."""

from __future__ import annotations

import json
import mimetypes
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.json as pajson
import pyarrow.parquet as pq

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, sha256_file
from aegisquant.data.models import ImportAction, ImportProposal, InventoryRecord
from aegisquant.domain.identifiers import DatasetId

STRUCTURED_EXTENSIONS = frozenset({".csv", ".jsonl", ".ndjson", ".parquet"})
CODE_EXTENSIONS = frozenset({".bat", ".cmd", ".dll", ".exe", ".ipynb", ".ps1", ".py", ".sql"})
STRATEGY_HINTS = ("backtest", "equity", "pnl", "result", "strategy", "trade")

INVENTORY_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("root_label", pa.string()),
        ("relative_path", pa.string()),
        ("extension", pa.string()),
        ("mime_type", pa.string()),
        ("size_bytes", pa.int64()),
        ("modified_time", pa.timestamp("us", tz="UTC")),
        ("sha256", pa.string()),
        ("row_count", pa.int64()),
        ("schema_json", pa.string()),
        ("schema_sha256", pa.string()),
        ("min_time", pa.timestamp("us", tz="UTC")),
        ("max_time", pa.timestamp("us", tz="UTC")),
        ("duplicate_group", pa.string()),
        ("possible_strategy_result", pa.bool_()),
    ]
)


class _PythonListColumn(Protocol):
    def to_pylist(self) -> list[object]: ...


class _ParquetBatchIterator(Protocol):
    def __call__(
        self, *, batch_size: int, columns: list[str] | None
    ) -> Iterator[pa.RecordBatch]: ...


class _SchemaFieldLookup(Protocol):
    def __call__(self, index: int) -> pa.Field[pa.DataType]: ...


def _schema_fields(schema: pa.Schema) -> Iterator[pa.Field[pa.DataType]]:
    field_at = cast(_SchemaFieldLookup, getattr(schema, "field"))  # noqa: B009
    for index in range(len(schema)):
        yield field_at(index)


def _schema_json(schema: pa.Schema) -> str:
    fields = [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
        }
        for field in _schema_fields(schema)
    ]
    return json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _update_time_bounds(
    batch: pa.RecordBatch,
    minimum: datetime | None,
    maximum: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    for index, field in enumerate(_schema_fields(batch.schema)):
        if not pa.types.is_timestamp(field.type):
            continue
        values = cast(_PythonListColumn, batch.column(index)).to_pylist()
        for value in values:
            if not isinstance(value, datetime) or value.tzinfo is None:
                continue
            current = value.astimezone(UTC)
            minimum = current if minimum is None else min(minimum, current)
            maximum = current if maximum is None else max(maximum, current)
    return minimum, maximum


def _reader_metadata(
    reader: pa.RecordBatchReader,
) -> tuple[int, str, str, datetime | None, datetime | None]:
    schema_json = _schema_json(reader.schema)
    rows = 0
    minimum: datetime | None = None
    maximum: datetime | None = None
    for batch in reader:
        rows += batch.num_rows
        minimum, maximum = _update_time_bounds(batch, minimum, maximum)
    return rows, schema_json, canonical_sha256(json.loads(schema_json)), minimum, maximum


def _structured_metadata(
    path: Path,
) -> tuple[int | None, str | None, str | None, datetime | None, datetime | None]:
    extension = path.suffix.lower()
    if extension == ".parquet":
        parquet_file = pq.ParquetFile(path)
        schema_json = _schema_json(parquet_file.schema_arrow)
        minimum: datetime | None = None
        maximum: datetime | None = None
        timestamp_columns = [
            field.name
            for field in _schema_fields(parquet_file.schema_arrow)
            if pa.types.is_timestamp(field.type)
        ]
        batches = cast(
            _ParquetBatchIterator,
            getattr(parquet_file, "iter_batches"),  # noqa: B009
        )(batch_size=65_536, columns=timestamp_columns or None)
        for batch in batches:
            minimum, maximum = _update_time_bounds(batch, minimum, maximum)
        return (
            parquet_file.metadata.num_rows,
            schema_json,
            canonical_sha256(json.loads(schema_json)),
            minimum,
            maximum,
        )
    if extension == ".csv":
        reader = pacsv.open_csv(
            path,
            read_options=pacsv.ReadOptions(block_size=1024 * 1024, use_threads=False),
        )
        return _reader_metadata(reader)
    if extension in {".jsonl", ".ndjson"}:
        reader = pajson.open_json(
            path,
            read_options=pajson.ReadOptions(block_size=1024 * 1024, use_threads=False),
        )
        return _reader_metadata(reader)
    return None, None, None, None, None


def _walk_regular_files(root: Path) -> Iterator[Path]:
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            ordered = sorted(entries, key=lambda entry: entry.name.casefold(), reverse=True)
        for entry in ordered:
            if entry.is_symlink():
                continue
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                yield path


@dataclass(frozen=True, slots=True)
class ReadOnlyAssetScanner:
    hash_buffer_bytes: int = 1024 * 1024

    def iter_records(self, *, root: Path, root_label: str) -> Iterator[InventoryRecord]:
        """Yield inventory rows without writing to or executing anything under root."""
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir() or resolved_root.is_symlink():
            raise ValueError("scan root must be a regular directory, not a symlink")
        if not root_label or len(root_label) > 128:
            raise ValueError("root_label is required and must be at most 128 characters")
        for path in _walk_regular_files(resolved_root):
            before = path.stat(follow_symlinks=False)
            content_hash = sha256_file(path, buffer_size=self.hash_buffer_bytes)
            row_count, schema_json, schema_hash, minimum, maximum = _structured_metadata(path)
            after = path.stat(follow_symlinks=False)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f"AQ-DATA-SCAN-RACE: file changed while scanning: {path.name}")
            relative = path.relative_to(resolved_root).as_posix()
            lower_name = path.name.casefold()
            yield InventoryRecord(
                dataset_id=DatasetId(content_hash),
                root_label=root_label,
                relative_path=relative,
                extension=path.suffix.lower(),
                mime_type=mimetypes.guess_type(path.name, strict=False)[0],
                size_bytes=before.st_size,
                modified_time=datetime.fromtimestamp(before.st_mtime, tz=UTC),
                sha256=content_hash,
                row_count=row_count,
                schema_json=schema_json,
                schema_sha256=schema_hash,
                min_time=minimum,
                max_time=maximum,
                duplicate_group=content_hash,
                possible_strategy_result=any(hint in lower_name for hint in STRATEGY_HINTS),
            )

    @staticmethod
    def proposal_for(record: InventoryRecord) -> ImportProposal:
        extension = record.extension
        if extension in CODE_EXTENSIONS:
            return ImportProposal(
                dataset_id=record.dataset_id,
                relative_path=record.relative_path,
                action=ImportAction.REVIEW,
                reasons=("code_or_executable_asset", "static_analysis_and_sandbox_required"),
                requires_static_analysis=True,
            )
        if extension in STRUCTURED_EXTENSIONS:
            return ImportProposal(
                dataset_id=record.dataset_id,
                relative_path=record.relative_path,
                action=ImportAction.ELIGIBLE_AFTER_APPROVAL,
                reasons=(
                    "recognized_structured_format",
                    "source_policy_and_schema_review_required",
                ),
                requires_static_analysis=False,
            )
        return ImportProposal(
            dataset_id=record.dataset_id,
            relative_path=record.relative_path,
            action=ImportAction.REVIEW,
            reasons=("unknown_or_unsupported_format",),
            requires_static_analysis=False,
        )

    @staticmethod
    def _validate_output_outside_root(*, root: Path, output: Path) -> None:
        resolved_root = root.resolve(strict=True)
        resolved_output = output.resolve(strict=False)
        try:
            resolved_output.relative_to(resolved_root)
        except ValueError:
            return
        raise ValueError("AQ-DATA-SCAN-READ-ONLY: output cannot be inside the source root")

    def scan_to_parquet(
        self,
        *,
        root: Path,
        root_label: str,
        output: Path,
        proposals_output: Path | None = None,
        batch_size: int = 256,
    ) -> tuple[int, int]:
        """Stream inventory rows to an external Parquet report in bounded batches."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._validate_output_outside_root(root=root, output=output)
        if proposals_output is not None:
            self._validate_output_outside_root(root=root, output=proposals_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        proposal_temporary = (
            proposals_output.with_name(f".{proposals_output.name}.tmp")
            if proposals_output is not None
            else None
        )
        if proposals_output is not None:
            proposals_output.parent.mkdir(parents=True, exist_ok=True)
        writer = pq.ParquetWriter(temporary, INVENTORY_SCHEMA, compression="zstd")
        count = 0
        proposal_count = 0
        rows: list[dict[str, object]] = []
        try:
            proposal_file = (
                proposal_temporary.open("wb") if proposal_temporary is not None else None
            )
            try:
                for record in self.iter_records(root=root, root_label=root_label):
                    row = record.model_dump(mode="python", by_alias=True)
                    row["dataset_id"] = str(record.dataset_id)
                    rows.append(row)
                    count += 1
                    if proposal_file is not None:
                        proposal = self.proposal_for(record)
                        proposal_file.write(canonical_json_bytes(proposal.model_dump(mode="json")))
                        proposal_count += 1
                    if len(rows) >= batch_size:
                        writer.write_table(pa.Table.from_pylist(rows, schema=INVENTORY_SCHEMA))
                        rows.clear()
                if proposal_file is not None:
                    proposal_file.flush()
                    os.fsync(proposal_file.fileno())
            finally:
                if proposal_file is not None:
                    proposal_file.close()
            if rows:
                writer.write_table(pa.Table.from_pylist(rows, schema=INVENTORY_SCHEMA))
            writer.close()
            os.replace(temporary, output)
            if proposals_output is not None and proposal_temporary is not None:
                os.replace(proposal_temporary, proposals_output)
        except Exception:
            writer.close()
            temporary.unlink(missing_ok=True)
            if proposal_temporary is not None:
                proposal_temporary.unlink(missing_ok=True)
            raise
        return count, proposal_count


def write_import_proposals(path: Path, proposals: tuple[ImportProposal, ...]) -> None:
    """Write review-only proposals atomically; never import the referenced assets."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as output:
        for proposal in proposals:
            output.write(canonical_json_bytes(proposal.model_dump(mode="json")))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
