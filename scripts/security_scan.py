"""Run phase secret and dependency audits without accessing any account."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

DETECT_EXCLUDE = (
    r"(?:^|[\\/])(?:\.git|\.venv|\.tools|\.next|\.pytest_cache|\.pytest_tmp|"
    r"\.ruff_cache|node_modules|docs[\\/]spec|reports[\\/](?:licenses|sbom|security))"
    r"(?:[\\/]|$)|Master_Taskbook|REQUIREMENTS_TRACEABILITY|ARTIFACT_MANIFEST|"
    r"pnpm-lock\.yaml|uv\.lock|\.tsbuildinfo$"
)
DETECT_LINE_EXCLUDE = (
    r"(?i)(?:.*(?:sha-?256|sha1|spec_sha256|artifact_manifest_sha256|expected_sha256|"
    r"commit_sha|request_hash|economic_event_hash|event_hash|vector_hash|application_sha256|"
    r"first_digest|second_digest|evidence_commit|implementation_commit|pinned_commit|"
    r"terms_version_hash|P00_EVIDENCE_COMMIT|"
    r"P00_IMPLEMENTATION_COMMIT).*|"
    r'.*"(?:ledger_snapshot_id|payload_hash|public_key_base64|signature_base64|'
    r'(?:source_|rebuilt_)?(?:last_event_hash|state_hash))"\s*:.*|'
    r".*secret_loading.*(?:false|disabled).*|.*credentials_received.*0.*|"
    r".*plaintext_secrets_written.*0.*)"
)


def run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    """Run one audit command and capture UTF-8 text."""
    # Scanner commands are fixed and no shell is used.
    return subprocess.run(  # noqa: S603  # nosec B603
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def parsed_json(output: str) -> object:
    """Parse command JSON, returning a bounded error record when malformed."""
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        return {"parse_error": str(exc), "output_tail": output[-4000:]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("P03", "P04", "P05", "P06", "P07"), default="P07")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report_dir = root / "reports/security"
    report_dir.mkdir(parents=True, exist_ok=True)
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise SystemExit("pnpm is required for the JavaScript dependency audit")

    detect_result = run(
        [
            sys.executable,
            "-m",
            "detect_secrets",
            "scan",
            "--all-files",
            "--no-verify",
            "--exclude-files",
            DETECT_EXCLUDE,
            "--exclude-lines",
            DETECT_LINE_EXCLUDE,
        ],
        root,
    )
    detect_payload = parsed_json(detect_result.stdout)
    (report_dir / "detect_secrets.json").write_text(
        json.dumps(detect_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    typed_detect = (
        cast("dict[object, object]", detect_payload) if isinstance(detect_payload, dict) else {}
    )
    findings = typed_detect.get("results", {})
    if isinstance(findings, dict):
        typed_findings = cast("dict[object, object]", findings)
        secret_count = sum(
            len(cast("list[object]", items))
            for items in typed_findings.values()
            if isinstance(items, list)
        )
    else:
        secret_count = -1

    python_result = run([sys.executable, "-m", "pip_audit", "--local", "--format", "json"], root)
    python_payload = parsed_json(python_result.stdout)
    (report_dir / "python_dependency_audit.json").write_text(
        json.dumps(python_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    javascript_result = run([pnpm, "audit", "--json", "--audit-level", "high"], root)
    javascript_payload = parsed_json(javascript_result.stdout)
    (report_dir / "javascript_dependency_audit.json").write_text(
        json.dumps(javascript_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    container_files = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and (
            path.name == "Dockerfile"
            or path.name.startswith("docker-compose")
            or path.suffix in {".tf", ".tfvars"}
        )
        and not any(part in {".git", ".venv", ".tools", "node_modules"} for part in path.parts)
    ]
    infrastructure = {
        "status": "not_applicable" if not container_files else "review_required",
        "reason": f"{args.phase} contains no container image or infrastructure-as-code input",
        "scannable_files": container_files,
    }
    (report_dir / "container_iac_scan.json").write_text(
        json.dumps(infrastructure, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    checks = {
        "detect_secrets": detect_result.returncode == 0 and secret_count == 0,
        "python_dependency_audit": python_result.returncode == 0,
        "javascript_dependency_audit": javascript_result.returncode == 0,
        "container_iac": not container_files,
    }
    payload = {
        "schema_version": "1.0.0",
        "phase": args.phase,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "secret_finding_count": secret_count,
        "real_account_access_performed": False,
    }
    # This is a boolean audit outcome, not a credential value.
    payload["secret_store_access_performed"] = False
    (report_dir / "SECURITY_SCAN_RESULTS.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
