"""Empty-database migration, transaction, Outbox, and Inbox contracts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import IntegrityError

from aegisquant.accounting.models import (
    ReconciliationMode,
    VenueAccountSnapshot,
)
from aegisquant.accounting.reconciliation import reconcile_account_snapshots
from aegisquant.accounting.snapshots import Ed25519SnapshotSigner, create_daily_snapshot
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import AccountSnapshotId
from aegisquant.persistence.accounting import (
    append_ledger_record,
    load_ledger_records,
    persist_accounting_configuration,
    store_daily_snapshot,
    store_reconciliation_case,
)
from aegisquant.persistence.database import create_postgres_engine
from aegisquant.persistence.messaging import (
    StoredEvent,
    append_event_with_outbox,
    record_inbox_once,
)
from aegisquant.persistence.tables import (
    accounting_ledger_entries,
    accounting_ledger_postings,
    accounting_position_lots,
    domain_events,
    inbox_messages,
    outbox_messages,
)
from tests.p05.helpers import NOW, fill, spot_instrument
from tests.p05.helpers import engine as accounting_engine

EXPECTED_TABLES = {
    "account_reconciliation_cases",
    "accounting_accounts",
    "accounting_entry_templates",
    "accounting_ledger_entries",
    "accounting_ledger_postings",
    "accounting_position_lots",
    "alembic_version",
    "daily_ledger_snapshots",
    "domain_events",
    "event_schema_registry",
    "inbox_messages",
    "instrument_registry",
    "outbox_messages",
    "provider_registry",
    "read_model_projection_checkpoints",
    "read_model_records",
    "read_model_snapshot_state",
    "source_document_registry",
}


def alembic_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    return Config(str(root / "alembic.ini"))


def remove_alembic_version(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def migrated_engine(postgres_dsn: str) -> Iterator[Engine]:
    engine = create_postgres_engine(postgres_dsn, pool_size=2)
    command.upgrade(alembic_config(), "head")
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(alembic_config(), "base")
        cleanup_engine = create_postgres_engine(postgres_dsn, pool_size=1)
        remove_alembic_version(cleanup_engine)
        cleanup_engine.dispose()


@pytest.mark.postgres
def test_empty_database_upgrade_and_full_rollback(postgres_dsn: str) -> None:
    engine = create_postgres_engine(postgres_dsn, pool_size=1)
    remove_alembic_version(engine)
    assert inspect(engine).get_table_names() == []

    command.upgrade(alembic_config(), "head")
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES

    command.downgrade(alembic_config(), "base")
    remove_alembic_version(engine)
    assert inspect(engine).get_table_names() == []
    engine.dispose()


@pytest.mark.postgres
def test_event_outbox_and_inbox_replay_are_idempotent(migrated_engine: Engine) -> None:
    now = datetime(2026, 8, 31, 8, tzinfo=UTC)
    event = StoredEvent(
        event_id="event-001",
        event_type="MARKET_EVENT",
        schema_version="1.0.0",
        available_time=now,
        ingest_time=now + timedelta(seconds=1),
        payload={"price": "123.4500", "unit": "USDT/BTC"},
        idempotency_key="event-semantic-key-001",
    )
    with migrated_engine.begin() as connection:
        first = append_event_with_outbox(
            connection,
            event=event,
            message_id="message-001",
            topic="market.events",
            outbox_idempotency_key="outbox-semantic-key-001",
        )
    with migrated_engine.begin() as connection:
        replay = append_event_with_outbox(
            connection,
            event=event,
            message_id="message-replay",
            topic="market.events",
            outbox_idempotency_key="outbox-semantic-key-replay",
        )
        inbox_first = record_inbox_once(
            connection,
            consumer_name="projector",
            message_id="message-001",
            idempotency_key="consume-semantic-key-001",
            payload_hash="a" * 64,
            result_code="APPLIED",
        )
        inbox_replay = record_inbox_once(
            connection,
            consumer_name="projector",
            message_id="message-redelivery",
            idempotency_key="consume-semantic-key-001",
            payload_hash="a" * 64,
            result_code="APPLIED",
        )

    assert first is True
    assert replay is False
    assert inbox_first is True
    assert inbox_replay is False
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(domain_events)) == 1
        assert connection.scalar(select(func.count()).select_from(outbox_messages)) == 1
        assert connection.scalar(select(func.count()).select_from(inbox_messages)) == 1


@pytest.mark.postgres
def test_outbox_failure_rolls_back_event_atomically(migrated_engine: Engine) -> None:
    now = datetime(2026, 8, 31, 8, tzinfo=UTC)
    first = StoredEvent(
        event_id="event-first",
        event_type="MARKET_EVENT",
        schema_version="1.0.0",
        available_time=now,
        ingest_time=now,
        payload={"fact": "first"},
        idempotency_key="event-first-key",
    )
    second = StoredEvent(
        event_id="event-second",
        event_type="MARKET_EVENT",
        schema_version="1.0.0",
        available_time=now,
        ingest_time=now,
        payload={"fact": "second"},
        idempotency_key="event-second-key",
    )
    with migrated_engine.begin() as connection:
        append_event_with_outbox(
            connection,
            event=first,
            message_id="duplicate-message",
            topic="market.events",
            outbox_idempotency_key="outbox-first-key",
        )

    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        append_event_with_outbox(
            connection,
            event=second,
            message_id="duplicate-message",
            topic="market.events",
            outbox_idempotency_key="outbox-second-key",
        )

    with migrated_engine.connect() as connection:
        second_count = connection.scalar(
            select(func.count())
            .select_from(domain_events)
            .where(domain_events.c.event_id == "event-second")
        )
        assert second_count == 0


@pytest.mark.postgres
def test_accounting_facts_projections_reconciliation_and_snapshots_are_durable(
    migrated_engine: Engine, project_root: Path
) -> None:
    ledger = accounting_engine(project_root)
    spec = spot_instrument()
    ledger.process_fill(fill(spec, sequence=1, side=OrderSide.BUY, quantity="1", price="100"), spec)
    ledger.process_fill(
        fill(spec, sequence=2, side=OrderSide.SELL, quantity="0.5", price="120"), spec
    )
    snapshot = VenueAccountSnapshot(
        account_snapshot_id=AccountSnapshotId("postgres-account-snapshot"),
        venue="SIM",
        as_of_time=NOW,
        balances=(),
        positions=(),
    )
    case = reconcile_account_snapshots(
        local=snapshot,
        venue=snapshot,
        mode=ReconciliationMode.STARTUP,
        opened_at=NOW,
    )
    signed = create_daily_snapshot(
        engine=ledger,
        signer=Ed25519SnapshotSigner.generate(),
        snapshot_date=date(2026, 9, 1),
        created_at=NOW,
    )
    with migrated_engine.begin() as connection:
        persist_accounting_configuration(
            connection,
            chart=ledger.chart.snapshot(),
            templates=tuple(ledger.templates.values()),
        )
        assert append_ledger_record(connection, record=ledger.records[0]) is True
        assert append_ledger_record(connection, record=ledger.records[1]) is True
        assert append_ledger_record(connection, record=ledger.records[1]) is False
        assert store_reconciliation_case(connection, case=case) is True
        assert store_reconciliation_case(connection, case=case) is False
        assert store_daily_snapshot(connection, snapshot=signed) is True
        assert store_daily_snapshot(connection, snapshot=signed) is False

    with migrated_engine.connect() as connection:
        loaded = load_ledger_records(connection)
        assert loaded == ledger.records
        assert connection.scalar(select(func.count()).select_from(accounting_ledger_entries)) == 2
        assert connection.scalar(
            select(func.count()).select_from(accounting_ledger_postings)
        ) == sum(len(record.journal_entry.postings) for record in ledger.records)
        remaining = connection.scalar(
            select(accounting_position_lots.c.remaining_quantity).where(
                accounting_position_lots.c.status == "OPEN"
            )
        )
        assert remaining == Decimal("0.5")

    conflict = ledger.records[1].model_copy(
        update={"command_hash": "f" * 64, "event_hash": "e" * 64}
    )
    with (
        pytest.raises(ValueError, match="PERSISTENCE-IDEMPOTENCY-CONFLICT"),
        migrated_engine.begin() as connection,
    ):
        append_ledger_record(connection, record=conflict)
