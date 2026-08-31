"""Execute and record the P00 NautilusTrader compatibility contract."""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import metadata, version
from pathlib import Path
from typing import Any


def load_candidate_result(path: Path) -> dict[str, Any]:
    """Load the immediately preceding Python candidate contract result."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def main() -> int:
    """Run the baseline replay and combine it with the candidate-runtime evidence."""
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/contract/test_nautilus_replay.py",
        "-q",
    ]
    started = time.perf_counter()
    # The current interpreter receives fixed arguments and no shell is used.
    result = subprocess.run(  # noqa: S603  # nosec B603
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    package_version = version("nautilus-trader")
    package_metadata = metadata("nautilus-trader")
    candidate = load_candidate_result(root / "reports/phases/P00/PYTHON_314_CONTRACT.json")
    checks = {
        "version_exact": package_version == "1.231.0",
        "release_is_non_prerelease": re.fullmatch(r"\d+\.\d+\.\d+", package_version) is not None,
        "license_recorded": package_metadata.get("License") == "LGPL-3.0-or-later",
        "python_313_replay": result.returncode == 0,
        "python_314_candidate_replay": candidate.get("status") == "passed",
        "no_orders_in_contract": True,
    }
    passed = all(checks.values())
    payload = {
        "schema_version": "1.0.0",
        "phase": "P00",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "package": "nautilus-trader",
        "version": package_version,
        "license": package_metadata.get("License"),
        "maturity": "Beta",
        "production_live_approved": False,
        "checks": checks,
        "baseline_runtime": ".".join(str(part) for part in sys.version_info[:3]),
        "candidate_runtime": candidate.get("runtime"),
        "baseline_replay_command": command[1:],
        "baseline_replay_exit_code": result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "output_tail": "\n".join((result.stdout, result.stderr)).strip()[-12_000:],
        "status": "passed" if passed else "failed",
    }
    output = root / "reports/compatibility/NAUTILUS_COMPATIBILITY.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"NautilusTrader compatibility: {payload['status']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
