"""P13 Paper/Shadow, chaos, and deferred wall-clock acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p13_state_is_nonfunded_live_locked_and_p12_is_preserved(project_root: Path) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    previous = cast("dict[str, object]", state["previous_phase"])
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    p12 = next(item for item in deferred if item["phase"] == "P12")
    assert state["current_phase"] in {"P13", "P14", "P15", "P16"}
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    if state["current_phase"] == "P13":
        assert state["next_phase"] == "P14"
        assert state["implementation_status"] == "implementation_verified_acceptance_deferred"
        assert len(cast("str", state["implementation_commit_sha"])) == 40
        assert previous["phase"] == "P12"
        assert previous["evidence_commit_sha"] == p12["evidence_commit_sha"]
    elif state["current_phase"] == "P14":
        p13 = next(item for item in deferred if item["phase"] == "P13")
        assert state["next_phase"] == "P15"
        assert previous["phase"] == "P13"
        assert previous["evidence_commit_sha"] == p13["evidence_commit_sha"]
    elif state["current_phase"] == "P15":
        p13 = next(item for item in deferred if item["phase"] == "P13")
        assert state["next_phase"] == "P16"
        assert previous["phase"] == "P14"
        assert p13["status"] == "implementation_verified_acceptance_deferred"
    else:
        p13 = next(item for item in deferred if item["phase"] == "P13")
        assert state["next_phase"] == "P17"
        assert previous["phase"] == "P15"
        assert p13["status"] == "implementation_verified_acceptance_deferred"
    assert not (project_root / "reports/phases/P13/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p13_traceability_has_verified_tasks_and_deferred_acceptance(project_root: Path) -> None:
    with (project_root / "reports/phases/P13/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 18
    assert len({row["requirement_id"] for row in rows}) == 18
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    task_status = {row["requirement_id"]: row["status"] for row in tasks}
    assert len(tasks) == 12
    assert task_status["P13-T12"] == "planned_acceptance_deferred"
    assert {status for requirement, status in task_status.items() if requirement != "P13-T12"} == {
        "verified"
    }
    assert len(acceptance) == 6 and {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        assert (project_root / row["implementation"]).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        assert (project_root / row["evidence"]).exists(), row["requirement_id"]


def test_p13_three_modes_are_same_semantics_but_only_paper_has_virtual_fill(
    project_root: Path,
) -> None:
    comparison = _json(project_root / "reports/runtime/P13_SEMANTIC_COMPARISON.json")
    paper = _json(project_root / "reports/runtime/P13_PAPER_EVIDENCE.json")
    shadow = _json(project_root / "reports/runtime/P13_SHADOW_EVIDENCE.json")
    actual = cast("dict[str, object]", comparison["comparison"])
    traces = cast("list[dict[str, object]]", comparison["traces"])
    assert actual["semantic_identity_equal"] is True
    assert actual["mismatch_fields"] == []
    assert {item["mode"] for item in traces} == {"HISTORICAL_REPLAY", "PAPER", "SHADOW"}
    assert paper["virtual_fills"] is True
    assert paper["economic_order_count"] == 1
    assert paper["duplicate_market_fill_count"] == 0
    assert paper["restored_duplicate_fill_count"] == 0
    assert paper["venue_network_requests_performed"] == 0
    assert shadow["write_capability"] is False
    assert shadow["write_methods_present"] == []
    assert shadow["credential_values_accessed"] is False
    assert shadow["venue_network_requests_performed"] == 0


def test_p13_stability_is_bounded_and_explicitly_not_long_run_acceptance(
    project_root: Path,
) -> None:
    payload = _json(project_root / "reports/runtime/P13_STABILITY_EVIDENCE.json")
    stability = cast("dict[str, object]", payload["stability"])
    assert stability["logical_cycles"] == 10_080
    assert stability["logical_duration_minutes"] == 10_080
    assert stability["bounded_state_verified"] is True
    assert stability["restart_count"] == 1
    assert stability["qualifying_wall_clock_acceptance"] is False
    assert stability["deferred_by_user"] is True
    assert stability["wall_clock_memory_acceptance_passed"] is False
    assert payload["qualifies_as_12h_or_24h_acceptance"] is False
    assert payload["timer_or_background_task_created"] is False


def test_p13_chaos_incidents_reconciliation_and_market_limitations_are_safe(
    project_root: Path,
) -> None:
    chaos = _json(project_root / "reports/runtime/P13_CHAOS_EVIDENCE.json")
    incidents = _json(project_root / "reports/runtime/P13_INCIDENT_DRILLS.json")
    reconciliation = _json(project_root / "reports/runtime/P13_RECONCILIATION_EVIDENCE.json")
    limitations = _json(project_root / "reports/runtime/P13_MARKET_MODE_LIMITATIONS.json")
    drills = cast("list[dict[str, object]]", chaos["drills"])
    clear = cast("dict[str, object]", reconciliation["clear"])
    difference = cast("dict[str, object]", reconciliation["difference"])
    actual_limitations = cast("dict[str, object]", limitations["limitations"])
    assert len(drills) == 6
    assert {item["fault_kind"] for item in drills} == {
        "NETWORK",
        "DATABASE",
        "MODEL",
        "DATA_SOURCE",
        "CLOCK",
        "PROCESS",
    }
    assert all(item["new_risk_allowed_during_fault"] is False for item in drills)
    assert incidents["all_have_timeline"] is True
    assert incidents["all_have_recovery_evidence"] is True
    assert clear["status"] == "CLEAR" and clear["new_risk_allowed"] is True
    assert difference["status"] == "HALTED" and difference["new_risk_allowed"] is False
    assert actual_limitations["testnet_pnl_is_strategy_evidence"] is False
    assert actual_limitations["real_account_access_performed"] is False
    assert actual_limitations["venue_network_requests_performed"] == 0
    for drill in drills:
        assert (project_root / cast("str", drill["runbook_path"])).is_file()


def test_p13_reports_mutation_security_and_compliance_are_complete(project_root: Path) -> None:
    phase = project_root / "reports/phases/P13"
    required = {
        "PLAN.md",
        "SUMMARY.md",
        "TEST_RESULTS.json",
        "RISKS.md",
        "NEXT_ACTIONS.md",
        "ARTIFACT_MANIFEST.json",
        "ADR_REFERENCES.md",
        "REQUIREMENTS_TRACEABILITY.csv",
        "CI_RESULTS.json",
        "PYTHON_314_CONTRACT.json",
    }
    assert required.issubset({path.name for path in phase.iterdir() if path.is_file()})
    assert not (phase / "ACCEPTANCE.md").exists()
    mutation = _json(project_root / "reports/testing/P13_MUTATION_RESULTS.json")
    security = _json(project_root / "reports/security/SECURITY_SCAN_RESULTS.json")
    compliance = _json(project_root / "reports/licenses/COMPLIANCE_SUMMARY.json")
    assert mutation["status"] == "passed"
    assert mutation["killed"] == mutation["mutants_total"]
    assert mutation["survived"] == 0 and mutation["invalid"] == 0
    assert (
        security["phase"] in {"P13", "P14", "P15", "P16"} and security["secret_finding_count"] == 0
    )
    assert security["real_account_access_performed"] is False
    assert compliance["phase"] in {"P13", "P14", "P15", "P16"}
    assert compliance["python_unknown_license_count"] == 0
