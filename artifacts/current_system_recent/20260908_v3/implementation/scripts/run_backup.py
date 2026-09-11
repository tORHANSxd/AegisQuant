"""Create and replicate one encrypted operational backup from systemd credentials."""

from __future__ import annotations

import argparse
import base64
import os
from datetime import UTC, datetime
from pathlib import Path

from aegisquant.operations.backup import create_encrypted_backup, replicate_encrypted_backup


def _credential(name: str) -> bytes:
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if directory is None:
        raise RuntimeError("systemd CREDENTIALS_DIRECTORY is required")
    path = (Path(directory) / name).resolve(strict=True)
    if path.parent != Path(directory).resolve(strict=True) or not path.is_file():
        raise RuntimeError(f"required systemd credential is missing: {name}")
    return path.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--offsite-dir", type=Path, required=True)
    arguments = parser.parse_args()
    dsn = _credential("database_dsn").decode("utf-8").strip()
    encoded_key = _credential("backup_key_base64").strip()
    key = base64.b64decode(encoded_key, validate=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = arguments.output_dir / f"aegisquant-{timestamp}.aqbk"
    root = Path(__file__).resolve().parents[1]
    backup, manifest, _ = create_encrypted_backup(
        dsn=dsn,
        postgres_bin=arguments.postgres_bin,
        output=output,
        encryption_key=key,
        metadata_paths=(
            root / "state/PROJECT_PHASE_STATE.yaml",
            root / "infra/compose/IMAGE_LOCK.json",
        ),
    )
    replicate_encrypted_backup(
        backup,
        manifest,
        offsite_directory=arguments.offsite_dir,
        require_distinct_device=True,
    )
    print(f"encrypted backup and offsite copy verified: {backup.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
