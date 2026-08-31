"""P00 mandatory report, state, and artifact-manifest consistency tests."""

import hashlib
import json
import shutil
import subprocess  # nosec B404
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

    previous = state["previous_phase"]
    assert previous["status"] == "accepted"
    assert previous["phase"] == "P00"
    assert state["live_trading_locked"] is True
    assert previous["commit_sha"] == manifest["implementation_commit"]
    assert len(previous["evidence_commit_sha"]) == 40
    assert previous["artifact_manifest_sha256"] == hashlib.sha256(manifest_raw).hexdigest()


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
    git = shutil.which("git")
    assert git is not None
    state = yaml.safe_load(
        (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
    )
    evidence_commit = state["previous_phase"]["evidence_commit_sha"]
    for entry in entries:
        result = subprocess.run(  # nosec B603 - fixed read-only Git query
            [git, "show", f"{evidence_commit}:{entry['path']}"],
            cwd=project_root,
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0, entry["path"]
        blob = result.stdout
        candidates = [blob]
        if b"\n" in blob:
            candidates.append(blob.replace(b"\n", b"\r\n"))
        if blob.endswith(b"\n"):
            candidates.append(blob[:-1] + b"\r\n")
        assert any(
            entry["size_bytes"] == len(candidate)
            and entry["sha256"] == hashlib.sha256(candidate).hexdigest()
            for candidate in candidates
        ), entry["path"]
