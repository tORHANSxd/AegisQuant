"""Machine-readable CI, supply-chain, and security evidence tests."""

import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from a required P00 artifact."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_security_and_compliance_evidence_passed(project_root: Path) -> None:
    security = load_json(project_root / "reports/security/SECURITY_SCAN_RESULTS.json")
    compliance = load_json(project_root / "reports/licenses/COMPLIANCE_SUMMARY.json")

    assert security["status"] == "passed"
    assert security["secret_finding_count"] == 0
    assert security["real_account_access_performed"] is False
    assert security["secret_store_access_performed"] is False
    assert compliance["status"] == "passed"
    assert compliance["python_unknown_license_count"] == 0


def test_sboms_are_cyclonedx_json(project_root: Path) -> None:
    for relative_path in (
        "reports/sbom/python.cdx.json",
        "reports/sbom/javascript.cdx.json",
    ):
        payload = load_json(project_root / relative_path)
        assert payload["bomFormat"] == "CycloneDX"
        assert payload["specVersion"]
        assert payload["components"]


def test_nautilus_compatibility_is_actual_and_live_denied(project_root: Path) -> None:
    payload = load_json(project_root / "reports/compatibility/NAUTILUS_COMPATIBILITY.json")

    assert payload["status"] == "passed"
    assert payload["version"] == "1.231.0"
    assert payload["license"] == "LGPL-3.0-or-later"
    assert payload["production_live_approved"] is False
    assert all(payload["checks"].values())


def test_ci_and_threat_model_cover_p00_gates(project_root: Path) -> None:
    workflow = (project_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    local_ci = (project_root / "scripts/ci.py").read_text(encoding="utf-8")
    threat_model = (project_root / "reports/security/THREAT_MODEL_DRAFT.md").read_text(
        encoding="utf-8"
    )

    assert "scripts/ci.py" in workflow
    action_refs = re.findall(r"uses:\s+[^@\s]+@([0-9a-f]{40})", workflow)
    assert len(action_refs) == 3
    assert "uses: actions/checkout@v" not in workflow
    for gate in (
        "ruff-lint",
        "pyright-strict",
        "pytest",
        "bandit",
        "web-build",
        "web-e2e",
        "security",
        "compliance-artifacts",
    ):
        assert gate in local_ci
    for boundary in ("依赖供应链", "Live 锁", "来源策略", "导入副作用"):
        assert boundary in threat_model
