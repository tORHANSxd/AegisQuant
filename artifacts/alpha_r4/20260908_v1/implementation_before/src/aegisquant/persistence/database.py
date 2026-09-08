"""Explicit PostgreSQL engine and transaction boundaries."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import Connection, make_url


def create_postgres_engine(dsn: str, *, pool_size: int = 5) -> Engine:
    """Create a Psycopg engine without connecting or logging parameters."""
    url = make_url(dsn)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("database URL must use postgresql+psycopg")
    if pool_size < 1:
        raise ValueError("pool_size must be positive")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        hide_parameters=True,
    )


@contextmanager
def transaction(engine: Engine) -> Generator[Connection]:
    """Commit a complete unit of work or roll it back atomically."""
    with engine.begin() as connection:
        yield connection
