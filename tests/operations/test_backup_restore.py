from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import Engine

from aegisquant.accounting.models import ReconciliationMode, VenueAccountSnapshot
from aegisquant.accounting.reconciliation import reconcile_account_snapshots
from aegisquant.accounting.snapshots import Ed25519SnapshotSigner, create_daily_snapshot
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import AccountSnapshotId
from aegisquant.operations.backup import create_encrypted_backup, restore_encrypted_backup
from aegisquant.persistence.accounting import (
    append_ledger_record,
    persist_accounting_configuration,
    store_daily_snapshot,
    store_reconciliation_case,
)
from aegisquant.persistence.database import create_postgres_engine
from tests.p05.helpers import NOW, fill, spot_instrument
from tests.p05.helpers import engine as accounting_engine
from tests.postgres_runtime import PostgresTestServer


def seed_authoritative_facts(engine: Engine, project_root: Path) -> None:
    ledger = accounting_engine(project_root)
    instrument = spot_instrument()
    ledger.process_fill(
        fill(instrument, sequence=1601, side=OrderSide.BUY, quantity="1", price="50000"),
        instrument,
    )
    ledger.process_fill(
        fill(instrument, sequence=1602, side=OrderSide.SELL, quantity="0.4", price="51000"),
        instrument,
    )
    snapshot = VenueAccountSnapshot(
        account_snapshot_id=AccountSnapshotId("p16-restore-snapshot"),
        venue="SIM",
        as_of_time=NOW,
        balances=(),
        positions=(),
    )
    reconciliation = reconcile_account_snapshots(
        local=snapshot,
        venue=snapshot,
        mode=ReconciliationMode.STARTUP,
        opened_at=NOW,
    )
    daily = create_daily_snapshot(
        engine=ledger,
        signer=Ed25519SnapshotSigner.generate(),
        snapshot_date=date(2026, 9, 1),
        created_at=NOW,
    )
    with engine.begin() as connection:
        persist_accounting_configuration(
            connection,
            chart=ledger.chart.snapshot(),
            templates=tuple(ledger.templates.values()),
        )
        for record in ledger.records:
            assert append_ledger_record(connection, record=record) is True
        assert store_reconciliation_case(connection, case=reconciliation) is True
        assert store_daily_snapshot(connection, snapshot=daily) is True


@pytest.mark.postgres
def test_encrypted_backup_restores_and_verifies_ledger_and_reconciliation(
    project_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = project_root / ".tools/postgresql-18.6/pgsql/bin"
    source_server = PostgresTestServer(root=project_root, bin_dir=bin_dir)
    source_server.start()
    monkeypatch.setenv("AEGISQUANT_TEST_DATABASE_URL", source_server.dsn)
    config = Config(str(project_root / "alembic.ini"))
    alembic_command.upgrade(config, "head")
    source = create_postgres_engine(source_server.dsn, pool_size=1)
    target = PostgresTestServer(root=project_root, bin_dir=bin_dir)
    key = bytes(range(32))
    try:
        seed_authoritative_facts(source, project_root)
        backup, manifest_path, manifest = create_encrypted_backup(
            dsn=source_server.dsn,
            postgres_bin=target.bin_dir,
            output=tmp_path / "p16-restore.aqbk",
            encryption_key=key,
            metadata_paths=(project_root / "state/PROJECT_PHASE_STATE.yaml",),
        )
        target.start()
        result = restore_encrypted_backup(
            backup=backup,
            manifest_path=manifest_path,
            encryption_key=key,
            postgres_bin=target.bin_dir,
            target_dsn=target.dsn,
        )
        assert result.status == "passed"
        assert result.verification_equal is True
        assert result.restored.ledger_entry_count == 2
        assert result.restored.reconciliation_case_count == 1
        assert result.restored.ledger_balanced is True
        assert (
            result.restored.ledger_chain_sha256 == manifest.source_verification.ledger_chain_sha256
        )

        tampered = tmp_path / "tampered.aqbk"
        data = bytearray(backup.read_bytes())
        data[len(data) // 2] ^= 0x01
        tampered.write_bytes(data)
        with pytest.raises(ValueError, match="encrypted backup hash"):
            restore_encrypted_backup(
                backup=tampered,
                manifest_path=manifest_path,
                encryption_key=key,
                postgres_bin=target.bin_dir,
                target_dsn=target.dsn,
            )
    finally:
        source.dispose()
        target.stop()
        alembic_command.downgrade(config, "base")
        source_server.stop()
