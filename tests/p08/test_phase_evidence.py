"""P08 implementation evidence and deferred formal-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p08_is_preserved_in_deferred_queue_after_later_phase_started(
    project_root: Path,
) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    p08 = next(item for item in deferred if item["phase"] == "P08")
    current_phase = cast("str", state["current_phase"])
    assert current_phase in {"P09", "P10", "P11", "P12", "P13", "P14"}
    expected_next = {
        "P09": "P10",
        "P10": "P11",
        "P11": "P12",
        "P12": "P13",
        "P13": "P14",
        "P14": "P15",
    }
    assert state["next_phase"] == expected_next[current_phase]
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    assert p08["status"] == "implementation_verified_acceptance_deferred"
    assert p08["accepted_at_utc"] is None
    required = {"P05", "P06", "P07", "P08"}
    if current_phase in {"P10", "P11", "P12", "P13", "P14"}:
        required.add("P09")
    if current_phase in {"P11", "P12", "P13", "P14"}:
        required.add("P10")
    if current_phase in {"P12", "P13", "P14"}:
        required.add("P11")
    if current_phase in {"P13", "P14"}:
        required.add("P12")
    if current_phase == "P14":
        required.add("P13")
    assert {item["phase"] for item in deferred} >= required
    assert not (project_root / "reports/phases/P08/ACCEPTANCE.md").exists()


def test_p08_traceability_has_verified_tasks_and_deferred_acceptance_rows(
    project_root: Path,
) -> None:
    with (project_root / "reports/phases/P08/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 24
    assert len({row["requirement_id"] for row in rows}) == 24
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(tasks) == 17
    assert {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 7
    assert {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        for evidence in row["evidence"].split("; "):
            assert (project_root / evidence).exists(), row["requirement_id"]


def test_p08_research_factory_council_foundation_and_safety_evidence(project_root: Path) -> None:
    data = project_root / "reports/data"
    experiments = _json(data / "P08_EXPERIMENT_EVIDENCE.json")
    council = _json(data / "P08_MODEL_COUNCIL_EVIDENCE.json")
    foundation = _json(data / "P08_FOUNDATION_MODEL_EVIDENCE.json")
    uncertainty = _json(data / "P08_UNCERTAINTY_EVIDENCE.json")
    ensemble = _json(data / "P08_ENSEMBLE_EVIDENCE.json")
    drift = _json(data / "P08_DRIFT_EVIDENCE.json")
    prompt = _json(data / "P08_PROMPT_SAFETY_EVIDENCE.json")
    committee = _json(data / "P08_EVENT_COMMITTEE_EVIDENCE.json")
    replay = _json(data / "P08_EVENT_REPLAY_EVIDENCE.json")
    resource = _json(data / "P08_RESOURCE_EVIDENCE.json")

    assert experiments["all_trials_recorded"] is True
    assert experiments["failed_and_pruned_retained"] is True
    assert experiments["optuna_trial_count"] == 3
    assert council["fair_comparison"] is True
    assert council["complexity_privilege"] is False
    assert council["selected_model_id"] == "linear-fused"
    assert council["final_holdout_opened"] is False
    finite = cast("dict[str, object]", foundation["finite_evaluation"])
    assert (
        finite["verified_weight_sha256"]
        == (
            "492290ae82bb89f9769e3479ce90b3179de1f33e600c34daa0352531538b23cd"  # pragma: allowlist secret
        )
    )
    assert foundation["restricted_models_executed"] is False
    assert uncertainty["should_abstain"] is True
    assert ensemble["oof_exact_coverage"] is True
    assert ensemble["train_validation_overlap"] is False
    assert drift["ood_abstain"] is True
    assert prompt["rejected_count"] == prompt["attack_count"] == 2
    assert prompt["tool_calls_allowed"] is False
    assert prompt["secret_access_allowed"] is False
    assert committee["evidence_escalation"] is False
    assert replay["point_in_time"] is True
    assert replay["causal_inference"] is False
    assert replay["alpha_claim"] is False
    assert resource["oom_recovered"] is True
    assert resource["gpu_contract"] == "formal_4070_ti_acceptance_deferred"


def test_p08_reports_and_compliance_are_complete_without_formal_acceptance(
    project_root: Path,
) -> None:
    phase = project_root / "reports/phases/P08"
    required = {
        "PLAN.md",
        "SUMMARY.md",
        "TEST_RESULTS.json",
        "RISKS.md",
        "NEXT_ACTIONS.md",
        "ADR_REFERENCES.md",
        "REQUIREMENTS_TRACEABILITY.csv",
    }
    assert required.issubset({path.name for path in phase.iterdir() if path.is_file()})
    assert not (phase / "ACCEPTANCE.md").exists()
    compliance = _json(project_root / "reports/licenses/COMPLIANCE_SUMMARY.json")
    security = _json(project_root / "reports/security/SECURITY_SCAN_RESULTS.json")
    mutation = _json(project_root / "reports/testing/P08_MUTATION_RESULTS.json")
    holdout = _json(project_root / "reports/data/P07_HOLDOUT_EVIDENCE.json")
    assert compliance["phase"] in {"P08", "P09", "P10", "P11", "P12", "P13", "P14"}
    assert compliance["status"] == "passed"
    assert security["phase"] in {"P08", "P09", "P10", "P11", "P12", "P13", "P14"}
    assert security["status"] == "passed"
    assert mutation["status"] == "passed"
    assert cast(float, mutation["score"]) >= cast(float, mutation["threshold"])
    assert holdout["state"] == "LOCKED"
    assert holdout["loader_invocations"] == 0
