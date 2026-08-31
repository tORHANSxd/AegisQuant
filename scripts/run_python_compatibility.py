"""Run P00-P03 contracts in an isolated Python 3.14 candidate environment."""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import time
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    local_uv = root / ".tools/uv-bootstrap/Scripts/uv.exe"
    uv = shutil.which("uv") or (str(local_uv) if local_uv.is_file() else None)
    if uv is None:
        raise SystemExit("uv is required for the candidate Python contract")
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
    payload = {
        "schema_version": "1.0.0",
        "phase": "P03",
        "runtime": "Python 3.14.7 candidate",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "command": command[1:],
        "exit_code": result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "status": "passed" if result.returncode == 0 else "failed",
        "output_tail": "\n".join((result.stdout, result.stderr)).strip()[-12_000:],
    }
    output = root / "reports/phases/P03/PYTHON_314_CONTRACT.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(payload["output_tail"])
    print(f"candidate Python contract: {payload['status']}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
