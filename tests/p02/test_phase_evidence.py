"""P02 phase-boundary, required evidence, and acceptance binding tests."""

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
    return cast(
        dict[str, object],
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )


def test_p02_is_the_only_active_phase_and_live_remains_locked(project_root: Path) -> None:
    state = load_state(project_root)
    previous = cast(dict[str, object], state["previous_phase"])
    assert state["current_phase"] == "P02"
    assert state["next_phase"] == "P03"
    assert state["status"] in {"in_progress", "accepted"}
    assert state["live_trading_locked"] is True
    assert previous["phase"] == "P01"
    assert previous["status"] == "accepted"
    assert not (project_root / "src/aegisquant/providers").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_every_p02_requirement_is_verified(project_root: Path) -> None:
    with (project_root / "state/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as matrix_file:
        rows = list(csv.DictReader(matrix_file))
    p02_rows = [row for row in rows if "P02" in row["owner_phase"]]
    assert len(p02_rows) == 38
    assert {row["status"] for row in p02_rows} == {"verified"}
    assert all(row["implementation_artifact"] for row in p02_rows)
    assert all(row["verification_artifact"] for row in p02_rows)


def test_mandatory_p02_data_artifacts_are_real_and_explicitly_synthetic(
    project_root: Path,
) -> None:
    report_dir = project_root / "reports/data"
    for name in (
        "DATA_LAKE_BENCHMARK.md",
        "LOCAL_ASSET_INVENTORY.md",
        "LOCAL_ASSET_INVENTORY.parquet",
        "PIT_LEAKAGE_TESTS.md",
    ):
        path = report_dir / name
        assert path.is_file() and path.stat().st_size > 0, name
    evidence = json.loads((report_dir / "P02_DATA_EVIDENCE.json").read_text(encoding="utf-8"))
    assert evidence["real_user_assets_scanned"] is False
    assert evidence["real_account_access_performed"] is False
    assert evidence["plaintext_secrets_written"] is False
    assert evidence["live_trading_locked"] is True


def test_p02_report_set_and_manifest_match_acceptance_state(project_root: Path) -> None:
    state = load_state(project_root)
    report_dir = project_root / "reports/phases/P02"
    assert (report_dir / "PLAN.md").is_file()
    if state["status"] != "accepted":
        return

    for name in REQUIRED_REPORTS:
        path = report_dir / name
        assert path.is_file() and path.stat().st_size > 0, name
    results = json.loads((report_dir / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "P02"
    assert results["commit_sha"] == state["commit_sha"]
    assert results["passed"] > 0
    assert results["failed"] == 0
    assert results["skipped"] == 0
    assert results["result"] == "pass"

    manifest_path = report_dir / "ARTIFACT_MANIFEST.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    assert state["accepted_at_utc"]
    assert state["commit_sha"] == manifest["implementation_commit"]
    assert state["artifact_manifest_sha256"] == hashlib.sha256(manifest_raw).hexdigest()
    assert manifest["phase"] == "P02"
    assert manifest["artifact_count"] == len(manifest["artifacts"])
    assert "state/PROJECT_PHASE_STATE.yaml" not in {
        entry["path"] for entry in manifest["artifacts"]
    }
