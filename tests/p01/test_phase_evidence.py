"""P01 phase-boundary and acceptance-evidence tests."""

import csv
import hashlib
import json
from pathlib import Path
from typing import cast

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


def load_state(project_root: Path) -> dict[str, object]:
    """Load the current project phase state."""
    payload = cast(
        dict[str, object],
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    return payload


def test_p01_phase_boundary_and_traceability(project_root: Path) -> None:
    state = load_state(project_root)
    assert state["current_phase"] == "P01"
    assert state["next_phase"] == "P02"
    assert state["status"] in {"in_progress", "accepted"}
    assert state["live_trading_locked"] is True

    with (project_root / "state/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as matrix_file:
        rows = list(csv.DictReader(matrix_file))
    p01_rows = [row for row in rows if "P01" in row["owner_phase"]]
    assert p01_rows
    assert {row["status"] for row in p01_rows} == {"verified"}


def test_p01_report_set_matches_phase_status(project_root: Path) -> None:
    state = load_state(project_root)
    report_dir = project_root / "reports/phases/P01"
    assert (report_dir / "PLAN.md").is_file()

    if state["status"] != "accepted":
        return

    for name in REQUIRED_REPORTS:
        path = report_dir / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name

    results = json.loads((report_dir / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "P01"
    assert results["commit_sha"] == state["commit_sha"]
    assert results["passed"] > 0
    assert results["failed"] == 0
    assert results["skipped"] == 0
    assert results["result"] == "pass"


def test_accepted_p01_state_is_bound_to_manifest(project_root: Path) -> None:
    state = load_state(project_root)
    if state["status"] != "accepted":
        return

    manifest_path = project_root / "reports/phases/P01/ARTIFACT_MANIFEST.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)

    assert state["accepted_at_utc"]
    assert state["commit_sha"] == manifest["implementation_commit"]
    assert len(str(state["commit_sha"])) == 40
    assert state["artifact_manifest_sha256"] == hashlib.sha256(manifest_raw).hexdigest()
    assert manifest["phase"] == "P01"
    assert manifest["artifact_count"] == len(manifest["artifacts"])
    assert "state/PROJECT_PHASE_STATE.yaml" not in {
        entry["path"] for entry in manifest["artifacts"]
    }
