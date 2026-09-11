"""Encrypted PostgreSQL backup and restore with ledger/reconciliation verification."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess  # nosec B404 - pinned PostgreSQL programs, no shell
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Final, cast

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from aegisquant.accounting.models import LedgerRecord, ReconciliationCase
from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256
from aegisquant.domain.accounting import PostingSide
from aegisquant.persistence.accounting import load_ledger_records
from aegisquant.persistence.database import create_postgres_engine
from aegisquant.persistence.tables import (
    account_reconciliation_cases,
    accounting_ledger_entries,
    accounting_ledger_postings,
    read_model_records,
)

MAGIC: Final = b"AQBK1"
NONCE_SIZE: Final = 12
TAG_SIZE: Final = 16
CHUNK_SIZE: Final = 1024 * 1024
ZERO_HASH: Final = "0" * 64


@dataclass(frozen=True, slots=True)
class DatabaseVerification:
    schema_revision: str
    ledger_entry_count: int
    ledger_posting_count: int
    reconciliation_case_count: int
    read_model_record_count: int
    last_ledger_event_hash: str
    ledger_chain_sha256: str
    ledger_balanced: bool
    reconciliation_valid: bool


@dataclass(frozen=True, slots=True)
class BackupManifest:
    schema_version: str
    created_at_utc: str
    format: str
    cipher: str
    key_id: str
    nonce_base64: str
    plaintext_sha256: str
    encrypted_sha256: str
    metadata_sha256: Mapping[str, str]
    source_verification: DatabaseVerification


@dataclass(frozen=True, slots=True)
class RestoreResult:
    status: str
    source: DatabaseVerification
    restored: DatabaseVerification
    verification_equal: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _postgres_environment(dsn: str) -> tuple[dict[str, str], str]:
    url = make_url(dsn)
    if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
        raise ValueError("backup DSN must use postgresql+psycopg with host and database")
    if url.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("P16 backup tooling is restricted to a loopback PostgreSQL endpoint")
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": url.host,
            "PGPORT": str(url.port or 5432),
            "PGUSER": url.username or "postgres",
            "PGDATABASE": url.database,
        }
    )
    if url.password is not None:
        environment["PGPASSWORD"] = url.password
    return environment, url.database


def _run_postgres(
    executable: Path,
    arguments: Sequence[str],
    *,
    dsn: str,
    root: Path,
    timeout: int = 120,
) -> None:
    if not executable.is_file():
        raise FileNotFoundError(f"required PostgreSQL executable is missing: {executable.name}")
    environment, _ = _postgres_environment(dsn)
    result = subprocess.run(  # noqa: S603  # nosec B603
        [str(executable), *arguments],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)[-4000:]
        raise RuntimeError(f"PostgreSQL operation failed safely: {executable.name}\n{output}")


def _ledger_balanced(records: tuple[LedgerRecord, ...]) -> bool:
    for record in records:
        totals: dict[str, tuple[Decimal, Decimal]] = {}
        for posting in record.journal_entry.postings:
            asset = str(posting.amount.asset_id)
            debits, credits = totals.get(asset, (Decimal("0"), Decimal("0")))
            if posting.side is PostingSide.DEBIT:
                debits += posting.amount.amount
            else:
                credits += posting.amount.amount
            totals[asset] = debits, credits
        if any(debits != credits for debits, credits in totals.values()):
            return False
    return True


def verify_database(dsn: str) -> DatabaseVerification:
    """Validate restored schema, ledger chain/balance, and reconciliation payloads."""
    engine = create_postgres_engine(dsn, pool_size=1)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            records = load_ledger_records(connection)
            posting_count = connection.scalar(
                select(func.count()).select_from(accounting_ledger_postings)
            )
            ledger_count = connection.scalar(
                select(func.count()).select_from(accounting_ledger_entries)
            )
            reconciliation_payloads = connection.scalars(
                select(account_reconciliation_cases.c.payload).order_by(
                    account_reconciliation_cases.c.reconciliation_case_id
                )
            ).all()
            read_model_count = connection.scalar(
                select(func.count()).select_from(read_model_records)
            )
    finally:
        engine.dispose()
    if not isinstance(revision, str):
        raise RuntimeError("restored database has no Alembic revision")
    previous = ZERO_HASH
    chain: list[str] = []
    for record in records:
        if record.previous_hash != previous:
            raise RuntimeError("ledger hash chain is broken")
        previous = record.event_hash
        chain.append(record.event_hash)
    cases = tuple(
        ReconciliationCase.model_validate_json(canonical_json_bytes(cast(object, payload)))
        for payload in reconciliation_payloads
    )
    if any(case.new_orders_allowed != (not case.differences) for case in cases):
        raise RuntimeError("reconciliation status does not match restored differences")
    balanced = _ledger_balanced(records)
    if not balanced:
        raise RuntimeError("restored ledger is not double-entry balanced")
    return DatabaseVerification(
        schema_revision=revision,
        ledger_entry_count=int(ledger_count or 0),
        ledger_posting_count=int(posting_count or 0),
        reconciliation_case_count=len(cases),
        read_model_record_count=int(read_model_count or 0),
        last_ledger_event_hash=previous,
        ledger_chain_sha256=canonical_sha256(chain),
        ledger_balanced=True,
        reconciliation_valid=True,
    )


def _encrypt(source: Path, target: Path, *, key: bytes, nonce: bytes) -> None:
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    with source.open("rb") as plain, target.open("xb") as encrypted:
        encrypted.write(MAGIC)
        encrypted.write(nonce)
        while chunk := plain.read(CHUNK_SIZE):
            encrypted.write(encryptor.update(chunk))
        encrypted.write(encryptor.finalize())
        encrypted.write(encryptor.tag)
    os.chmod(target, 0o600)


def _decrypt(source: Path, target: Path, *, key: bytes, nonce: bytes) -> None:
    with source.open("rb") as encrypted:
        header = encrypted.read(len(MAGIC) + NONCE_SIZE)
        if header != MAGIC + nonce:
            raise ValueError("backup header or nonce does not match the manifest")
        encrypted.seek(0, os.SEEK_END)
        length = encrypted.tell()
        if length <= len(MAGIC) + NONCE_SIZE + TAG_SIZE:
            raise ValueError("encrypted backup is truncated")
        encrypted.seek(-TAG_SIZE, os.SEEK_END)
        tag = encrypted.read(TAG_SIZE)
        remaining = length - len(MAGIC) - NONCE_SIZE - TAG_SIZE
        encrypted.seek(len(MAGIC) + NONCE_SIZE)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(MAGIC)
        with target.open("xb") as plain:
            while remaining:
                chunk = encrypted.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError("encrypted backup ended unexpectedly")
                remaining -= len(chunk)
                plain.write(decryptor.update(chunk))
            plain.write(decryptor.finalize())


def _safe_members(archive: tarfile.TarFile) -> tuple[tarfile.TarInfo, ...]:
    members = tuple(archive.getmembers())
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise ValueError("backup archive contains an unsafe path")
    return members


def create_encrypted_backup(
    *,
    dsn: str,
    postgres_bin: Path,
    output: Path,
    encryption_key: bytes,
    metadata_paths: Sequence[Path] = (),
) -> tuple[Path, Path, BackupManifest]:
    """Create a new AES-GCM backup without ever placing the key on disk or argv."""
    if len(encryption_key) != 32:
        raise ValueError("backup encryption key must contain exactly 32 bytes")
    output = output.resolve()
    manifest_path = output.with_suffix(output.suffix + ".json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("backup output is immutable and cannot be overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    source_verification = verify_database(dsn)
    metadata_hashes: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="aegisquant-backup-", dir=output.parent) as temporary:
        work = Path(temporary)
        dump = work / "database.dump"
        _run_postgres(
            postgres_bin / ("pg_dump.exe" if os.name == "nt" else "pg_dump"),
            ["--format=custom", "--no-owner", "--no-privileges", "--file", str(dump)],
            dsn=dsn,
            root=work,
        )
        archive_path = work / "backup.tar"
        verification_path = work / "source_verification.json"
        verification_path.write_text(
            json.dumps(asdict(source_verification), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        seen_names: set[str] = set()
        with tarfile.open(archive_path, mode="w") as archive:
            archive.add(dump, arcname="database.dump", recursive=False)
            archive.add(verification_path, arcname="source_verification.json", recursive=False)
            for path in metadata_paths:
                resolved = path.resolve()
                if not resolved.is_file() or resolved.is_symlink():
                    raise ValueError(f"backup metadata must be a regular file: {path.name}")
                if resolved.name in seen_names:
                    raise ValueError("backup metadata basenames must be unique")
                seen_names.add(resolved.name)
                metadata_hashes[resolved.name] = _sha256(resolved)
                archive.add(resolved, arcname=f"metadata/{resolved.name}", recursive=False)
        nonce = os.urandom(NONCE_SIZE)
        _encrypt(archive_path, output, key=encryption_key, nonce=nonce)
        manifest = BackupManifest(
            schema_version="aegisquant-backup-manifest-v1",
            created_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            format="postgresql-custom-in-tar",
            cipher="AES-256-GCM",
            key_id=hashlib.sha256(encryption_key).hexdigest()[:16],
            nonce_base64=base64.b64encode(nonce).decode("ascii"),
            plaintext_sha256=_sha256(archive_path),
            encrypted_sha256=_sha256(output),
            metadata_sha256=metadata_hashes,
            source_verification=source_verification,
        )
    manifest_path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.chmod(manifest_path, 0o600)
    return output, manifest_path, manifest


def restore_encrypted_backup(
    *,
    backup: Path,
    manifest_path: Path,
    encryption_key: bytes,
    postgres_bin: Path,
    target_dsn: str,
) -> RestoreResult:
    """Restore into an explicitly provided database and compare authoritative facts."""
    if len(encryption_key) != 32:
        raise ValueError("backup encryption key must contain exactly 32 bytes")
    payload = cast("dict[str, object]", json.loads(manifest_path.read_text(encoding="utf-8")))
    source_payload = cast("dict[str, object]", payload["source_verification"])
    source = DatabaseVerification(**source_payload)  # type: ignore[arg-type]
    if payload["key_id"] != hashlib.sha256(encryption_key).hexdigest()[:16]:
        raise ValueError("backup key identity does not match")
    if payload["encrypted_sha256"] != _sha256(backup):
        raise ValueError("encrypted backup hash does not match")
    nonce_value = payload["nonce_base64"]
    if not isinstance(nonce_value, str):
        raise ValueError("backup manifest nonce is invalid")
    nonce = base64.b64decode(nonce_value, validate=True)
    with tempfile.TemporaryDirectory(prefix="aegisquant-restore-", dir=backup.parent) as temporary:
        work = Path(temporary)
        archive_path = work / "backup.tar"
        _decrypt(backup, archive_path, key=encryption_key, nonce=nonce)
        if payload["plaintext_sha256"] != _sha256(archive_path):
            raise ValueError("decrypted backup hash does not match")
        with tarfile.open(archive_path, mode="r") as archive:
            members = _safe_members(archive)
            archive.extractall(work / "contents", members=members, filter="data")
        dump = work / "contents/database.dump"
        if not dump.is_file():
            raise ValueError("backup archive has no PostgreSQL dump")
        _, database = _postgres_environment(target_dsn)
        _run_postgres(
            postgres_bin / ("pg_restore.exe" if os.name == "nt" else "pg_restore"),
            [
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--dbname",
                database,
                str(dump),
            ],
            dsn=target_dsn,
            root=work,
        )
    restored = verify_database(target_dsn)
    equal = restored == source
    if not equal:
        raise RuntimeError("restored database does not match source verification")
    return RestoreResult("passed", source, restored, equal)


def replicate_encrypted_backup(
    backup: Path,
    manifest: Path,
    *,
    offsite_directory: Path,
    require_distinct_device: bool = True,
) -> tuple[Path, Path]:
    """Copy only ciphertext and its manifest to a distinct mounted filesystem."""
    source_backup = backup.resolve(strict=True)
    source_manifest = manifest.resolve(strict=True)
    destination = offsite_directory.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if destination == source_backup.parent:
        raise ValueError("offsite destination cannot be the local backup directory")
    if require_distinct_device and os.stat(destination).st_dev == os.stat(source_backup).st_dev:
        raise ValueError("offsite destination must be a distinct mounted filesystem")
    target_backup = destination / source_backup.name
    target_manifest = destination / source_manifest.name
    if target_backup.exists() or target_manifest.exists():
        raise FileExistsError("offsite backup is immutable and cannot be overwritten")
    shutil.copy2(source_backup, target_backup)
    shutil.copy2(source_manifest, target_manifest)
    if _sha256(target_backup) != _sha256(source_backup):
        raise RuntimeError("offsite ciphertext verification failed")
    if _sha256(target_manifest) != _sha256(source_manifest):
        raise RuntimeError("offsite manifest verification failed")
    return target_backup, target_manifest
