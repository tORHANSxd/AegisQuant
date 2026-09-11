"""Run the real P16 encrypted PostgreSQL restore drill or verify its evidence."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Final, cast

from alembic import command as alembic_command
from alembic.config import Config

from aegisquant.operations.backup import create_encrypted_backup, restore_encrypted_backup
from aegisquant.persistence.database import create_postgres_engine
from tests.operations.test_backup_restore import seed_authoritative_facts
from tests.postgres_runtime import PostgresTestServer

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "reports/operations/P16_RESTORE_DRILL.json"


def _validate(payload: dict[str, object]) -> None:
    checks = {
        "drill passed": payload.get("status") == "passed",
        "real PostgreSQL": payload.get("database") == "PostgreSQL 18.6",
        "restore equal": payload.get("verification_equal") is True,
        "ledger entries": payload.get("ledger_entry_count") == 2,
        "reconciliation cases": payload.get("reconciliation_case_count") == 1,
        "ledger balanced": payload.get("ledger_balanced") is True,
        "reconciliation valid": payload.get("reconciliation_valid") is True,
        "tamper rejected": payload.get("tampered_ciphertext_rejected") is True,
        "encryption": payload.get("cipher") == "AES-256-GCM",
        "acceptance deferred": payload.get("formal_acceptance_performed") is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("P16 restore evidence validation failed: " + ", ".join(failed))


def run_drill() -> dict[str, object]:
    bin_dir = ROOT / ".tools/postgresql-18.6/pgsql/bin"
    source_server = PostgresTestServer(root=ROOT, bin_dir=bin_dir)
    target_server = PostgresTestServer(root=ROOT, bin_dir=bin_dir)
    source_server.start()
    prior_dsn = os.environ.get("AEGISQUANT_TEST_DATABASE_URL")
    os.environ["AEGISQUANT_TEST_DATABASE_URL"] = source_server.dsn
    config = Config(str(ROOT / "alembic.ini"))
    alembic_command.upgrade(config, "head")
    source_engine = create_postgres_engine(source_server.dsn, pool_size=1)
    tamper_rejected = False
    try:
        seed_authoritative_facts(source_engine, ROOT)
        with tempfile.TemporaryDirectory(
            prefix="aegisquant-p16-restore-", dir=ROOT / "reports/operations"
        ) as temporary:
            work = Path(temporary)
            backup, manifest_path, manifest = create_encrypted_backup(
                dsn=source_server.dsn,
                postgres_bin=bin_dir,
                output=work / "p16-restore.aqbk",
                encryption_key=bytes(range(32)),
                metadata_paths=(ROOT / "state/PROJECT_PHASE_STATE.yaml",),
            )
            target_server.start()
            result = restore_encrypted_backup(
                backup=backup,
                manifest_path=manifest_path,
                encryption_key=bytes(range(32)),
                postgres_bin=bin_dir,
                target_dsn=target_server.dsn,
            )
            tampered = work / "tampered.aqbk"
            contents = bytearray(backup.read_bytes())
            contents[len(contents) // 2] ^= 0x01
            tampered.write_bytes(contents)
            try:
                restore_encrypted_backup(
                    backup=tampered,
                    manifest_path=manifest_path,
                    encryption_key=bytes(range(32)),
                    postgres_bin=bin_dir,
                    target_dsn=target_server.dsn,
                )
            except ValueError as error:
                tamper_rejected = "encrypted backup hash" in str(error)
        verification = result.restored
        payload: dict[str, object] = {
            "schema_version": "p16-restore-drill-v1",
            "status": result.status,
            "database": "PostgreSQL 18.6",
            "backup_format": manifest.format,
            "cipher": manifest.cipher,
            "key_delivery": "in-memory argument; never file or process argv",
            "schema_revision": verification.schema_revision,
            "ledger_entry_count": verification.ledger_entry_count,
            "ledger_posting_count": verification.ledger_posting_count,
            "reconciliation_case_count": verification.reconciliation_case_count,
            "read_model_record_count": verification.read_model_record_count,
            "last_ledger_event_hash": verification.last_ledger_event_hash,
            "ledger_chain_sha256": verification.ledger_chain_sha256,
            "ledger_balanced": verification.ledger_balanced,
            "reconciliation_valid": verification.reconciliation_valid,
            "verification_equal": result.verification_equal,
            "tampered_ciphertext_rejected": tamper_rejected,
            "offsite_copy_contract": "ciphertext and manifest only; distinct filesystem required",
            "formal_acceptance_performed": False,
            "test": "tests/operations/test_backup_restore.py",
        }
        _validate(payload)
        return payload
    finally:
        source_engine.dispose()
        target_server.stop()
        try:
            alembic_command.downgrade(config, "base")
        finally:
            source_server.stop()
            if prior_dsn is None:
                os.environ.pop("AEGISQUANT_TEST_DATABASE_URL", None)
            else:
                os.environ["AEGISQUANT_TEST_DATABASE_URL"] = prior_dsn


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.check:
        payload = cast("dict[str, object]", json.loads(OUTPUT.read_text(encoding="utf-8")))
        _validate(payload)
        print("verified P16 restore drill evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = run_drill()
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("generated P16 restore drill evidence from a real PostgreSQL restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
