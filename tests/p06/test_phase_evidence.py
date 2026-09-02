"""P06 boundary, traceability, artifact and deferred-acceptance evidence gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml

from aegisquant.backtest.artifacts import REQUIRED_BACKTEST_ARTIFACTS


def _json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _p06_record(state: dict[str, object]) -> dict[str, object]:
    if state["current_phase"] == "P06":
        return state
    previous = cast(dict[str, object], state["previous_phase"])
    if previous["phase"] == "P06":
        return previous
    history = cast(list[dict[str, object]], state.get("phase_history", []))
    return next(item for item in history if item["phase"] == "P06")


def test_p06_state_is_in_progress_with_live_lock_and_deferred_acceptance(
    project_root: Path,
) -> None:
    state = cast(
        dict[str, object],
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    previous = cast(dict[str, object], state["previous_phase"])
    deferred = cast(list[dict[str, object]], state["deferred_acceptance_queue"])

    assert state["current_phase"] in {
        "P06",
        "P07",
        "P08",
        "P09",
        "P10",
        "P11",
        "P12",
        "P13",
        "P14",
        "P15",
    }
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["live_trading_locked"] is True
    assert {item["phase"] for item in deferred} >= {"P05"}
    assert all(item["status"] == "implementation_verified_acceptance_deferred" for item in deferred)
    if state["current_phase"] == "P06":
        assert state["next_phase"] == "P07"
        assert previous["phase"] == "P05"
    elif state["current_phase"] == "P07":
        assert state["next_phase"] == "P08"
        assert previous["phase"] == "P06"
        assert {item["phase"] for item in deferred} >= {"P05", "P06"}
    elif state["current_phase"] == "P08":
        assert state["next_phase"] == "P09"
        assert previous["phase"] == "P07"
        assert {item["phase"] for item in deferred} >= {"P05", "P06", "P07"}
    elif state["current_phase"] == "P09":
        assert state["next_phase"] == "P10"
        assert previous["phase"] == "P08"
        assert {item["phase"] for item in deferred} >= {"P05", "P06", "P07", "P08"}
    elif state["current_phase"] == "P10":
        assert state["next_phase"] == "P11"
        assert previous["phase"] == "P09"
        assert {item["phase"] for item in deferred} >= {"P05", "P06", "P07", "P08", "P09"}
    elif state["current_phase"] == "P11":
        assert state["next_phase"] == "P12"
        assert previous["phase"] == "P10"
        assert {item["phase"] for item in deferred} >= {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
        }
    elif state["current_phase"] == "P12":
        assert state["next_phase"] == "P13"
        assert previous["phase"] == "P11"
        assert {item["phase"] for item in deferred} >= {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
        }
    elif state["current_phase"] == "P13":
        assert state["next_phase"] == "P14"
        assert previous["phase"] == "P12"
        assert {item["phase"] for item in deferred} >= {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
            "P12",
        }
    elif state["current_phase"] == "P14":
        assert state["next_phase"] == "P15"
        assert previous["phase"] == "P13"
        assert {item["phase"] for item in deferred} >= {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
            "P12",
            "P13",
        }
    else:
        assert state["next_phase"] == "P16"
        assert previous["phase"] == "P14"
        assert {item["phase"] for item in deferred} >= {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
            "P12",
            "P13",
            "P14",
        }
    if state["current_phase"] in {
        "P08",
        "P09",
        "P10",
        "P11",
        "P12",
        "P13",
        "P14",
        "P15",
    }:
        p06 = next(item for item in deferred if item["phase"] == "P06")
        assert p06["status"] == "implementation_verified_acceptance_deferred"
    else:
        assert _p06_record(state)["status"] == "in_progress"
    assert not (project_root / "reports/phases/P06/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p06_traceability_has_13_verified_tasks_and_6_deferred_acceptance_rows(
    project_root: Path,
) -> None:
    matrix = project_root / "reports/phases/P06/REQUIREMENTS_TRACEABILITY.csv"
    with matrix.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    assert len(rows) == 19
    assert len({row["requirement_id"] for row in rows}) == 19
    task_rows = [row for row in rows if row["category"] == "task"]
    acceptance_rows = [row for row in rows if row["category"] == "acceptance"]
    assert len(task_rows) == 13
    assert {row["status"] for row in task_rows} == {"verified"}
    assert len(acceptance_rows) == 6
    assert {row["status"] for row in acceptance_rows} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        assert (project_root / row["evidence"]).exists(), row["requirement_id"]


def test_p06_golden_backtest_has_exact_artifact_contract(project_root: Path) -> None:
    output = project_root / "reports/backtests/p06-golden"
    assert {path.name for path in output.iterdir() if path.is_file()} == set(
        REQUIRED_BACKTEST_ARTIFACTS
    )
    manifest = _json(output / "run_manifest.json")
    assert manifest["schema_version"] == "p06-backtest-run-manifest-v1"
    assert manifest["live_trading_locked"] is True
    assert manifest["real_account_connected"] is False
    assert len(cast(dict[str, str], manifest["artifact_sha256"])) == 11


def test_p06_machine_evidence_proves_contracts_without_account_access(
    project_root: Path,
) -> None:
    data = project_root / "reports/data"
    backtest = _json(data / "P06_BACKTEST_EVIDENCE.json")
    consistency = _json(data / "P06_CONSISTENCY_EVIDENCE.json")
    replay = _json(data / "P06_REPLAY_EVIDENCE.json")
    stress = _json(data / "P06_STRESS_EVIDENCE.json")
    nautilus = _json(data / "P06_NAUTILUS_CONTRACT.json")
    mutation = _json(project_root / "reports/testing/P06_MUTATION_RESULTS.json")
    benchmark = _json(project_root / "reports/performance/P06_BACKTEST_BENCHMARK.json")

    assert backtest["ledger_balanced"] is True
    assert backtest["artifact_count"] == 12
    assert backtest["live_trading_locked"] is True
    assert backtest["real_account_connected"] is False
    assert backtest["authentication_used"] is False
    assert backtest["order_transmission_used"] is False
    assert consistency["matched"] is True
    assert replay["deterministic"] is True
    assert replay["unique_hashes"] == 1
    assert stress["scenario_count"] == 14
    assert nautilus["deterministic"] is True
    assert nautilus["authentication_used"] is False
    assert mutation["score"] == 1.0
    assert benchmark["passed"] is True
