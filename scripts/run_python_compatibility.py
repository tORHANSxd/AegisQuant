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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("P03", "P04", "P05", "P06", "P07", "P08"), default="P08"
    )
    args = parser.parse_args()
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
    if args.phase in {"P04", "P05", "P06", "P07", "P08"}:
        test_targets.extend(("tests/replay/intelligence", "tests/p04"))
    if args.phase in {"P05", "P06", "P07", "P08"}:
        test_targets.extend(("tests/p05", "tests/mutation"))
    if args.phase in {"P06", "P07", "P08"}:
        test_targets.append("tests/p06")
    if args.phase in {"P07", "P08"}:
        test_targets.extend(("tests/research", "tests/p07"))
    if args.phase == "P08":
        test_targets.append("tests/p08")
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
