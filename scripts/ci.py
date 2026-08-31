"""Run the complete P02 verification pipeline and emit machine-readable evidence."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StageResult:
    """Bounded result for one verification command."""

    name: str
    command: list[str]
    exit_code: int
    duration_seconds: float
    output_tail: str


def resolve_command(name: str) -> str:
    """Resolve a required executable without invoking a shell."""
    resolved = shutil.which(name)
    if resolved is None:
        raise FileNotFoundError(f"required command is unavailable: {name}")
    return resolved


def run_stage(name: str, command: list[str], root: Path) -> StageResult:
    """Run one stage to completion and retain a bounded output tail."""
    started = time.perf_counter()
    # The executable and arguments are explicit and no shell is used.
    result = subprocess.run(  # noqa: S603  # nosec B603
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
    )
    duration = round(time.perf_counter() - started, 3)
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    print(f"[{name}] exit={result.returncode} duration={duration:.3f}s")
    return StageResult(name, command, result.returncode, duration, output[-12_000:])


def stage_commands(root: Path) -> list[tuple[str, list[str]]]:
    """Return the ordered, complete P02 test pipeline."""
    pnpm = resolve_command("pnpm")
    return [
        ("postgres-runtime", [sys.executable, "scripts/setup_postgres.py"]),
        (
            "traceability",
            [
                sys.executable,
                "scripts/generate_traceability.py",
                "--phase-status",
                "P00=verified",
                "--phase-status",
                "P01=verified",
                "--phase-status",
                "P02=verified",
                "--check",
            ],
        ),
        ("schema-contracts", [sys.executable, "scripts/generate_schemas.py", "--check"]),
        (
            "p02-data-evidence",
            [sys.executable, "scripts/generate_p02_data_evidence.py", "--check"],
        ),
        ("ruff-format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("ruff-lint", [sys.executable, "-m", "ruff", "check", "."]),
        ("pyright-strict", [sys.executable, "-m", "pyright", "--project", "pyproject.toml"]),
        ("pytest", [sys.executable, "-m", "pytest"]),
        ("python-candidate", [sys.executable, "scripts/run_python_compatibility.py"]),
        (
            "nautilus-compatibility",
            [sys.executable, "scripts/generate_nautilus_compatibility.py"],
        ),
        (
            "bandit",
            [sys.executable, "scripts/run_bandit.py"],
        ),
        ("security", [sys.executable, "scripts/security_scan.py"]),
        ("compliance-artifacts", [sys.executable, "scripts/generate_compliance_artifacts.py"]),
        ("web-lint", [pnpm, "lint"]),
        ("web-typecheck", [pnpm, "typecheck"]),
        ("web-unit", [pnpm, "test"]),
        ("web-build", [pnpm, "build"]),
        ("web-e2e", [pnpm, "e2e"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/phases/P02/CI_RESULTS.json"),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    results = [run_stage(name, command, root) for name, command in stage_commands(root)]
    passed = all(result.exit_code == 0 for result in results)
    payload = {
        "schema_version": "1.0.0",
        "phase": "P02",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if passed else "failed",
        "stage_count": len(results),
        "passed_count": sum(result.exit_code == 0 for result in results),
        "failed_count": sum(result.exit_code != 0 for result in results),
        "results": [asdict(result) for result in results],
    }
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"P02 verification status: {payload['status']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
