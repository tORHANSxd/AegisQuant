"""P17 procurement, evidence, authority, and deferred-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml

from scripts.ci import stage_commands


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p17_state_is_non_live_and_acceptance_remains_deferred(project_root: Path) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    current = cast("str", state["current_phase"])
    assert current in {"P17", "P18"}
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    if current == "P17":
        previous = cast("dict[str, object]", state["previous_phase"])
        p16 = next(item for item in deferred if item["phase"] == "P16")
        assert state["status"] == "in_progress"
        assert state["next_phase"] == "P18"
        assert previous["phase"] == "P16"
        assert previous["evidence_commit_sha"] == p16["evidence_commit_sha"]
        if (project_root / "reports/phases/P17/SUMMARY.md").is_file():
            assert state["implementation_status"] == ("implementation_verified_acceptance_deferred")
            assert len(cast("str", state["implementation_commit_sha"])) == 40
        else:
            assert state["implementation_status"] == "planned"
    else:
        p17 = next(item for item in deferred if item["phase"] == "P17")
        assert p17["status"] == "implementation_verified_acceptance_deferred"
        assert len(cast("str", p17["implementation_commit_sha"])) == 40
        assert len(cast("str", p17["evidence_commit_sha"])) == 40
    assert not (project_root / "reports/phases/P17/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p17_ci_has_provider_evidence_and_mutation_gates(project_root: Path) -> None:
    commands = dict(stage_commands(project_root, "P17"))
    assert {"p17-provider-evidence", "p17-mutation"} <= set(commands)


def test_p17_traceability_has_verified_tasks_and_deferred_acceptance(
    project_root: Path,
) -> None:
    matrix = project_root / "reports/phases/P17/REQUIREMENTS_TRACEABILITY.csv"
    with matrix.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(rows) == 20 and len({row["requirement_id"] for row in rows}) == 20
    assert len(tasks) == 15 and {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 5 and {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        for test in row["test"].split("; "):
            assert (project_root / test).exists(), row["requirement_id"]
        for evidence in row["evidence"].split("; "):
            assert (project_root / evidence).exists(), row["requirement_id"]


def test_p17_zero_purchase_and_unmeasured_scores_are_explicit(project_root: Path) -> None:
    requests = _json(project_root / "reports/data/provider_bakeoff/TRIAL_REQUESTS.json")
    decisions = _json(project_root / "reports/data/provider_bakeoff/PROVIDER_DECISIONS.json")
    scorecard = _json(project_root / "reports/data/provider_bakeoff/PROVIDER_SCORECARD.json")
    registry = _json(project_root / "reports/data/provider_bakeoff/REGISTRY_GATE_EVIDENCE.json")
    context = _json(project_root / "configs/provider_bakeoff/context.json")

    assert requests["trial_count"] == 7
    assert requests["activated_trial_count"] == 0
    assert requests["approved_max_cost_usd"] == "0"
    assert requests["real_provider_network_requests_performed"] == 0
    assert requests["credentials_requested_or_received"] is False
    assert requests["plaintext_secrets_written"] is False
    assert decisions["procurement_decision"] == "NO_PURCHASE"
    assert decisions["approved_provider_count"] == 0
    decision_rows = cast("list[dict[str, object]]", decisions["decisions"])
    assert len(decision_rows) == 13
    databento = next(item for item in decision_rows if item["provider_id"] == "databento")
    assert databento["decision"] == "NOT_APPLICABLE"
    assert all(item["selected_as_primary"] is False for item in decision_rows)
    score_rows = cast("list[dict[str, object]]", scorecard["scorecards"])
    assert len(score_rows) == 13
    assert all(item["aggregate_score"] is None for item in score_rows)
    assert all(item["measurement_status"] == "NOT_TESTED" for item in score_rows)
    assert scorecard["numeric_scores_assigned_without_trial"] == 0
    assert registry["approved_paid_count"] == 0
    assert registry["paid_candidates_registered_at_runtime"] == []
    assert context["paid_provider_purchases_performed"] == 0
    assert context["real_provider_network_requests_performed"] == 0
    assert context["live_trading_locked"] is True


def test_p17_ablation_news_degradation_and_authority_are_evidenced(
    project_root: Path,
) -> None:
    ablation = _json(project_root / "reports/data/provider_bakeoff/ABLATION_EVIDENCE.json")
    news = _json(project_root / "reports/data/provider_bakeoff/NEWS_BAKEOFF_EVIDENCE.json")
    degradation = _json(project_root / "reports/data/provider_bakeoff/DEGRADATION_EVIDENCE.json")
    crosscheck = _json(project_root / "reports/data/provider_bakeoff/OFFICIAL_CROSSCHECK.json")
    negatives = _json(project_root / "reports/data/provider_bakeoff/NEGATIVE_RESULTS.json")

    assert ablation["fixture_only"] is True
    assert ablation["real_provider_trial_count"] == 0
    assert ablation["real_provider_incremental_value_claims"] == []
    assert ablation["feature_importance_used"] is False
    metrics = cast("dict[str, object]", news["metrics"])
    assert news["fixture_only"] is True
    assert news["real_provider_comparison_performed"] is False
    assert metrics["matched_event_count"] == 2
    assert metrics["recall"] == "0.5"
    assert metrics["false_alert_rate"] == "0.25"
    assert metrics["duplicate_rate"] == "0.25"
    assert metrics["risk_coverage_rate"] == "0.5"
    assert degradation["free_baseline_survives_provider_loss"] is True
    assert degradation["unpaid_provider_runtime_hard_dependency"] is False
    outage = cast("dict[str, object]", degradation["provider_outage"])
    assert outage["mode"] == "BASELINE_ONLY"
    assert outage["candidate_records_used"] is False
    assert crosscheck["third_party_trading_fact_rejected"] is True
    assert crosscheck["third_party_replaces_official_trading_fact"] is False
    assert crosscheck["real_provider_claim_made"] is False
    assert negatives["deleted_negative_result_count"] == 0
    assert negatives["retention_policy"] == "append_only_no_cherry_picking"


def test_p17_final_reports_are_consistent_when_published(project_root: Path) -> None:
    phase_dir = project_root / "reports/phases/P17"
    if not (phase_dir / "SUMMARY.md").is_file():
        return
    required = (
        "PLAN.md",
        "SUMMARY.md",
        "TEST_RESULTS.json",
        "RISKS.md",
        "NEXT_ACTIONS.md",
        "ADR_REFERENCES.md",
        "ARTIFACT_MANIFEST.json",
        "CI_RESULTS.json",
        "PYTHON_314_CONTRACT.json",
        "REQUIREMENTS_TRACEABILITY.csv",
    )
    assert all((phase_dir / name).is_file() for name in required)
    assert not (phase_dir / "ACCEPTANCE.md").exists()

    results = _json(phase_dir / "TEST_RESULTS.json")
    ci = _json(phase_dir / "CI_RESULTS.json")
    candidate = _json(phase_dir / "PYTHON_314_CONTRACT.json")
    mutation = _json(project_root / "reports/testing/P17_MUTATION_RESULTS.json")
    manifest = _json(phase_dir / "ARTIFACT_MANIFEST.json")
    assert results["status"] == "passed_implementation_acceptance_deferred"
    assert results["formal_acceptance"] == "deferred"
    assert ci["status"] == "passed" and ci["passed_count"] == ci["stage_count"]
    assert candidate["status"] == "passed"
    assert mutation["status"] == "passed" and mutation["survived"] == 0
    assert manifest["phase"] == "P17"
    assert manifest["implementation_commit"] == results["implementation_commit"]
    assert cast("int", manifest["artifact_count"]) > 1000
