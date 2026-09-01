"""P07 boundary, deterministic evidence, and deferred-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml


def _json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def test_p07_state_is_in_progress_live_locked_and_stops_before_p08(project_root: Path) -> None:
    state = cast(
        dict[str, object],
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    previous = cast(dict[str, object], state["previous_phase"])
    deferred = cast(list[dict[str, object]], state["deferred_acceptance_queue"])
    assert state["current_phase"] == "P07"
    assert state["next_phase"] == "P08"
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    assert previous["phase"] == "P06"
    assert previous["status"] == "in_progress"
    assert {item["phase"] for item in deferred} >= {"P05", "P06"}
    assert not (project_root / "reports/phases/P07/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p07_traceability_has_verified_tasks_and_deferred_acceptance_rows(
    project_root: Path,
) -> None:
    with (project_root / "reports/phases/P07/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 19
    assert len({row["requirement_id"] for row in rows}) == 19
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(tasks) == 13
    assert {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 6
    assert {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        assert (project_root / row["evidence"]).exists(), row["requirement_id"]


def test_p07_machine_evidence_is_point_in_time_cost_aware_and_account_free(
    project_root: Path,
) -> None:
    data = project_root / "reports/data"
    feature = _json(data / "P07_FEATURE_EVIDENCE.json")
    labels = _json(data / "P07_LABEL_EVIDENCE.json")
    dataset = _json(data / "P07_DATASET_EVIDENCE.json")
    validation = _json(data / "P07_VALIDATION_EVIDENCE.json")
    leakage = _json(data / "P07_LEAKAGE_EVIDENCE.json")
    holdout = _json(data / "P07_HOLDOUT_EVIDENCE.json")
    baseline = _json(data / "P07_BASELINE_EVIDENCE.json")
    models = _json(data / "P07_MODEL_EVIDENCE.json")
    experiments = _json(data / "P07_EXPERIMENT_EVIDENCE.json")
    mutation = _json(project_root / "reports/testing/P07_MUTATION_RESULTS.json")

    assert feature["batch_incremental_parity"] is True
    assert feature["point_in_time"] is True
    assert labels["gross_minus_cost_equals_net"] is True
    assert dataset["future_listing_backfilled"] is False
    assert dataset["required_manifest_count"] == 8
    assert validation["random_time_split_forbidden"] is True
    assert validation["walk_forward_folds"] == 5
    assert leakage["all_seven_injected_leaks_detected"] is True
    assert holdout["state"] == "LOCKED"
    assert holdout["loader_invocations"] == 0
    assert holdout["final_holdout_opened"] is False
    assert baseline["screening_only"] is True
    assert baseline["live_trading_locked"] is True
    assert models["final_holdout_opened"] is False
    assert experiments["failure_and_error_retained"] is True
    assert cast(float, mutation["score"]) >= cast(float, mutation["threshold"])


def test_p07_scoreboard_and_dependency_contract_are_explicit(project_root: Path) -> None:
    scoreboard = (project_root / "reports/research/P07/BASELINE_SCOREBOARD.md").read_text(
        encoding="utf-8"
    )
    dependency = _json(project_root / "reports/data/P07_DEPENDENCY_CONTRACT.json")
    external = _json(project_root / "reports/data/P07_EXTERNAL_BASELINE_EVIDENCE.json")
    compliance = _json(project_root / "reports/licenses/COMPLIANCE_SUMMARY.json")
    assert "Gross" in scoreboard and "Net" in scoreboard
    assert "PSR" in scoreboard and "DSR" in scoreboard and "PBO" in scoreboard
    assert "Negative results" in scoreboard
    assert "final_holdout_opened=false" in scoreboard
    assert cast(dict[str, object], dependency["scikit_learn"])["version"] == "1.9.0"
    assert dependency["ai_trader_code_copied_or_executed"] is False
    assert external["r331_state"] == "not_provided"
    assert external["fabricated_baseline"] is False
    assert compliance["phase"] == "P07"
    assert compliance["status"] == "passed"
    assert compliance["python_unknown_license_count"] == 0
