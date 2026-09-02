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

import yaml

DETECT_EXCLUDE = (
    r"(?:^|[\\/])(?:\.git|\.venv|\.tools|\.next|\.pytest_cache|\.pytest_tmp|\.runtime|"
    r"\.ruff_cache|node_modules|storybook-static|apps[\\/]web[\\/]src[\\/]generated|"
    r"docs[\\/]spec|reports[\\/](?:licenses|sbom|security))"
    r"(?:[\\/]|$)|Master_Taskbook|REQUIREMENTS_TRACEABILITY|ARTIFACT_MANIFEST|"
    r"pnpm-lock\.yaml|uv\.lock|\.tsbuildinfo$"
)
DETECT_LINE_EXCLUDE = (
    r"(?i)(?:.*(?:sha-?256|sha1|spec_sha256|artifact_manifest_sha256|expected_sha256|"
    r"commit_sha|request_hash|economic_event_hash|event_hash|vector_hash|application_sha256|"
    r"dataset_manifest_hash|feature_snapshot_hash|snapshot_hash|source_hash|"
    r"first_digest|second_digest|evidence_commit|implementation_commit|pinned_commit|"
    r"terms_version_hash|P00_EVIDENCE_COMMIT|"
    r"P00_IMPLEMENTATION_COMMIT).*|"
    r".*detect_secrets.*passed_zero_findings.*|"
    r'.*"(?:ledger_snapshot_id|payload_hash|idempotency_key|order_intent_id|risk_decision_id|'
    r"public_key_base64|signature_base64|"
    r"public_key_hex|signature_hex|"
    r'(?:source_|rebuilt_)?(?:last_event_hash|state_hash))"\s*:.*|'
    r'.*"revision"\s*:.*|.*revision\s*=.*|'
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


def resolve_pnpm_command(root: Path) -> list[str]:
    """Use the repository-pinned Node and pnpm rather than the ambient host tools."""
    node = root / ".tools/node-v24.20.0-win-x64/node.exe"
    pnpm = root / ".tools/pnpm/node_modules/pnpm/bin/pnpm.cjs"
    if not node.is_file() or not pnpm.is_file():
        raise FileNotFoundError("repository-pinned Node/pnpm toolchain is unavailable")
    return [str(node), str(pnpm)]


def infrastructure_policy(root: Path) -> tuple[dict[str, object], bool]:
    """Statically enforce the production container/IaC security boundary."""
    infrastructure_root = root / "infra"
    scannable = [
        path
        for path in infrastructure_root.rglob("*")
        if path.is_file()
        and (path.name.startswith("Dockerfile") or path.suffix in {".yml", ".yaml", ".alloy"})
    ]
    findings: list[str] = []
    dockerfiles = [path for path in scannable if path.name.startswith("Dockerfile")]
    for path in dockerfiles:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("FROM ") and "@sha256:" not in line:
                findings.append(f"unpinned base image: {path.relative_to(root).as_posix()}")
    compose_path = root / "infra/compose/compose.yaml"
    if not compose_path.is_file():
        findings.append("production compose file is missing")
    else:
        compose_text = compose_path.read_text(encoding="utf-8")
        payload = cast("dict[str, object]", yaml.safe_load(compose_text))
        services = payload.get("services")
        if not isinstance(services, dict):
            findings.append("compose services mapping is invalid")
        else:
            for name, raw in cast("dict[object, object]", services).items():
                if not isinstance(raw, dict):
                    findings.append(f"compose service is invalid: {name}")
                    continue
                service = cast("dict[str, object]", raw)
                image = service.get("image")
                if isinstance(image, str) and "@sha256:" not in image and "DIGEST" not in image:
                    findings.append(f"service image is not digest-bound: {name}")
                if service.get("privileged") is True or service.get("network_mode") == "host":
                    findings.append(f"service has an unsafe privilege boundary: {name}")
                volumes = service.get("volumes", [])
                if isinstance(volumes, list) and any(
                    "docker.sock" in str(item) for item in cast("list[object]", volumes)
                ):
                    findings.append(f"service mounts docker.sock: {name}")
                ports = service.get("ports", [])
                if isinstance(ports, list):
                    for port in cast("list[object]", ports):
                        if not str(port).startswith("127.0.0.1:"):
                            findings.append(f"service publishes a non-loopback port: {name}")
        if ":latest" in compose_text.casefold():
            findings.append("compose contains a latest image tag")
    infra_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in scannable
        if path.stat().st_size <= 2_000_000
    ).casefold()
    if "promtail" in infra_text:
        findings.append("Promtail is prohibited")
    docker_available = shutil.which("docker") is not None
    payload: dict[str, object] = {
        "status": "passed" if not findings else "failed",
        "policy": "digest-pinned, loopback-only, least-privilege, no-Promtail",
        "scannable_files": [path.relative_to(root).as_posix() for path in scannable],
        "findings": findings,
        "runtime_image_scan": (
            "requires_target_linux_evidence"
            if not docker_available
            else "available_not_invoked_by_static_scan"
        ),
        "docker_available": docker_available,
        "runtime_scan_claimed": False,
    }
    return payload, not findings


def parsed_json(output: str) -> object:
    """Parse command JSON, returning a bounded error record when malformed."""
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        return {"parse_error": str(exc), "output_tail": output[-4000:]}


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
            "P15",
            "P16",
        ),
        default="P16",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report_dir = root / "reports/security"
    report_dir.mkdir(parents=True, exist_ok=True)
    pnpm = resolve_pnpm_command(root)

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

    javascript_result = run([*pnpm, "audit", "--json", "--audit-level", "high"], root)
    javascript_payload = parsed_json(javascript_result.stdout)
    (report_dir / "javascript_dependency_audit.json").write_text(
        json.dumps(javascript_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    infrastructure, infrastructure_passed = infrastructure_policy(root)
    (report_dir / "container_iac_scan.json").write_text(
        json.dumps(infrastructure, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    checks = {
        "detect_secrets": detect_result.returncode == 0 and secret_count == 0,
        "python_dependency_audit": python_result.returncode == 0,
        "javascript_dependency_audit": javascript_result.returncode == 0,
        "container_iac_policy": infrastructure_passed,
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
