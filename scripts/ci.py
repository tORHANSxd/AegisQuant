"""Run a complete phase verification pipeline and emit machine-readable evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

LEGACY_PHASE_CHOICES = (
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
)
V5_PHASE_CHOICES = (
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
)
PHASE_CHOICES = (*LEGACY_PHASE_CHOICES, *V5_PHASE_CHOICES)


@dataclass(frozen=True, slots=True)
class StageResult:
    """Bounded result for one verification command."""

    name: str
    command: list[str]
    exit_code: int
    duration_seconds: float
    output_tail: str


def resolve_pnpm_command(root: Path) -> list[str]:
    """Resolve the repository-pinned Node and pnpm entry point."""
    node = root / ".tools/node-v24.20.0-win-x64/node.exe"
    pnpm = root / ".tools/pnpm/node_modules/pnpm/bin/pnpm.cjs"
    missing = [path for path in (node, pnpm) if not path.is_file()]
    if missing:
        rendered = ", ".join(path.relative_to(root).as_posix() for path in missing)
        raise FileNotFoundError(f"required pinned web toolchain is unavailable: {rendered}")
    return [str(node), str(pnpm)]


def run_stage(
    name: str, command: list[str], root: Path, *, phase_under_verification: str
) -> StageResult:
    """Run one stage to completion and retain a bounded output tail."""
    started = time.perf_counter()
    # The executable and arguments are explicit and no shell is used.
    environment = os.environ.copy()
    if name == "pytest":
        environment["AEGISQUANT_CI_BUILDING_TEST_RESULTS"] = phase_under_verification
    result = subprocess.run(  # noqa: S603  # nosec B603
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    duration = round(time.perf_counter() - started, 3)
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    print(f"[{name}] exit={result.returncode} duration={duration:.3f}s")
    return StageResult(name, command, result.returncode, duration, output[-12_000:])


def stage_commands(root: Path, phase: str) -> list[tuple[str, list[str]]]:
    """Return the ordered P03-P18 pipeline without network soak execution."""
    pnpm = resolve_pnpm_command(root)
    legacy_phase = "P18" if phase in V5_PHASE_CHOICES else phase
    included_phases = set(LEGACY_PHASE_CHOICES[: LEGACY_PHASE_CHOICES.index(legacy_phase) + 1])
    phase_status = [
        "P00=verified",
        "P01=verified",
        "P02=verified",
        *(f"{item}=verified" for item in LEGACY_PHASE_CHOICES if item in included_phases),
    ]
    frozen_v5_manifest_stages: list[tuple[str, list[str]]] = []
    if phase in V5_PHASE_CHOICES:
        for historical_phase in V5_PHASE_CHOICES[: V5_PHASE_CHOICES.index(phase)]:
            frozen_v5_manifest_stages.append(
                (
                    f"{historical_phase.lower()}-frozen-manifest-self-consistency",
                    [
                        sys.executable,
                        "scripts/generate_artifact_manifest.py",
                        "--phase",
                        historical_phase,
                        "--check-frozen",
                    ],
                )
            )
    evidence_stages: list[tuple[str, list[str]]] = [
        (
            "p03-binance-evidence",
            [sys.executable, "scripts/generate_p03_binance_evidence.py", "--check"],
        )
    ]
    if "P04" in included_phases:
        evidence_stages.append(
            (
                "p04-multivenue-event-evidence",
                [sys.executable, "scripts/generate_p04_evidence.py", "--check"],
            )
        )
    if "P05" in included_phases:
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
    if "P06" in included_phases:
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
    if "P07" in included_phases:
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
    if "P08" in included_phases:
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
    if "P09" in included_phases:
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
    if "P10" in included_phases:
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
    if "P11" in included_phases:
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
    if "P12" in included_phases:
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
    if "P13" in included_phases:
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
    if "P14" in included_phases:
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
                )
            )
        evidence_stages.extend(
            (
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
    if "P15" in included_phases:
        evidence_stages.extend(
            (
                (
                    "p15-workbench-contracts",
                    [sys.executable, "-m", "scripts.generate_p15_contracts", "--check"],
                ),
                (
                    "p15-workbench-evidence",
                    [sys.executable, "-m", "scripts.generate_p15_evidence", "--check"],
                ),
                (
                    "p15-typescript-client-drift",
                    [sys.executable, "-m", "scripts.check_p15_client"],
                ),
                (
                    "p15-mutation",
                    [sys.executable, "-m", "scripts.run_p15_mutation", "--check"],
                ),
            )
        )
    if "P16" in included_phases:
        evidence_stages.extend(
            (
                (
                    "p16-image-lock",
                    [sys.executable, "-m", "scripts.resolve_image_digests", "--check"],
                ),
                (
                    "p16-dashboards",
                    [sys.executable, "-m", "scripts.generate_p16_dashboards", "--check"],
                ),
                (
                    "p16-operational-evidence",
                    [sys.executable, "-m", "scripts.generate_p16_evidence", "--check"],
                ),
                (
                    "p16-restore-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_p16_restore_evidence",
                        "--check",
                    ],
                ),
                (
                    "p16-mutation",
                    [sys.executable, "-m", "scripts.run_p16_mutation", "--check"],
                ),
            )
        )
    if "P17" in included_phases:
        evidence_stages.extend(
            (
                (
                    "p17-provider-evidence",
                    [sys.executable, "-m", "scripts.generate_p17_evidence", "--check"],
                ),
                (
                    "p17-mutation",
                    [sys.executable, "-m", "scripts.run_p17_mutation", "--check"],
                ),
            )
        )
    if "P18" in included_phases:
        evidence_stages.extend(
            (
                (
                    "p18-live-readiness-evidence",
                    [sys.executable, "-m", "scripts.generate_p18_evidence", "--check"],
                ),
                (
                    "p18-mutation",
                    [sys.executable, "-m", "scripts.run_p18_mutation", "--check"],
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
        *(
            [
                (
                    "v5-p01-truth-contract-evidence",
                    [sys.executable, "-m", "scripts.generate_v5_p01_evidence", "--check"],
                )
            ]
            if phase in {"V5-P01", "V5-P02"}
            else []
        ),
        *(
            [
                (
                    "v5-p02-source-provenance-evidence",
                    [sys.executable, "-m", "scripts.generate_v5_p02_evidence", "--check"],
                )
            ]
            if phase == "V5-P02"
            else []
        ),
        *(
            [
                (
                    "v5-p03-retrieval-independence-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p03_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P03"
            else []
        ),
        *(
            [
                (
                    "v5-p04-truth-council-calibration-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p04_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P04"
            else []
        ),
        *(
            [
                (
                    "v5-p05-event-canonicalization-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p05_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P05"
            else []
        ),
        *(
            [
                (
                    "v5-p06-causal-layer-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p06_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P06"
            else []
        ),
        *(
            [
                (
                    "v5-p07-forecast-council-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p07_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P07"
            else []
        ),
        *(
            [
                (
                    "v5-p08-event-forecast-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p08_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P08"
            else []
        ),
        *(
            [
                (
                    "v5-p09-forecast-governance-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p09_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P09"
            else []
        ),
        *(
            [
                (
                    "v5-p10-decision-integration-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p10_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P10"
            else []
        ),
        *(
            [
                (
                    "v5-p11-forward-proof-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p11_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P11"
            else []
        ),
        *(
            [
                (
                    "v5-p12-canary-readiness-evidence",
                    [
                        sys.executable,
                        "-m",
                        "scripts.generate_v5_p12_evidence",
                        "--check",
                    ],
                )
            ]
            if phase == "V5-P12"
            else []
        ),
        *frozen_v5_manifest_stages,
        (
            "p02-data-evidence",
            [sys.executable, "scripts/generate_p02_data_evidence.py", "--check"],
        ),
        *evidence_stages,
        ("ruff-format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("ruff-lint", [sys.executable, "-m", "ruff", "check", "."]),
        ("pyright-strict", [sys.executable, "-m", "pyright", "--project", "pyproject.toml"]),
        (
            "bandit",
            [sys.executable, "scripts/run_bandit.py"],
        ),
        ("security", [sys.executable, "scripts/security_scan.py", "--phase", legacy_phase]),
        (
            "compliance-artifacts",
            [sys.executable, "scripts/generate_compliance_artifacts.py", "--phase", legacy_phase],
        ),
        (
            "python-candidate",
            [sys.executable, "scripts/run_python_compatibility.py", "--phase", legacy_phase],
        ),
        *(
            [
                (
                    "v5-p00-evidence-reset-before-tests",
                    [sys.executable, "-m", "scripts.generate_v5_p00_evidence"],
                )
            ]
            if phase in V5_PHASE_CHOICES
            else []
        ),
        ("pytest", [sys.executable, "-m", "pytest"]),
        (
            "nautilus-compatibility",
            [sys.executable, "scripts/generate_nautilus_compatibility.py"],
        ),
        ("web-lint", [*pnpm, "--filter", "@aegisquant/web", "lint"]),
        ("web-typecheck", [*pnpm, "--filter", "@aegisquant/web", "typecheck"]),
        ("web-unit", [*pnpm, "--filter", "@aegisquant/web", "test"]),
        *(
            [
                (
                    "web-storybook",
                    [*pnpm, "--filter", "@aegisquant/web", "build-storybook"],
                )
            ]
            if "P14" in included_phases
            else []
        ),
        ("web-build", [*pnpm, "--filter", "@aegisquant/web", "build"]),
        ("web-e2e", [*pnpm, "--filter", "@aegisquant/web", "e2e"]),
        *(
            [
                (
                    "v5-p00-evidence-reset-final",
                    [sys.executable, "-m", "scripts.generate_v5_p00_evidence"],
                ),
                (
                    "v5-p00-evidence-check",
                    [sys.executable, "-m", "scripts.generate_v5_p00_evidence", "--check"],
                ),
            ]
            if phase in V5_PHASE_CHOICES
            else []
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=PHASE_CHOICES,
        default="V5-P12",
    )
    parser.add_argument(
        "--output",
        type=Path,
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    results = [
        run_stage(name, command, root, phase_under_verification=args.phase)
        for name, command in stage_commands(root, args.phase)
    ]
    passed = all(result.exit_code == 0 for result in results)
    payload = {
        "schema_version": "1.0.0",
        "phase": args.phase,
        "verification_scope": {
            "legacy_regression_through": "P18" if args.phase in V5_PHASE_CHOICES else args.phase,
            "future_v5_phase_authorization": False,
            "meaning": "legacy regression coverage is not V5 phase acceptance",
        },
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if passed else "failed",
        "stage_count": len(results),
        "passed_count": sum(result.exit_code == 0 for result in results),
        "failed_count": sum(result.exit_code != 0 for result in results),
        "results": [asdict(result) for result in results],
    }
    default_output = (
        Path(f"reports/v5/{args.phase.removeprefix('V5-')}/TEST_RESULTS.json")
        if args.phase in V5_PHASE_CHOICES
        else Path(f"reports/phases/{args.phase}/CI_RESULTS.json")
    )
    output = root / (args.output or default_output)
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
