"""Run a complete phase verification pipeline and emit machine-readable evidence."""

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


def stage_commands(root: Path, phase: str) -> list[tuple[str, list[str]]]:
    """Return the ordered P03-P14 pipeline without network soak execution."""
    pnpm = resolve_command("pnpm")
    phase_status = [
        "P00=verified",
        "P01=verified",
        "P02=verified",
        "P03=verified",
    ]
    if phase in {"P04", "P05", "P06", "P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        phase_status.append("P04=verified")
    if phase in {"P05", "P06", "P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        phase_status.append("P05=planned")
    if phase in {"P06", "P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        phase_status.append("P06=planned")
    if phase in {"P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        phase_status.append("P07=planned")
    if phase in {"P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        phase_status.append("P08=planned")
    if phase in {"P09", "P10", "P11", "P12", "P13", "P14"}:
        phase_status.append("P09=planned")
    if phase in {"P10", "P11", "P12", "P13", "P14"}:
        phase_status.append("P10=planned")
    if phase in {"P11", "P12", "P13", "P14"}:
        phase_status.append("P11=planned")
    if phase in {"P12", "P13", "P14"}:
        phase_status.append("P12=planned")
    if phase in {"P13", "P14"}:
        phase_status.append("P13=planned")
    if phase == "P14":
        phase_status.append("P14=planned")
    evidence_stages: list[tuple[str, list[str]]] = [
        (
            "p03-binance-evidence",
            [sys.executable, "scripts/generate_p03_binance_evidence.py", "--check"],
        )
    ]
    if phase in {"P04", "P05", "P06", "P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        evidence_stages.append(
            (
                "p04-multivenue-event-evidence",
                [sys.executable, "scripts/generate_p04_evidence.py", "--check"],
            )
        )
    if phase in {"P05", "P06", "P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p05-accounting-evidence",
                    [sys.executable, "scripts/generate_p05_evidence.py", "--check"],
                ),
                (
                    "p05-mutation",
                    [sys.executable, "scripts/run_p05_mutation.py"],
                ),
            )
        )
    if phase in {"P06", "P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p06-backtest-evidence",
                    [sys.executable, "-m", "scripts.generate_p06_evidence"],
                ),
                (
                    "p06-benchmark",
                    [sys.executable, "-m", "scripts.run_p06_benchmark"],
                ),
                (
                    "p06-mutation",
                    [sys.executable, "-m", "scripts.run_p06_mutation"],
                ),
            )
        )
    if phase in {"P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p07-research-evidence",
                    [sys.executable, "-m", "scripts.generate_p07_evidence", "--check"],
                ),
                (
                    "p07-mutation",
                    [sys.executable, "-m", "scripts.run_p07_mutation", "--check"],
                ),
            )
        )
    if phase in {"P08", "P09", "P10", "P11", "P12", "P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p08-research-intelligence-evidence",
                    [sys.executable, "-m", "scripts.generate_p08_evidence", "--check"],
                ),
                (
                    "p08-mutation",
                    [sys.executable, "-m", "scripts.run_p08_mutation", "--check"],
                ),
            )
        )
    if phase in {"P09", "P10", "P11", "P12", "P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p09-knowledge-intelligence-evidence",
                    [sys.executable, "-m", "scripts.generate_p09_evidence", "--check"],
                ),
                (
                    "p09-mutation",
                    [sys.executable, "-m", "scripts.run_p09_mutation", "--check"],
                ),
            )
        )
    if phase in {"P10", "P11", "P12", "P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p10-global-event-intelligence-evidence",
                    [sys.executable, "-m", "scripts.generate_p10_evidence", "--check"],
                ),
                (
                    "p10-mutation",
                    [sys.executable, "-m", "scripts.run_p10_mutation", "--check"],
                ),
            )
        )
    if phase in {"P11", "P12", "P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p11-portfolio-risk-evidence",
                    [sys.executable, "-m", "scripts.generate_p11_evidence", "--check"],
                ),
                (
                    "p11-mutation",
                    [sys.executable, "-m", "scripts.run_p11_mutation", "--check"],
                ),
            )
        )
    if phase in {"P12", "P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p12-testnet-execution-evidence",
                    [sys.executable, "-m", "scripts.generate_p12_evidence", "--check"],
                ),
                (
                    "p12-mutation",
                    [sys.executable, "-m", "scripts.run_p12_mutation", "--check"],
                ),
            )
        )
    if phase in {"P13", "P14"}:
        evidence_stages.extend(
            (
                (
                    "p13-paper-shadow-chaos-evidence",
                    [sys.executable, "-m", "scripts.generate_p13_evidence", "--check"],
                ),
                (
                    "p13-mutation",
                    [sys.executable, "-m", "scripts.run_p13_mutation", "--check"],
                ),
            )
        )
    if phase == "P14":
        evidence_stages.extend(
            (
                (
                    "p14-read-api-web-contracts",
                    [sys.executable, "-m", "scripts.generate_p14_contracts", "--check"],
                ),
                (
                    "p14-read-api-web-evidence",
                    [sys.executable, "-m", "scripts.generate_p14_evidence", "--check"],
                ),
                (
                    "p14-typescript-client-drift",
                    [sys.executable, "-m", "scripts.check_p14_client"],
                ),
                (
                    "p14-mutation",
                    [sys.executable, "-m", "scripts.run_p14_mutation", "--check"],
                ),
            )
        )
    return [
        ("postgres-runtime", [sys.executable, "scripts/setup_postgres.py"]),
        (
            "traceability",
            [
                sys.executable,
                "scripts/generate_traceability.py",
                *[item for status in phase_status for item in ("--phase-status", status)],
                "--check",
            ],
        ),
        ("schema-contracts", [sys.executable, "scripts/generate_schemas.py", "--check"]),
        (
            "p02-data-evidence",
            [sys.executable, "scripts/generate_p02_data_evidence.py", "--check"],
        ),
        *evidence_stages,
        ("ruff-format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("ruff-lint", [sys.executable, "-m", "ruff", "check", "."]),
        ("pyright-strict", [sys.executable, "-m", "pyright", "--project", "pyproject.toml"]),
        ("pytest", [sys.executable, "-m", "pytest"]),
        (
            "python-candidate",
            [sys.executable, "scripts/run_python_compatibility.py", "--phase", phase],
        ),
        (
            "nautilus-compatibility",
            [sys.executable, "scripts/generate_nautilus_compatibility.py"],
        ),
        (
            "bandit",
            [sys.executable, "scripts/run_bandit.py"],
        ),
        ("security", [sys.executable, "scripts/security_scan.py", "--phase", phase]),
        (
            "compliance-artifacts",
            [sys.executable, "scripts/generate_compliance_artifacts.py", "--phase", phase],
        ),
        ("web-lint", [pnpm, "lint"]),
        ("web-typecheck", [pnpm, "typecheck"]),
        ("web-unit", [pnpm, "test"]),
        *(
            [("web-storybook", [pnpm, "--filter", "@aegisquant/web", "build-storybook"])]
            if phase == "P14"
            else []
        ),
        ("web-build", [pnpm, "build"]),
        ("web-e2e", [pnpm, "e2e"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=(
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
        ),
        default="P14",
    )
    parser.add_argument(
        "--output",
        type=Path,
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    results = [run_stage(name, command, root) for name, command in stage_commands(root, args.phase)]
    passed = all(result.exit_code == 0 for result in results)
    payload = {
        "schema_version": "1.0.0",
        "phase": args.phase,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if passed else "failed",
        "stage_count": len(results),
        "passed_count": sum(result.exit_code == 0 for result in results),
        "failed_count": sum(result.exit_code != 0 for result in results),
        "results": [asdict(result) for result in results],
    }
    output = root / (args.output or Path(f"reports/phases/{args.phase}/CI_RESULTS.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{args.phase} verification status: {payload['status']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
