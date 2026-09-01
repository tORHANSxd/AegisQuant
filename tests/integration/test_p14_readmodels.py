"""Real PostgreSQL P14 migration, atomic replacement, and read-only role contracts."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import ProgrammingError

from aegisquant.persistence.database import create_postgres_engine
from aegisquant.readmodels.bootstrap import build_snapshot
from aegisquant.readmodels.persistence import load_snapshot, replace_snapshot


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    return Config(str(root / "alembic.ini"))


def _role_dsn(dsn: str, role: str) -> str:
    value = urlsplit(dsn)
    host = value.hostname or "127.0.0.1"
    netloc = f"{role}@{host}:{value.port}"
    return urlunsplit((value.scheme, netloc, value.path, value.query, value.fragment))


@pytest.mark.postgres
def test_snapshot_round_trip_is_atomic_and_service_role_is_read_only(
    postgres_dsn: str, project_root: Path
) -> None:
    engine = create_postgres_engine(postgres_dsn, pool_size=2)
    command.upgrade(_alembic_config(), "head")
    snapshot = build_snapshot(project_root)
    try:
        with engine.begin() as connection:
            replace_snapshot(connection, snapshot)
        with engine.connect() as connection:
            assert load_snapshot(connection) == snapshot

        with pytest.raises(RuntimeError, match="rollback candidate"), engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM read_model_records"))
            raise RuntimeError("rollback candidate")
        with engine.connect() as connection:
            assert load_snapshot(connection) == snapshot

        with engine.begin() as connection:
            connection.execute(sa.text("CREATE ROLE aegisquant_read_api LOGIN"))
            connection.execute(sa.text("GRANT CONNECT ON DATABASE postgres TO aegisquant_read_api"))
            connection.execute(sa.text("GRANT USAGE ON SCHEMA public TO aegisquant_read_api"))
            connection.execute(
                sa.text(
                    "GRANT SELECT ON read_model_records, read_model_projection_checkpoints, "
                    "read_model_snapshot_state TO aegisquant_read_api"
                )
            )
        read_engine = create_postgres_engine(
            _role_dsn(postgres_dsn, "aegisquant_read_api"), pool_size=1
        )
        try:
            with read_engine.connect() as connection:
                assert connection.scalar(sa.text("SELECT count(*) FROM read_model_records")) == 15
            with pytest.raises(ProgrammingError), read_engine.begin() as connection:
                connection.execute(sa.text("DELETE FROM read_model_records"))
        finally:
            read_engine.dispose()
    finally:
        command.downgrade(_alembic_config(), "base")
        with engine.begin() as connection:
            connection.execute(sa.text("DROP OWNED BY aegisquant_read_api"))
            connection.execute(sa.text("DROP ROLE IF EXISTS aegisquant_read_api"))
            connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()
