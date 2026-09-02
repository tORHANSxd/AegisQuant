"""Run phase contracts in an isolated Python 3.14 candidate environment."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PHASE_CHOICES = (
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
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=PHASE_CHOICES,
        default="P16",
    )
    args = parser.parse_args()
    included_phases = set(PHASE_CHOICES[: PHASE_CHOICES.index(args.phase) + 1])
    root = Path(__file__).resolve().parents[1]
    local_uv = root / ".tools/uv-bootstrap/Scripts/uv.exe"
    uv = shutil.which("uv") or (str(local_uv) if local_uv.is_file() else None)
    if uv is None:
        raise SystemExit("uv is required for the candidate Python contract")
    test_targets = [
        "tests/architecture",
        "tests/unit",
        "tests/property",
        "tests/contract",
        "tests/p02",
        "tests/p03",
        "tests/chaos",
        "tests/performance",
        "tests/security",
    ]
    if "P04" in included_phases:
        test_targets.extend(("tests/replay/intelligence", "tests/p04"))
    if "P05" in included_phases:
        test_targets.extend(("tests/p05", "tests/mutation"))
    if "P06" in included_phases:
        test_targets.append("tests/p06")
    if "P07" in included_phases:
        test_targets.extend(("tests/research", "tests/p07"))
    if "P08" in included_phases:
        test_targets.append("tests/p08")
    if "P09" in included_phases:
        test_targets.extend(("tests/intelligence", "tests/p09"))
    if "P10" in included_phases:
        test_targets.append("tests/p10")
    if "P11" in included_phases:
        test_targets.extend(("tests/portfolio", "tests/risk", "tests/p11"))
    if "P12" in included_phases:
        test_targets.extend(
            (
                "tests/execution",
                "tests/integration/test_p12_execution_e2e.py",
                "tests/p12",
            )
        )
    if "P13" in included_phases:
        test_targets.extend(
            (
                "tests/runtime",
                "tests/replay/test_p13_historical_runtime.py",
                "tests/integration/test_p13_runtime_e2e.py",
                "tests/p13",
            )
        )
    if "P14" in included_phases:
        test_targets.extend(
            (
                "tests/readmodels",
                "tests/integration/test_p14_dashboard_flow.py",
                "tests/integration/test_p14_readmodels.py",
                "tests/p14",
            )
        )
    if "P15" in included_phases:
        test_targets.extend(
            (
                "tests/integration/test_p15_workbench.py",
                "tests/p15",
            )
        )
    if "P16" in included_phases:
        test_targets.extend(
            (
                "tests/observability",
                "tests/operations",
                "tests/p16",
            )
        )
    command = [
        uv,
        "run",
        "--isolated",
        "--python",
        "3.14.7",
        "--all-groups",
        "--frozen",
        "python",
        "-m",
        "pytest",
        *test_targets,
    ]
    started = time.perf_counter()
    # uv is resolved before use and receives fixed arguments.
    result = subprocess.run(  # noqa: S603  # nosec B603
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_tail = "\n".join((result.stdout, result.stderr)).strip()[-12_000:]
    payload = {
        "schema_version": "1.0.0",
        "phase": args.phase,
        "runtime": "Python 3.14.7 candidate",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "command": command[1:],
        "exit_code": result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "status": "passed" if result.returncode == 0 else "failed",
        "output_tail": output_tail,
    }
    output = root / f"reports/phases/{args.phase}/PYTHON_314_CONTRACT.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    console_encoding = sys.stdout.encoding or "utf-8"
    console_tail = output_tail.encode(console_encoding, errors="backslashreplace").decode(
        console_encoding
    )
    print(console_tail)
    print(f"candidate Python contract: {payload['status']}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
