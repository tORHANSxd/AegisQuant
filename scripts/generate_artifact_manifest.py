"""Generate or verify a phase artifact manifest without self-referential hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

DEFAULT_PHASE: Final = "P18"
STATE_PATH: Final = "state/PROJECT_PHASE_STATE.yaml"
COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")


def run_git(root: Path, arguments: list[str]) -> bytes:
    """Run one fixed Git query and return its raw output."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to build the artifact manifest")
    # The executable is resolved, arguments are fixed by this module, and no shell is used.
    result = subprocess.run(  # noqa: S603  # nosec B603
        [git, *arguments],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout


def repository_paths(root: Path, excluded_paths: frozenset[str]) -> list[Path]:
    """Return tracked and non-ignored untracked files in stable order."""
    raw = run_git(
        root,
        [
            "-c",
            "core.quotepath=false",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
    )
    paths = {
        Path(item.decode("utf-8"))
        for item in raw.split(b"\0")
        if item and item.decode("utf-8") not in excluded_paths
    }
    missing = sorted(path.as_posix() for path in paths if not (root / path).is_file())
    if missing:
        raise RuntimeError(f"manifest inputs are not regular files: {missing}")
    return sorted(paths, key=lambda path: path.as_posix())


def category_for(path: Path) -> str:
    """Map a repository path to a compact evidence category."""
    return {
        "apps": "frontend",
        "configs": "configuration",
        "docs": "governance",
        "knowledge": "intelligence_governance",
        "reports": "evidence",
        "schemas": "contract",
        "scripts": "automation",
        "src": "implementation",
        "state": "project_state",
        "tests": "verification",
    }.get(path.parts[0], "repository_baseline")


def file_entry(root: Path, path: Path) -> dict[str, object]:
    """Hash one manifest input exactly as stored in the workspace."""
    raw = (root / path).read_bytes()
    return {
        "path": path.as_posix(),
        "category": category_for(path),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def verify_commit(root: Path, commit_sha: str) -> None:
    """Require a full, locally resolvable implementation commit."""
    if COMMIT_RE.fullmatch(commit_sha) is None:
        raise RuntimeError("implementation commit must be a full 40-character SHA")
    run_git(root, ["cat-file", "-e", f"{commit_sha}^{{commit}}"])


def generate(root: Path, output: Path, commit_sha: str, phase: str) -> None:
    """Write the manifest using normalized LF endings."""
    verify_commit(root, commit_sha)
    excluded_paths = frozenset({output.relative_to(root).as_posix(), STATE_PATH})
    entries = [file_entry(root, path) for path in repository_paths(root, excluded_paths)]
    payload = {
        "schema_version": "1.0.0",
        "phase": phase,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "implementation_commit": commit_sha,
        "hash_algorithm": "SHA-256",
        "artifact_count": len(entries),
        "excluded_from_hash_set": {
            output.relative_to(root).as_posix(): "self-reference",
            STATE_PATH: "contains this manifest's SHA-256",
        },
        "artifacts": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(entries)} artifacts to {output}")


def check(root: Path, output: Path, phase: str) -> None:
    """Verify every declared path, size, hash, exclusion, and commit reference."""
    payload = json.loads(output.read_text(encoding="utf-8"))
    commit_sha = payload["implementation_commit"]
    if not isinstance(commit_sha, str):
        raise RuntimeError("manifest implementation_commit is invalid")
    verify_commit(root, commit_sha)
    excluded_paths = frozenset({output.relative_to(root).as_posix(), STATE_PATH})
    actual_entries = [file_entry(root, path) for path in repository_paths(root, excluded_paths)]
    if payload.get("phase") != phase or payload.get("hash_algorithm") != "SHA-256":
        raise RuntimeError("manifest metadata is invalid")
    if payload.get("artifact_count") != len(actual_entries):
        raise RuntimeError("manifest artifact_count is stale")
    if payload.get("artifacts") != actual_entries:
        raise RuntimeError("manifest paths or hashes are stale")
    print(f"verified {len(actual_entries)} artifacts in {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        default=DEFAULT_PHASE,
        choices=(
            "P00",
            "P01",
            "P02",
            "P03",
            "P04",
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
            "P12",
            "P13",
            "P14",
            "P15",
            "P16",
            "P17",
            "P18",
        ),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--implementation-commit")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_path = args.output or Path(f"reports/phases/{args.phase}/ARTIFACT_MANIFEST.json")
    output = root / output_path
    if args.check:
        check(root, output, args.phase)
        return 0
    if args.implementation_commit is None:
        raise SystemExit("--implementation-commit is required when generating")
    generate(root, output, args.implementation_commit, args.phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
