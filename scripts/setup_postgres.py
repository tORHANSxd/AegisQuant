"""Provision the pinned project-local PostgreSQL test binary on Windows."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Final

POSTGRES_VERSION: Final = "18.6"
ARCHIVE_NAME: Final = "postgresql-18.6-1-windows-x64-binaries.zip"
ARCHIVE_URL: Final = f"https://get.enterprisedb.com/postgresql/{ARCHIVE_NAME}"
ARCHIVE_SHA256: Final = "fbe23da234ee31547bf8a36d29dfd81e82b849df2d2b78d2eecb43d360252f8c"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    if url != ARCHIVE_URL or not url.startswith("https://"):
        raise ValueError("only the pinned HTTPS PostgreSQL archive URL is allowed")
    partial = target.with_suffix(".partial")
    request = urllib.request.Request(  # noqa: S310  # nosec B310 - pinned HTTPS URL
        url, headers={"User-Agent": "AegisQuant-P01-bootstrap"}
    )
    with (
        urllib.request.urlopen(  # noqa: S310  # nosec B310 - pinned HTTPS request
            request, timeout=60
        ) as response,
        partial.open("wb") as output,
    ):
        shutil.copyfileobj(response, output, length=1024 * 1024)
    partial.replace(target)


def safe_extract(archive: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (destination / member.filename).resolve()
            if destination_resolved not in target.parents and target != destination_resolved:
                raise RuntimeError(f"unsafe archive member: {member.filename}")
        package.extractall(destination)


def ensure_postgres(root: Path, *, allow_download: bool) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("the pinned EDB binary contract is Windows-only")
    tools = root / ".tools"
    archive = tools / ARCHIVE_NAME
    destination = tools / f"postgresql-{POSTGRES_VERSION}"
    executable = destination / "pgsql/bin/pg_ctl.exe"
    tools.mkdir(parents=True, exist_ok=True)
    if executable.is_file():
        return executable.parent
    if not archive.is_file():
        if not allow_download:
            raise RuntimeError(f"missing PostgreSQL archive: {archive}")
        download(ARCHIVE_URL, archive)
    actual_hash = sha256(archive)
    if actual_hash != ARCHIVE_SHA256:
        raise RuntimeError(f"PostgreSQL archive SHA-256 mismatch: {actual_hash}")
    safe_extract(archive, destination)
    if not executable.is_file():
        raise RuntimeError("PostgreSQL archive did not contain pg_ctl.exe")
    return executable.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="do not download a missing archive")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    bin_dir = ensure_postgres(root, allow_download=not args.check)
    payload = {
        "version": POSTGRES_VERSION,
        "archive_url": ARCHIVE_URL,
        "archive_sha256": ARCHIVE_SHA256,
        "bin_dir": str(bin_dir),
        "status": "ready",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
