"""Real PostgreSQL fixture for P01 integration contracts."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.postgres_runtime import PostgresTestServer


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    root = Path(__file__).resolve().parents[2]
    bin_dir = root / ".tools/postgresql-18.6/pgsql/bin"
    if not (bin_dir / "pg_ctl.exe").is_file():
        pytest.fail("run scripts/setup_postgres.py before PostgreSQL contract tests")
    server = PostgresTestServer(root=root, bin_dir=bin_dir)
    previous = os.environ.get("AEGISQUANT_TEST_DATABASE_URL")
    server.start()
    os.environ["AEGISQUANT_TEST_DATABASE_URL"] = server.dsn
    try:
        yield server.dsn
    finally:
        if previous is None:
            os.environ.pop("AEGISQUANT_TEST_DATABASE_URL", None)
        else:
            os.environ["AEGISQUANT_TEST_DATABASE_URL"] = previous
        server.stop()
