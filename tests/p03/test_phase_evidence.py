"""P03 phase-boundary and acceptance-evidence binding tests."""

import csv
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


def p03_record(state: dict[str, object]) -> dict[str, object]:
    if state["current_phase"] == "P03":
        return state
    previous = cast(dict[str, object], state["previous_phase"])
    if previous["phase"] == "P03":
        return previous
    history = cast(list[dict[str, object]], state.get("phase_history", []))
    return next(item for item in history if item["phase"] == "P03")


def test_p03_boundary_is_explicit_and_live_trading_remains_locked(
    project_root: Path,
) -> None:
    state = load_state(project_root)
    assert state["current_phase"] in {"P03", "P04", "P05"}
    assert state["next_phase"] in {"P04", "P05", "P06"}
    assert state["status"] in {"in_progress", "accepted", "accepted_with_waiver"}
    assert state["live_trading_locked"] is True
    assert not (project_root / "src/aegisquant/live").exists()


def test_p03_traceability_targets_are_real(project_root: Path) -> None:
    matrix_path = project_root / "reports/phases/P03/REQUIREMENTS_TRACEABILITY.csv"
    with matrix_path.open(encoding="utf-8", newline="") as matrix_file:
        rows = list(csv.DictReader(matrix_file))
    assert len(rows) == 20
    assert len({row["requirement_id"] for row in rows}) == 20
    assert {row["status"] for row in rows} <= {"in_progress", "verified", "waived"}
    for row in rows:
        assert (project_root / row["implementation"]).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]

    state = p03_record(load_state(project_root))
    statuses = {row["requirement_id"]: row["status"] for row in rows}
    if state["status"] == "in_progress":
        assert set(statuses.values()) == {"in_progress"}
    elif state["status"] == "accepted":
        assert set(statuses.values()) == {"verified"}
    else:
        assert statuses["P03-A01"] == "waived"
        assert {
            status for requirement_id, status in statuses.items() if requirement_id != "P03-A01"
        } == {"verified"}


def test_p03_acceptance_requires_qualifying_24_hour_evidence_or_explicit_waiver(
    project_root: Path,
) -> None:
    state = p03_record(load_state(project_root))
    if state["status"] == "in_progress":
        assert state["accepted_at_utc"] is None
        return

    report_dir = project_root / "reports/phases/P03"
    for name in REQUIRED_REPORTS:
        path = report_dir / name
        assert path.is_file() and path.stat().st_size > 0, name

    evidence_path = project_root / "reports/data/BINANCE_24H_SOAK.json"
    if state["status"] == "accepted_with_waiver":
        assert not evidence_path.exists()
        waivers = cast(list[dict[str, object]], state["waivers"])
        assert len(waivers) == 1
        waiver = waivers[0]
        assert waiver["waiver_id"] == "P03-WAIVER-001"
        assert waiver["requirement_id"] == "P03-A01"
        assert waiver["decision"] == "owner_approved"
        assert (project_root / str(waiver["evidence"])).is_file()

        summary = json.loads(
            (project_root / "reports/data/BINANCE_SOAK_ATTEMPT_SUMMARY.json").read_text(
                encoding="utf-8"
            )
        )
        assert summary["requirement_id"] == "P03-A01"
        assert summary["acceptance_status"] == "waived"
        assert summary["qualifying_24h_evidence_present"] is False
        assert summary["qualifying_acceptance"] is False
        assert all(attempt["qualifying_acceptance"] is False for attempt in summary["attempts"])

        results = json.loads((report_dir / "TEST_RESULTS.json").read_text(encoding="utf-8"))
        assert results["result"] == "pass_with_waiver"
        assert results["failed"] == 0
        assert results["waived"] == 1
        return

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "passed"
    assert evidence["qualifying_acceptance"] is True
    assert evidence["test_mode"] is False
    assert evidence["requested_duration_seconds"] >= 86_400
    assert evidence["actual_monotonic_duration_seconds"] >= 86_400
    assert evidence["host_pause_detected"] is False
    assert evidence["manual_outage_recovered"] is True
    assert evidence["unexplained_sequence_gap_count"] == 0
    assert evidence["errors"] == []
    assert len(evidence["streams"]) == 2
    assert all(stream["message_count"] > 0 for stream in evidence["streams"])
    assert all(stream["forced_rollover_count"] > 0 for stream in evidence["streams"])
    assert evidence["public_market_data_only"] is True
    assert evidence["authentication_used"] is False
    assert evidence["account_access_performed"] is False
    assert evidence["order_capability_present"] is False
    assert evidence["live_trading_locked"] is True
