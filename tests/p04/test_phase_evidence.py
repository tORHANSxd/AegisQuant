from __future__ import annotations

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


def test_p04_boundary_preserves_p03_waiver_and_live_lock(project_root: Path) -> None:
    state = load_state(project_root)
    previous = cast(dict[str, object], state["previous_phase"])
    assert state["current_phase"] == "P04"
    assert state["next_phase"] == "P05"
    assert state["status"] in {"in_progress", "accepted"}
    assert state["live_trading_locked"] is True
    assert previous["phase"] == "P03"
    assert previous["status"] == "accepted_with_waiver"
    waivers = cast(list[dict[str, object]], previous["waivers"])
    assert waivers[0]["requirement_id"] == "P03-A01"
    assert not (project_root / "reports/data/BINANCE_24H_SOAK.json").exists()
    assert not (project_root / "src/aegisquant/live").exists()
    accounting_root = project_root / "src/aegisquant/accounting"
    assert not accounting_root.exists() or not any(accounting_root.rglob("*.py"))


def test_p04_traceability_has_35_real_targets(project_root: Path) -> None:
    with (project_root / "reports/phases/P04/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as matrix_file:
        rows = list(csv.DictReader(matrix_file))
    assert len(rows) == 35
    assert len({row["requirement_id"] for row in rows}) == 35
    assert {row["requirement_id"] for row in rows} == {
        *(f"P04-T{index:02d}" for index in range(1, 24)),
        *(f"P04-A{index:02d}" for index in range(1, 13)),
    }
    state = load_state(project_root)
    expected_status = "verified" if state["status"] == "accepted" else "in_progress"
    assert {row["status"] for row in rows} == {expected_status}
    for row in rows:
        assert (project_root / row["implementation"]).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        if state["status"] == "accepted":
            assert (project_root / row["evidence"]).exists(), row["requirement_id"]


def test_p04_machine_evidence_is_explicitly_public_or_fixture_only(project_root: Path) -> None:
    provider = json.loads(
        (project_root / "reports/data/P04_PUBLIC_PROVIDER_CONTRACTS.json").read_text(
            encoding="utf-8"
        )
    )
    event = json.loads(
        (project_root / "reports/data/P04_EVENT_SOURCE_EVIDENCE.json").read_text(encoding="utf-8")
    )
    assert provider["fixture_only"] is True
    assert provider["authentication_used"] is False
    assert provider["account_access_performed"] is False
    assert provider["order_capability_present"] is False
    assert provider["live_trading_locked"] is True
    assert event["credentials_requested_or_stored"] is False
    assert event["collection_enabled"] is False
    assert event["source_contracts"]["x"]["access_state"] == "awaiting_credentials"
    assert event["source_contracts"]["telegram_bot"]["access_state"] == ("awaiting_credentials")
    assert event["source_contracts"]["youtube"]["access_state"] == "awaiting_credentials"


def test_closed_p04_is_bound_to_reports_manifest_and_ci(project_root: Path) -> None:
    state = load_state(project_root)
    if state["status"] != "accepted":
        return
    report_dir = project_root / "reports/phases/P04"
    for name in REQUIRED_REPORTS:
        assert (report_dir / name).is_file() and (report_dir / name).stat().st_size > 0
    results = json.loads((report_dir / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "P04"
    assert results["result"] == "pass"
    assert results["failed"] == 0
    assert results["skipped"] == 0
    ci = json.loads((report_dir / "CI_RESULTS.json").read_text(encoding="utf-8"))
    assert ci["phase"] == "P04"
    assert ci["status"] == "passed"
    manifest_raw = (report_dir / "ARTIFACT_MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest["phase"] == "P04"
    assert state["commit_sha"] == manifest["implementation_commit"]
    assert state["artifact_manifest_sha256"] == hashlib.sha256(manifest_raw).hexdigest()
