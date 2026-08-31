"""Run Bandit and write normalized machine-readable P00 evidence."""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from pathlib import Path


def main() -> int:
    """Execute Bandit with fixed arguments and normalize its JSON report to LF."""
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "bandit",
        "-c",
        "pyproject.toml",
        "-r",
        "src",
        "scripts",
        "-f",
        "json",
    ]
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
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Bandit did not emit valid JSON: {result.stderr[-2000:]}") from error
    output = root / "reports/security/bandit.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if result.stderr:
        print(result.stderr[-4000:])
    print(f"Bandit findings: {len(payload['results'])}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
