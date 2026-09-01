"""Real PostgreSQL fill → ledger → event → Outbox atomicity."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import Engine, func, select

import aegisquant.execution.atomic as atomic_module
from aegisquant.accounting.ledger import LedgerEngine
from aegisquant.domain.execution import OrderSide
from aegisquant.execution.atomic import persist_fill_atomically
from aegisquant.persistence.accounting import persist_accounting_configuration
from aegisquant.persistence.database import create_postgres_engine
from aegisquant.persistence.tables import (
    accounting_ledger_entries,
    domain_events,
    outbox_messages,
)
from tests.p05.helpers import engine as accounting_engine
from tests.p05.helpers import fill, spot_instrument


@pytest.fixture
def p12_migrated_engine(postgres_dsn: str, project_root: Path) -> Iterator[Engine]:
    engine = create_postgres_engine(postgres_dsn, pool_size=2)
    config = Config(str(project_root / "alembic.ini"))
    alembic_command.upgrade(config, "head")
    try:
        yield engine
    finally:
        engine.dispose()
        alembic_command.downgrade(config, "base")


def configure(engine: Engine, ledger: LedgerEngine) -> None:
    with engine.begin() as connection:
        persist_accounting_configuration(
            connection,
            chart=ledger.chart.snapshot(),
            templates=tuple(ledger.templates.values()),
        )


@pytest.mark.postgres
def test_fill_ledger_event_and_outbox_commit_once(
    p12_migrated_engine: Engine, project_root: Path
) -> None:
    ledger = accounting_engine(project_root)
    configure(p12_migrated_engine, ledger)
    instrument = spot_instrument()
    execution_fill = fill(
        instrument,
        sequence=1201,
        side=OrderSide.BUY,
        quantity="0.1",
        price="50000",
        fee="1",
    )
    first = persist_fill_atomically(
        engine=p12_migrated_engine,
        ledger=ledger,
        fill=execution_fill,
        instrument=instrument,
    )
    replay = persist_fill_atomically(
        engine=p12_migrated_engine,
        ledger=ledger,
        fill=execution_fill,
        instrument=instrument,
    )
    assert first.inserted is True
    assert replay.inserted is False
    assert len(ledger.records) == 1
    with p12_migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(accounting_ledger_entries)) == 1
        assert connection.scalar(select(func.count()).select_from(domain_events)) == 1
        assert connection.scalar(select(func.count()).select_from(outbox_messages)) == 1


@pytest.mark.postgres
def test_outbox_failure_rolls_back_ledger_and_memory(
    p12_migrated_engine: Engine,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = accounting_engine(project_root)
    configure(p12_migrated_engine, ledger)
    instrument = spot_instrument()
    execution_fill = fill(
        instrument,
        sequence=1202,
        side=OrderSide.BUY,
        quantity="0.1",
        price="50000",
    )

    def fail_event(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        raise RuntimeError("injected outbox failure")

    monkeypatch.setattr(atomic_module, "append_event_with_outbox", fail_event)
    with pytest.raises(RuntimeError, match="injected outbox failure"):
        persist_fill_atomically(
            engine=p12_migrated_engine,
            ledger=ledger,
            fill=execution_fill,
            instrument=instrument,
        )
    assert ledger.records == ()
    with p12_migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(accounting_ledger_entries)) == 0
        assert connection.scalar(select(func.count()).select_from(domain_events)) == 0
        assert connection.scalar(select(func.count()).select_from(outbox_messages)) == 0
