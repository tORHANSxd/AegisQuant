"""Local-only DuckDB query layer for registered Parquet artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from aegisquant.data.duckdb_security import secure_duckdb_connection


@dataclass(frozen=True, slots=True)
class DuckDbQueryLayer:
    allowed_root: Path

    def _validated_paths(self, paths: tuple[Path, ...]) -> list[str]:
        root = self.allowed_root.resolve(strict=True)
        if not paths:
            raise ValueError("at least one Parquet path is required")
        validated: list[str] = []
        for path in paths:
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise ValueError("AQ-DATA-QUERY-PATH-ESCAPE: path outside allowed root") from error
            if resolved.suffix.lower() != ".parquet" or not resolved.is_file():
                raise ValueError("query layer only accepts regular Parquet files")
            validated.append(resolved.as_posix())
        return validated

    def read(self, paths: tuple[Path, ...], *, columns: tuple[str, ...] = ()) -> pa.Table:
        """Read local Parquet through DuckDB with external access disabled."""
        validated = self._validated_paths(paths)
        connection = secure_duckdb_connection(allowed_root=self.allowed_root)
        try:
            relation = connection.read_parquet(validated)
            if columns:
                for column in columns:
                    if not column.replace("_", "").isalnum():
                        raise ValueError(f"invalid column name: {column}")
                relation = relation.select(", ".join(f'"{column}"' for column in columns))
            return relation.to_arrow_table()
        finally:
            connection.close()

    def count_rows(self, paths: tuple[Path, ...]) -> int:
        validated = self._validated_paths(paths)
        connection = secure_duckdb_connection(allowed_root=self.allowed_root)
        try:
            result = (
                connection.read_parquet(validated).aggregate("count(*) AS row_count").fetchone()
            )
            if result is None or not isinstance(result[0], int):
                raise RuntimeError("DuckDB count query returned an invalid result")
            return result[0]
        finally:
            connection.close()
