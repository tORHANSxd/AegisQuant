"""Hardened in-memory DuckDB connections with explicit local path allowlists."""

from __future__ import annotations

from pathlib import Path

import duckdb


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def secure_duckdb_connection(*, allowed_root: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Create a connection that cannot load extensions, secrets, URLs, or other paths."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads = 1")
        connection.execute("SET autoinstall_known_extensions = false")
        connection.execute("SET autoload_known_extensions = false")
        connection.execute("SET allow_community_extensions = false")
        connection.execute("SET allow_unsigned_extensions = false")
        connection.execute("SET allow_persistent_secrets = false")
        if allowed_root is not None:
            root = allowed_root.resolve(strict=True).as_posix()
            connection.execute(f"SET allowed_directories = [{_sql_string(root)}]")
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
        return connection
    except Exception:
        connection.close()
        raise
