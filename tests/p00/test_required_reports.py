"""P00 mandatory report, state, and artifact-manifest consistency tests."""

import hashlib
import json
from pathlib import Path

import yaml

REQUIRED_REPORTS = {
    "ACCEPTANCE.md",
    "ADR_REFERENCES.md",
    "ARTIFACT_MANIFEST.json",
    "NEXT_ACTIONS.md",
    "PLAN.md",
    "RISKS.md",
    "SUMMARY.md",
    "TEST_RESULTS.json",
}


def test_all_mandatory_p00_reports_exist(project_root: Path) -> None:
    report_dir = project_root / "reports/phases/P00"
    for name in REQUIRED_REPORTS:
        path = report_dir / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_results_follow_the_spec_schema(project_root: Path) -> None:
    payload = json.loads(
        (project_root / "reports/phases/P00/TEST_RESULTS.json").read_text(encoding="utf-8")
    )
    required = {
        "phase",
        "commit_sha",
        "environment_fingerprint",
        "suites",
        "passed",
        "failed",
        "skipped",
        "known_flakes",
        "coverage",
        "mutation",
        "performance",
        "security_findings",
        "result",
    }

    assert required <= payload.keys()
    assert payload["phase"] == "P00"
    assert len(payload["commit_sha"]) == 40
    assert payload["passed"] > 0
    assert payload["failed"] == 0
    assert payload["skipped"] == 0
    assert payload["result"] == "pass"
    for deferred_gate in ("coverage", "mutation", "performance"):
        assert payload[deferred_gate]["reason"]
        assert payload[deferred_gate]["next_required_phase"]


def test_accepted_state_is_bound_to_manifest(project_root: Path) -> None:
    state = yaml.safe_load(
        (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
    )
    manifest_path = project_root / "reports/phases/P00/ARTIFACT_MANIFEST.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)

    assert state["status"] == "accepted"
    assert state["current_phase"] == "P00"
    assert state["next_phase"] == "P01"
    assert state["live_trading_locked"] is True
    assert state["commit_sha"] == manifest["implementation_commit"]
    assert state["artifact_manifest_sha256"] == hashlib.sha256(manifest_raw).hexdigest()


def test_manifest_hashes_every_declared_artifact(project_root: Path) -> None:
    manifest = json.loads(
        (project_root / "reports/phases/P00/ARTIFACT_MANIFEST.json").read_text(encoding="utf-8")
    )
    entries = manifest["artifacts"]
    paths = [entry["path"] for entry in entries]

    assert manifest["artifact_count"] == len(entries)
    assert len(paths) == len(set(paths))
    assert "state/PROJECT_PHASE_STATE.yaml" not in paths
    assert "reports/phases/P00/ARTIFACT_MANIFEST.json" not in paths
    for entry in entries:
        raw = (project_root / entry["path"]).read_bytes()
        assert entry["size_bytes"] == len(raw)
        assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
