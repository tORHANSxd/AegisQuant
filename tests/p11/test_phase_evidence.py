"""P11 portfolio, independent-risk, and deferred-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p11_state_is_current_deferred_live_locked_and_p10_is_preserved(
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
    assert state["current_phase"] in {
        "P11",
        "P12",
        "P13",
        "P14",
        "P15",
        "P16",
        "P17",
        "P18",
    }
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    required = {
        "P05",
        "P06",
        "P07",
        "P08",
        "P09",
        "P10",
    }
    if state["current_phase"] == "P11":
        p10 = next(item for item in deferred if item["phase"] == "P10")
        assert state["next_phase"] == "P12"
        assert previous["phase"] == "P10"
        assert previous["evidence_commit_sha"] == p10["evidence_commit_sha"]
    elif state["current_phase"] == "P12":
        p11 = next(item for item in deferred if item["phase"] == "P11")
        assert state["next_phase"] == "P13"
        assert previous["phase"] == "P11"
        assert previous["evidence_commit_sha"] == p11["evidence_commit_sha"]
        required.add("P11")
    elif state["current_phase"] == "P13":
        p11 = next(item for item in deferred if item["phase"] == "P11")
        assert state["next_phase"] == "P14"
        assert previous["phase"] == "P12"
        assert p11["status"] == "implementation_verified_acceptance_deferred"
        required.update({"P11", "P12"})
    elif state["current_phase"] == "P14":
        p11 = next(item for item in deferred if item["phase"] == "P11")
        assert state["next_phase"] == "P15"
        assert previous["phase"] == "P13"
        assert p11["status"] == "implementation_verified_acceptance_deferred"
        required.update({"P11", "P12", "P13"})
    elif state["current_phase"] == "P15":
        p11 = next(item for item in deferred if item["phase"] == "P11")
        assert state["next_phase"] == "P16"
        assert previous["phase"] == "P14"
        assert p11["status"] == "implementation_verified_acceptance_deferred"
        required.update({"P11", "P12", "P13", "P14"})
    elif state["current_phase"] == "P16":
        p11 = next(item for item in deferred if item["phase"] == "P11")
        assert state["next_phase"] == "P17"
        assert previous["phase"] == "P15"
        assert p11["status"] == "implementation_verified_acceptance_deferred"
        required.update({"P11", "P12", "P13", "P14", "P15"})
    else:
        p11 = next(item for item in deferred if item["phase"] == "P11")
        assert previous["phase"] in {"P16", "P17"}
        assert p11["status"] == "implementation_verified_acceptance_deferred"
        current_number = int(cast("str", state["current_phase"]).removeprefix("P"))
        required.update(f"P{number:02d}" for number in range(11, current_number))
    assert {item["phase"] for item in deferred} >= required
    assert not (project_root / "reports/phases/P11/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p11_traceability_has_16_verified_tasks_and_7_deferred_acceptance_rows(
    project_root: Path,
) -> None:
    with (project_root / "reports/phases/P11/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 23
    assert len({row["requirement_id"] for row in rows}) == 23
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(tasks) == 16 and {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 7 and {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        assert (project_root / row["implementation"]).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        assert (project_root / row["evidence"]).exists(), row["requirement_id"]


def test_p11_portfolio_is_point_in_time_constrained_and_cannot_place_orders(
    project_root: Path,
) -> None:
    portfolio = _json(project_root / "reports/data/P11_PORTFOLIO_EVIDENCE.json")
    covariance = _json(project_root / "reports/data/P11_RISK_ESTIMATION_EVIDENCE.json")
    constraints = _json(project_root / "reports/data/P11_CONSTRAINT_EVIDENCE.json")
    proposal = cast("dict[str, object]", portfolio["proposal"])
    assert portfolio["confidence_discount_applied"] is True
    assert portfolio["no_trade_zone_enforced"] is True
    assert portfolio["order_capability"] is False
    assert proposal["environment_stage"] == "PAPER"
    assert proposal["order_capability"] is False
    assert covariance["future_covariance_used"] is False
    assert covariance["shrinkage_applied"] is True
    assert covariance["factor_risk_applied"] is True
    assert covariance["regime_risk_applied"] is True
    assert set(cast("list[str]", constraints["dimensions"])) == {
        "ASSET",
        "CONTRACT",
        "STRATEGY",
        "SLEEVE",
        "VENUE",
        "STABLECOIN",
        "CORRELATION_CLUSTER",
    }
    assert constraints["capacity_satisfied"] is True
    assert constraints["impact_satisfied"] is True


def test_p11_risk_decision_is_independent_stale_safe_and_non_amplifying(
    project_root: Path,
) -> None:
    decision = _json(project_root / "reports/data/P11_RISK_DECISION_EVIDENCE.json")
    architecture = _json(project_root / "reports/data/P11_ARCHITECTURE_EVIDENCE.json")
    stale = cast("dict[str, object]", decision["stale_decision"])
    assert decision["independent_snapshot"] is True
    assert decision["approved_target_amplified"] is False
    assert decision["stale_data_allows_new_risk"] is False
    assert stale["status"] == "REJECTED"
    assert stale["new_risk_allowed"] is False
    assert architecture["risk_import_violations"] == []
    assert architecture["risk_bypass_api_present"] is False
    assert architecture["risk_override_api_present"] is False
    assert architecture["research_can_create_order_intent"] is False


def test_p11_pretrade_requires_risk_decision_and_remains_paper_only(
    project_root: Path,
) -> None:
    pretrade = _json(project_root / "reports/data/P11_PRETRADE_EVIDENCE.json")
    request = cast("dict[str, object]", pretrade["request"])
    intent = cast("dict[str, object]", pretrade["order_intent"])
    assert pretrade["deployment_stage"] == "PAPER"
    assert pretrade["order_intent_requires_risk_decision"] is True
    assert pretrade["strategy_can_amplify_approved_target"] is False
    assert pretrade["order_command_created"] is False
    assert pretrade["external_side_effect_performed"] is False
    assert request["risk_decision_id"] == intent["risk_decision_id"]


def test_p11_state_machine_breakers_and_signed_playbooks_are_fail_closed(
    project_root: Path,
) -> None:
    replay = _json(project_root / "reports/data/P11_STATE_REPLAY_EVIDENCE.json")
    breakers = _json(project_root / "reports/data/P11_CIRCUIT_BREAKER_EVIDENCE.json")
    playbooks = _json(project_root / "reports/data/P11_PLAYBOOK_EVIDENCE.json")
    assert replay["kill_switch_replayed"] is True
    assert replay["reduce_only_replayed"] is True
    assert replay["automatic_less_safe_transition_allowed"] is False
    assert replay["automatic_recovery_allowed"] is False
    assert set(cast("list[str]", breakers["breaker_types"])) == {
        "DATA",
        "MODEL",
        "LOSS",
        "MARGIN",
        "LIQUIDITY",
        "VENUE",
        "SECURITY",
        "MAJOR_EVENT",
    }
    assert breakers["all_breaker_types_covered"] is True
    assert len(cast("list[str]", playbooks["playbook_types"])) == 5
    assert playbooks["signature_verified"] is True
    assert playbooks["rumor_full_liquidation_allowed"] is False
    assert playbooks["llm_full_liquidation_allowed"] is False


def test_p11_signed_policy_and_stress_evidence_are_nonproduction(
    project_root: Path,
) -> None:
    policy = _json(project_root / "reports/risk/P11_SIGNED_RISK_POLICY.json")
    stress = _json(project_root / "reports/risk/P11_STRESS_RESULTS.json")
    assert policy["fixture_only"] is True
    assert policy["allowed_stages"] == ["PAPER"]
    assert policy["live_trading_locked"] is True
    assert policy["private_key_persisted"] is False
    assert policy["secret_store_access_performed"] is False
    assert policy["signature_verified"] is True
    assert stress["fixture_only"] is True
    assert stress["live_calibration_claim"] is False
    assert set(cast("list[str]", stress["states_observed"])) == {
        "REDUCE_ONLY",
        "HALTED",
    }


def test_p11_phase_reports_and_security_evidence_are_complete(project_root: Path) -> None:
    phase = project_root / "reports/phases/P11"
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
    mutation = _json(project_root / "reports/testing/P11_MUTATION_RESULTS.json")
    security = _json(project_root / "reports/security/SECURITY_SCAN_RESULTS.json")
    compliance = _json(project_root / "reports/licenses/COMPLIANCE_SUMMARY.json")
    assert mutation["status"] == "passed"
    assert cast("float", mutation["score"]) >= cast("float", mutation["threshold"])
    assert mutation["survived"] == 0 and mutation["invalid"] == 0
    assert (
        security["phase"] in {"P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18"}
        and security["secret_finding_count"] == 0
    )
    assert compliance["phase"] in {
        "P11",
        "P12",
        "P13",
        "P14",
        "P15",
        "P16",
        "P17",
        "P18",
    }
    assert compliance["python_unknown_license_count"] == 0
