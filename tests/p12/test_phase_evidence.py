"""P12 Testnet-only execution, recovery, and deferred-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p12_state_is_current_deferred_live_locked_and_p11_is_preserved(
    project_root: Path,
) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    previous = cast("dict[str, object]", state["previous_phase"])
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    assert state["current_phase"] in {"P12", "P13", "P14", "P15"}
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    if state["current_phase"] == "P12":
        p11 = next(item for item in deferred if item["phase"] == "P11")
        assert state["next_phase"] == "P13"
        assert state["implementation_status"] == "implementation_verified_acceptance_deferred"
        assert len(cast("str", state["implementation_commit_sha"])) == 40
        assert previous["phase"] == "P11"
        assert previous["evidence_commit_sha"] == p11["evidence_commit_sha"]
    elif state["current_phase"] == "P13":
        p12 = next(item for item in deferred if item["phase"] == "P12")
        assert state["next_phase"] == "P14"
        assert previous["phase"] == "P12"
        assert previous["evidence_commit_sha"] == p12["evidence_commit_sha"]
    elif state["current_phase"] == "P14":
        p12 = next(item for item in deferred if item["phase"] == "P12")
        assert state["next_phase"] == "P15"
        assert previous["phase"] == "P13"
        assert p12["status"] == "implementation_verified_acceptance_deferred"
    else:
        p12 = next(item for item in deferred if item["phase"] == "P12")
        assert state["next_phase"] == "P16"
        assert previous["phase"] == "P14"
        assert p12["status"] == "implementation_verified_acceptance_deferred"
    assert not (project_root / "reports/phases/P12/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p12_traceability_has_verified_tasks_and_honest_acceptance_statuses(
    project_root: Path,
) -> None:
    with (project_root / "reports/phases/P12/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 22
    assert len({row["requirement_id"] for row in rows}) == 22
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(tasks) == 15 and {row["status"] for row in tasks} == {"verified"}
    statuses = {row["requirement_id"]: row["status"] for row in acceptance}
    assert statuses["P12-A01"] == "blocked_external_input"
    assert set(statuses.values()) == {"blocked_external_input", "in_progress"}
    for row in rows:
        assert (project_root / row["implementation"]).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        assert (project_root / row["evidence"]).exists(), row["requirement_id"]


def test_p12_submit_timeout_recovers_without_duplicate_economic_order(
    project_root: Path,
) -> None:
    adapter = _json(project_root / "reports/execution/P12_ADAPTER_EVIDENCE.json")
    recovery = _json(project_root / "reports/execution/P12_RECOVERY_EVIDENCE.json")
    scenario = cast("dict[str, object]", recovery["scenario"])
    assert adapter["allowed_environments"] == ["SIMULATED", "TESTNET"]
    assert adapter["secondary_send_enabled"] is False
    assert adapter["constant_success_adapter_present"] is False
    assert recovery["timeout_means_failure"] is False
    assert recovery["blind_resend_allowed"] is False
    assert scenario["submit_disposition"] == "UNKNOWN"
    assert scenario["recovery_disposition"] == "FOUND_OPEN_ORDER"
    assert scenario["duplicate_economic_orders"] == 0


def test_p12_state_account_rules_and_commands_fail_closed(project_root: Path) -> None:
    state = _json(project_root / "reports/execution/P12_STATE_REPLAY.json")
    account = _json(project_root / "reports/execution/P12_ACCOUNT_RECONCILIATION.json")
    rules = _json(project_root / "reports/execution/P12_RULE_EVIDENCE.json")
    command = _json(project_root / "reports/execution/P12_COMMAND_EVIDENCE.json")
    expected_states = {
        "CREATED",
        "RISK_APPROVED",
        "SUBMITTING",
        "SUBMIT_UNKNOWN",
        "VENUE_ACCEPTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_REQUESTED",
        "CANCEL_UNKNOWN",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
        "RECOVERY_REQUIRED",
        "TERMINAL_RECONCILED",
    }
    assert set(cast("list[str]", state["states"])) == expected_states
    assert state["terminal_reconciled"] is True
    assert state["late_event_can_rollback"] is False
    assert account["rest_snapshot_required_after_gap"] is True
    assert account["frontend_connection_controls_execution"] is False
    assert "ILLEGAL-QUANTITY-PRECISION" in cast("str", rules["illegal_precision_rejection"])
    assert rules["stale_rule_allowed"] is False
    assert command["risk_decision_bound"] is True
    assert command["risk_rejection_adapter_bypass_available"] is False


def test_p12_algorithms_groups_rate_limit_and_atomicity_are_bounded(
    project_root: Path,
) -> None:
    algorithm = _json(project_root / "reports/execution/P12_ALGORITHM_EVIDENCE.json")
    group = _json(project_root / "reports/execution/P12_GROUP_EVIDENCE.json")
    limiter = _json(project_root / "reports/execution/P12_RATE_LIMIT_EVIDENCE.json")
    atomic = _json(project_root / "reports/execution/P12_ATOMIC_FILL_EVIDENCE.json")
    assert algorithm["twap_total_quantity"] == "1.000000000000000000000000000"
    assert algorithm["time_bounded_passive"] is True
    assert group["unbounded_naked_exposure_allowed"] is False
    assert group["cross_venue_atomicity_assumed"] is False
    assert limiter["cancel_preempts_submit"] is True
    assert limiter["reconciliation_preempts_submit"] is True
    assert limiter["queue_is_bounded"] is True
    assert atomic["transaction_unit"] == ["fill", "ledger", "domain_event", "outbox"]
    assert atomic["authoritative_memory_advances_before_commit"] is False
    assert atomic["fault_injection_rolls_back_all_facts"] is True


def test_p12_testnet_and_nautilus_contracts_are_nonproduction(project_root: Path) -> None:
    capability = _json(project_root / "reports/execution/P12_TESTNET_CAPABILITY.json")
    compatibility = _json(project_root / "reports/compatibility/P12_NAUTILUS_EXECUTION.json")
    actual = cast("dict[str, object]", capability["capability"])
    contract = cast("dict[str, object]", compatibility["contract"])
    assert capability["real_testnet_acceptance"] == "blocked_external_input"
    assert capability["credential_reference_received"] is False
    assert capability["plaintext_credential_requested"] is False
    assert capability["production_endpoint_literal_present"] is False
    assert actual["network_requests_performed"] == 0
    assert actual["real_account_access_performed"] is False
    assert actual["live_domain_available"] is False
    assert contract["package_version"] == "1.231.0"
    assert contract["instantiated"] is False
    assert compatibility["credential_access_performed"] is False
    assert compatibility["network_requests_performed"] == 0


def test_p12_phase_reports_security_and_mutation_evidence_are_complete(
    project_root: Path,
) -> None:
    phase = project_root / "reports/phases/P12"
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
    mutation = _json(project_root / "reports/testing/P12_MUTATION_RESULTS.json")
    security = _json(project_root / "reports/security/SECURITY_SCAN_RESULTS.json")
    compliance = _json(project_root / "reports/licenses/COMPLIANCE_SUMMARY.json")
    assert mutation["status"] == "passed"
    assert mutation["killed"] == mutation["mutants_total"]
    assert mutation["survived"] == 0 and mutation["invalid"] == 0
    assert (
        security["phase"] in {"P12", "P13", "P14", "P15"} and security["secret_finding_count"] == 0
    )
    assert security["real_account_access_performed"] is False
    assert compliance["phase"] in {"P12", "P13", "P14", "P15"}
    assert compliance["python_unknown_license_count"] == 0
