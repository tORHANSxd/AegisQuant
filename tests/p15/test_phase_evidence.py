"""P15 workbench, safety, evidence, and deferred-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml

from scripts.ci import stage_commands


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p15_state_is_non_live_and_acceptance_remains_deferred(project_root: Path) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    previous = cast("dict[str, object]", state["previous_phase"])
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    p14 = next(item for item in deferred if item["phase"] == "P14")

    assert state["current_phase"] == "P15"
    assert state["next_phase"] == "P16"
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    assert previous["phase"] == "P14"
    assert previous["evidence_commit_sha"] == p14["evidence_commit_sha"]
    assert not (project_root / "reports/phases/P15/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()

    finalized = (project_root / "reports/phases/P15/SUMMARY.md").is_file()
    if finalized:
        assert state["implementation_status"] == ("implementation_verified_acceptance_deferred")
        assert len(cast("str", state["implementation_commit_sha"])) == 40
        assert len(cast("str", state["artifact_manifest_sha256"])) == 64
    else:
        assert state["implementation_status"] == "planned"
        assert state["implementation_commit_sha"] is None


def test_p15_ci_uses_the_repository_pinned_web_toolchain(project_root: Path) -> None:
    commands = dict(stage_commands(project_root, "P15"))
    expected_node = (project_root / ".tools/node-v24.20.0-win-x64/node.exe").resolve()
    expected_pnpm = (project_root / ".tools/pnpm/node_modules/pnpm/bin/pnpm.cjs").resolve()

    for stage in (
        "web-lint",
        "web-typecheck",
        "web-unit",
        "web-storybook",
        "web-build",
        "web-e2e",
    ):
        command = commands[stage]
        assert Path(command[0]).resolve() == expected_node
        assert Path(command[1]).resolve() == expected_pnpm
        assert command[2:4] == ["--filter", "@aegisquant/web"]


def test_p15_traceability_has_verified_tasks_and_deferred_acceptance(
    project_root: Path,
) -> None:
    matrix = project_root / "reports/phases/P15/REQUIREMENTS_TRACEABILITY.csv"
    with matrix.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]

    assert len(rows) == 28 and len({row["requirement_id"] for row in rows}) == 28
    assert len(tasks) == 21 and {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 7 and {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        for test in row["test"].split("; "):
            assert (project_root / test).exists(), row["requirement_id"]
        for evidence in row["evidence"].split("; "):
            assert (project_root / evidence).exists(), row["requirement_id"]


def test_p15_routes_traces_performance_accessibility_and_safety_are_evidenced(
    project_root: Path,
) -> None:
    routes = _json(project_root / "reports/web/P15_ROUTE_EVIDENCE.json")
    traces = _json(project_root / "reports/web/P15_TRACE_EVIDENCE.json")
    performance = _json(project_root / "reports/performance/P15_PERFORMANCE_EVIDENCE.json")
    accessibility = _json(project_root / "reports/web/P15_ACCESSIBILITY_EVIDENCE.json")
    browsers = _json(project_root / "reports/web/P15_BROWSER_EVIDENCE.json")
    safety = _json(project_root / "reports/security/P15_WEB_SAFETY_EVIDENCE.json")

    assert routes["route_count"] == 15 and routes["missing_routes"] == []
    assert routes["unsafe_api_methods"] == []
    assert traces["visible_order_count"] == traces["trace_count"] == 2
    assert traces["all_visible_orders_traceable"] is True
    assert traces["all_traces_complete"] is True
    assert traces["causal_overclaim_count"] == 0
    assert performance["benchmark_status"] == "passed"
    assert cast("int", performance["benchmark_p75_ms"]) < cast(
        "int", performance["benchmark_target_p75_ms"]
    )
    assert performance["protected_event_preserved"] is True
    assert cast("float", accessibility["minimum_normal_text_ratio"]) >= 4.5
    assert browsers["browsers"] == ["chromium", "firefox", "webkit"]
    assert browsers["visual_baseline_count"] == 6
    assert safety["live_trading_locked"] is True
    assert safety["unsafe_control_matches"] == []
    assert safety["api_write_routes"] == []


def test_p15_final_reports_are_consistent_when_published(project_root: Path) -> None:
    phase_dir = project_root / "reports/phases/P15"
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
    mutation = _json(project_root / "reports/testing/P15_MUTATION_RESULTS.json")
    manifest = _json(phase_dir / "ARTIFACT_MANIFEST.json")

    assert results["status"] == "passed_implementation_acceptance_deferred"
    assert results["formal_acceptance"] == "deferred"
    assert ci["status"] == "passed" and ci["passed_count"] == ci["stage_count"]
    assert candidate["status"] == "passed"
    assert mutation["status"] == "passed" and mutation["survived"] == 0
    assert manifest["phase"] == "P15"
    assert manifest["implementation_commit"] == results["implementation_commit"]
    assert cast("int", manifest["artifact_count"]) > 1000
