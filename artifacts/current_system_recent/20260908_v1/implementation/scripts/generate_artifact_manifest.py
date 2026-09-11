"""Generate or verify a phase artifact manifest without self-referential hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final, cast

import yaml

DEFAULT_PHASE: Final = "V5-P12"
STATE_PATHS: Final = frozenset({"state/PROJECT_PHASE_STATE.yaml", "state/V5_PROJECT_STATE.yaml"})
COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}")
SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")


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


def artifact_set_sha256(entries: list[dict[str, object]]) -> str:
    """Bind the ordered workspace snapshot independently of the baseline commit."""

    raw = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def generate(root: Path, output: Path, commit_sha: str, phase: str) -> None:
    """Write the manifest using normalized LF endings."""
    verify_commit(root, commit_sha)
    excluded_paths = frozenset({output.relative_to(root).as_posix(), *STATE_PATHS})
    entries = [file_entry(root, path) for path in repository_paths(root, excluded_paths)]
    payload = {
        "schema_version": "1.0.0",
        "phase": phase,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "implementation_commit": commit_sha,
        "implementation_commit_role": "SOURCE_REPOSITORY_BASELINE_ONLY",
        "workspace_snapshot": {
            "kind": "CONTENT_ADDRESSED_WORKTREE",
            "artifact_set_sha256": artifact_set_sha256(entries),
            "commit_alone_reconstructs_snapshot": False,
        },
        "hash_algorithm": "SHA-256",
        "artifact_count": len(entries),
        "excluded_from_hash_set": {
            output.relative_to(root).as_posix(): "self-reference",
            **{path: "may contain this manifest's SHA-256" for path in sorted(STATE_PATHS)},
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
    payload_object: object = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(payload_object, dict):
        raise RuntimeError("manifest root is invalid")
    payload = cast("dict[str, object]", payload_object)
    commit_sha = payload["implementation_commit"]
    if not isinstance(commit_sha, str):
        raise RuntimeError("manifest implementation_commit is invalid")
    verify_commit(root, commit_sha)
    excluded_paths = frozenset({output.relative_to(root).as_posix(), *STATE_PATHS})
    actual_entries = [file_entry(root, path) for path in repository_paths(root, excluded_paths)]
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("phase") != phase
        or payload.get("hash_algorithm") != "SHA-256"
    ):
        raise RuntimeError("manifest metadata is invalid")
    if payload.get("implementation_commit_role") != "SOURCE_REPOSITORY_BASELINE_ONLY":
        raise RuntimeError("manifest commit role is invalid")
    expected_exclusions = {
        output.relative_to(root).as_posix(): "self-reference",
        **{path: "may contain this manifest's SHA-256" for path in sorted(STATE_PATHS)},
    }
    if payload.get("excluded_from_hash_set") != expected_exclusions:
        raise RuntimeError("manifest exclusion metadata is invalid")
    expected_snapshot = {
        "kind": "CONTENT_ADDRESSED_WORKTREE",
        "artifact_set_sha256": artifact_set_sha256(actual_entries),
        "commit_alone_reconstructs_snapshot": False,
    }
    if payload.get("workspace_snapshot") != expected_snapshot:
        raise RuntimeError("manifest workspace snapshot binding is stale")
    if payload.get("artifact_count") != len(actual_entries):
        raise RuntimeError("manifest artifact_count is stale")
    if payload.get("artifacts") != actual_entries:
        raise RuntimeError("manifest paths or hashes are stale")
    print(f"verified {len(actual_entries)} artifacts in {output}")


def check_frozen(root: Path, output: Path, phase: str) -> None:
    """Validate a historical manifest's own hash commitments without comparing today's tree."""

    payload_object: object = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(payload_object, dict):
        raise RuntimeError("frozen manifest root is invalid")
    payload = cast("dict[str, object]", payload_object)
    commit_sha = payload.get("implementation_commit")
    if not isinstance(commit_sha, str):
        raise RuntimeError("frozen manifest implementation_commit is invalid")
    verify_commit(root, commit_sha)
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("phase") != phase
        or payload.get("hash_algorithm") != "SHA-256"
    ):
        raise RuntimeError("frozen manifest metadata is invalid")
    raw_entries_object = payload.get("artifacts")
    if not isinstance(raw_entries_object, list):
        raise RuntimeError("frozen manifest artifacts are invalid")
    raw_entries = cast("list[object]", raw_entries_object)
    entries: list[dict[str, object]] = []
    paths: list[str] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise RuntimeError("frozen manifest artifact entry is invalid")
        entry = cast("dict[str, object]", raw_entry)
        path = entry.get("path")
        category = entry.get("category")
        size_bytes = entry.get("size_bytes")
        sha256 = entry.get("sha256")
        if (
            set(entry) != {"path", "category", "size_bytes", "sha256"}
            or not isinstance(path, str)
            or not path
            or "\\" in path
            or PurePosixPath(path).is_absolute()
            or PurePosixPath(path).as_posix() != path
            or ".." in PurePosixPath(path).parts
            or not isinstance(category, str)
            or not category
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
            or not isinstance(sha256, str)
            or SHA256_RE.fullmatch(sha256) is None
        ):
            raise RuntimeError("frozen manifest artifact entry is invalid")
        paths.append(path)
        entries.append(entry)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise RuntimeError("frozen manifest artifact paths are not unique and ordered")
    if payload.get("artifact_count") != len(entries):
        raise RuntimeError("frozen manifest artifact_count is invalid")
    expected_exclusions = {
        output.relative_to(root).as_posix(): "self-reference",
        **{path: "may contain this manifest's SHA-256" for path in sorted(STATE_PATHS)},
    }
    if payload.get("excluded_from_hash_set") != expected_exclusions:
        raise RuntimeError("frozen manifest exclusion metadata is invalid")
    snapshot = payload.get("workspace_snapshot")
    if snapshot is None:
        if phase != "V5-P00" or payload.get("implementation_commit_role") is not None:
            raise RuntimeError("legacy frozen manifest metadata is invalid")
    else:
        expected_snapshot = {
            "kind": "CONTENT_ADDRESSED_WORKTREE",
            "artifact_set_sha256": artifact_set_sha256(entries),
            "commit_alone_reconstructs_snapshot": False,
        }
        if (
            payload.get("implementation_commit_role") != "SOURCE_REPOSITORY_BASELINE_ONLY"
            or snapshot != expected_snapshot
        ):
            raise RuntimeError("frozen manifest artifact-set commitment is invalid")
    if phase.startswith("V5-"):
        state_object: object = yaml.safe_load(
            (root / "state/V5_PROJECT_STATE.yaml").read_text(encoding="utf-8")
        )
        if not isinstance(state_object, dict):
            raise RuntimeError("V5 project state is invalid")
        state = cast("dict[str, object]", state_object)
        history_object = state.get("phase_history")
        if not isinstance(history_object, list):
            raise RuntimeError("V5 phase history is invalid")
        records: list[dict[str, object]] = []
        for item in cast("list[object]", history_object):
            if not isinstance(item, dict):
                continue
            record = cast("dict[str, object]", item)
            if record.get("phase") == phase:
                records.append(record)
        if len(records) != 1:
            raise RuntimeError("frozen V5 manifest is not uniquely bound in project state")
        record = records[0]
        expected_path = output.relative_to(root).as_posix()
        expected_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
        if (
            record.get("artifact_manifest_path") != expected_path
            or record.get("artifact_manifest_sha256") != expected_sha256
        ):
            raise RuntimeError("frozen V5 manifest differs from project-state commitment")
    print(f"verified {len(entries)} frozen artifact commitments in {output}")


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
            "V5-P00",
            "V5-P01",
            "V5-P02",
            "V5-P03",
            "V5-P04",
            "V5-P05",
            "V5-P06",
            "V5-P07",
            "V5-P08",
            "V5-P09",
            "V5-P10",
            "V5-P11",
            "V5-P12",
        ),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--implementation-commit")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-frozen", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    default_output = (
        Path(f"reports/v5/{args.phase.removeprefix('V5-')}/ARTIFACT_MANIFEST.json")
        if args.phase
        in {
            "V5-P00",
            "V5-P01",
            "V5-P02",
            "V5-P03",
            "V5-P04",
            "V5-P05",
            "V5-P06",
            "V5-P07",
            "V5-P08",
            "V5-P09",
            "V5-P10",
            "V5-P11",
            "V5-P12",
        }
        else Path(f"reports/phases/{args.phase}/ARTIFACT_MANIFEST.json")
    )
    output_path = args.output or default_output
    output = root / output_path
    if args.check and args.check_frozen:
        raise SystemExit("--check and --check-frozen are mutually exclusive")
    if args.check_frozen:
        check_frozen(root, output, args.phase)
        return 0
    if args.check:
        check(root, output, args.phase)
        return 0
    if args.implementation_commit is None:
        raise SystemExit("--implementation-commit is required when generating")
    generate(root, output, args.implementation_commit, args.phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
