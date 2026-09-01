"""P09 implementation evidence and deferred formal-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import polars as pl
import yaml


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p09_state_is_verified_acceptance_deferred_and_preserved_after_p10_started(
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
    assert state["current_phase"] in {"P09", "P10", "P11", "P12", "P13"}
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    if state["current_phase"] == "P09":
        assert state["next_phase"] == "P10"
        assert state["implementation_status"] == "verified_acceptance_deferred"
        assert previous["phase"] == "P08"
        assert {item["phase"] for item in deferred} >= {"P05", "P06", "P07", "P08"}
    elif state["current_phase"] == "P10":
        assert state["next_phase"] == "P11"
        assert previous["phase"] == "P09"
        p09 = next(item for item in deferred if item["phase"] == "P09")
        assert p09["implementation_commit_sha"] == previous["implementation_commit_sha"]
        assert p09["evidence_commit_sha"] == previous["evidence_commit_sha"]
        assert {item["phase"] for item in deferred} >= {"P05", "P06", "P07", "P08", "P09"}
    elif state["current_phase"] == "P11":
        assert state["next_phase"] == "P12"
        assert previous["phase"] == "P10"
        p09 = next(item for item in deferred if item["phase"] == "P09")
        assert p09["status"] == "implementation_verified_acceptance_deferred"
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
        p09 = next(item for item in deferred if item["phase"] == "P09")
        assert p09["status"] == "implementation_verified_acceptance_deferred"
        assert {item["phase"] for item in deferred} >= {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
        }
    else:
        assert state["next_phase"] == "P14"
        assert previous["phase"] == "P12"
        p09 = next(item for item in deferred if item["phase"] == "P09")
        assert p09["status"] == "implementation_verified_acceptance_deferred"
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
    assert not (project_root / "reports/phases/P09/ACCEPTANCE.md").exists()
    if state["current_phase"] in {"P10", "P11", "P12", "P13"}:
        assert (project_root / "reports/phases/P10/PLAN.md").exists()


def test_p09_traceability_has_verified_tasks_and_deferred_acceptance_rows(
    project_root: Path,
) -> None:
    with (project_root / "reports/phases/P09/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 20
    assert len({row["requirement_id"] for row in rows}) == 20
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(tasks) == 14
    assert {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 6
    assert {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        for evidence in row["evidence"].split("; "):
            assert (project_root / evidence).exists(), row["requirement_id"]


def test_p09_import_static_ir_rights_and_discovery_are_fail_closed(project_root: Path) -> None:
    data = project_root / "reports/data"
    imported = _json(data / "P09_IMPORT_EVIDENCE.json")
    static = _json(data / "P09_STATIC_ANALYSIS_EVIDENCE.json")
    strategy = _json(data / "P09_STRATEGY_IR_EVIDENCE.json")
    rights = _json(data / "P09_RIGHTS_EVIDENCE.json")
    discovery = _json(data / "P09_DISCOVERY_EVIDENCE.json")

    assert imported["source_code_executed"] is False
    assert imported["notebook_kernel_started"] is False
    assert imported["real_user_export_imported"] is False
    assert imported["real_source_status"] == "awaiting_user_export"
    assert static["source_code_executed"] is False
    assert static["execution_api_exposed"] is False
    assert {"dynamic_execution", "subprocess", "unsafe_deserialization"} <= set(
        cast("list[str]", static["unsafe_categories"])
    )
    assert strategy["evidence_coverage"] == 1.0
    assert strategy["source_performance_accepted"] is False
    assert strategy["ai_missing_parameters_fabricated"] is False
    assert rights["unknown_rights_public_text_exports"] == 0
    assert rights["prohibited_content_exported"] is False
    assert discovery["network_fetch_performed_by_discovery_component"] is False
    assert discovery["access_bypass_attempted"] is False
    assert discovery["credentials_requested"] is False


def test_p09_dedupe_translation_frameworks_and_catalogs_are_reproducible(
    project_root: Path,
) -> None:
    data = project_root / "reports/data"
    dedupe = _json(data / "P09_DEDUPE_EVIDENCE.json")
    translation = _json(data / "P09_TRANSLATION_EVIDENCE.json")
    frameworks = _json(data / "P09_FRAMEWORK_REVIEW_EVIDENCE.json")
    dependency = _json(data / "P09_DEPENDENCY_CONTRACT.json")
    source_rows = pl.read_parquet(project_root / "reports/intelligence/SOURCE_CATALOG.parquet")
    strategy_rows = pl.read_parquet(project_root / "reports/intelligence/STRATEGY_CATALOG.parquet")

    assert dedupe["layers"] == 7
    assert dedupe["renamed_copy_detected"] is True
    assert translation["candidate_count"] == 3
    assert translation["common_engine"] == "EVENT"
    assert translation["source_code_reused"] is False
    assert translation["source_return_used_as_evidence"] is False
    assert translation["alpha_or_profit_claim"] is False
    assert len(cast("list[object]", frameworks["frameworks"])) == 9
    assert frameworks["required_framework_count"] == 8
    assert frameworks["ai_trader_active_integration"] is False
    assert frameworks["ai_trader_license_file_observed"] is False
    assert dependency["external_frameworks_installed_or_imported"] is False
    assert dependency["live_trading_locked"] is True
    assert source_rows.height == 11
    assert strategy_rows.height == 5
    assert (
        source_rows.filter(pl.col("rights_status") == "unknown")
        .select(pl.col("public_text_export_allowed").any())
        .item()
        is False
    )
    assert strategy_rows.select(pl.col("execution_allowed").any()).item() is False


def test_p09_reports_and_compliance_are_complete_without_formal_acceptance(
    project_root: Path,
) -> None:
    phase = project_root / "reports/phases/P09"
    required_phase = {
        "PLAN.md",
        "SUMMARY.md",
        "TEST_RESULTS.json",
        "RISKS.md",
        "NEXT_ACTIONS.md",
        "ADR_REFERENCES.md",
        "REQUIREMENTS_TRACEABILITY.csv",
    }
    required_intelligence = {
        "SOURCE_CATALOG.parquet",
        "STRATEGY_CATALOG.parquet",
        "ALPHA_PRIMITIVE_CATALOG.md",
        "DUPLICATE_CLUSTERS.md",
        "FAILURE_TAXONOMY.md",
        "CRYPTO_TRANSLATION_QUEUE.md",
        "REPRODUCTION_SCOREBOARD.md",
        "FRAMEWORK_REVIEW.md",
        "SOURCE_REQUEST_QUEUE.md",
    }
    assert required_phase.issubset({path.name for path in phase.iterdir() if path.is_file()})
    assert required_intelligence.issubset(
        {path.name for path in (project_root / "reports/intelligence").iterdir() if path.is_file()}
    )
    assert not (phase / "ACCEPTANCE.md").exists()
    compliance = _json(project_root / "reports/licenses/COMPLIANCE_SUMMARY.json")
    security = _json(project_root / "reports/security/SECURITY_SCAN_RESULTS.json")
    mutation = _json(project_root / "reports/testing/P09_MUTATION_RESULTS.json")
    holdout = _json(project_root / "reports/data/P07_HOLDOUT_EVIDENCE.json")
    assert compliance["phase"] in {"P09", "P10", "P11", "P12", "P13"}
    assert compliance["status"] == "passed"
    assert security["phase"] in {"P09", "P10", "P11", "P12", "P13"}
    assert security["status"] == "passed"
    assert mutation["status"] == "passed"
    assert cast(float, mutation["score"]) >= cast(float, mutation["threshold"])
    assert holdout["state"] == "LOCKED"
    assert holdout["loader_invocations"] == 0
