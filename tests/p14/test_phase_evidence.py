"""P14 Read Model, API, dashboard, and deferred-acceptance evidence gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p14_state_is_read_only_live_locked_and_acceptance_deferred(project_root: Path) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    previous = cast("dict[str, object]", state["previous_phase"])
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    p13 = next(item for item in deferred if item["phase"] == "P13")
    assert state["current_phase"] == "P14"
    assert state["next_phase"] == "P15"
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    assert previous["phase"] == "P13"
    assert previous["evidence_commit_sha"] == p13["evidence_commit_sha"]
    assert not (project_root / "reports/phases/P14/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p14_traceability_has_verified_tasks_and_deferred_acceptance(project_root: Path) -> None:
    with (project_root / "reports/phases/P14/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 19
    assert len({row["requirement_id"] for row in rows}) == 19
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(tasks) == 13 and {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 6 and {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        assert (project_root / row["evidence"]).exists(), row["requirement_id"]


def test_p14_projection_and_postgres_contracts_are_deterministic(project_root: Path) -> None:
    projection = _json(project_root / "reports/read_models/P14_PROJECTION_EVIDENCE.json")
    postgres = _json(project_root / "reports/read_models/P14_POSTGRES_EVIDENCE.json")
    snapshot = _json(project_root / "reports/read_models/P14_SNAPSHOT.json")
    records = cast("list[dict[str, object]]", snapshot["records"])
    assert projection["deterministic_rebuild"] is True
    assert projection["failed_candidate_left_previous_snapshot_intact"] is True
    assert projection["provenance_complete"] is True
    assert projection["source_hashes_match"] is True
    assert projection["float_values_present"] is False
    assert projection["projection_coverage"] and len(records) == 15
    assert all(record["source_watermark"] for record in records)
    assert postgres["database_contract"] == "PostgreSQL"
    assert postgres["sqlite_or_mock_used_for_acceptance"] is False
    assert postgres["read_api_write_grants"] == []


def test_p14_api_stream_client_and_web_surface_are_read_only(project_root: Path) -> None:
    websocket = _json(project_root / "reports/api/P14_WEBSOCKET_EVIDENCE.json")
    client = _json(project_root / "reports/api/P14_CLIENT_CONTRACT.json")
    web = _json(project_root / "reports/web/P14_WEB_EVIDENCE.json")
    assert websocket["monotonic_increment_verified"] is True
    assert websocket["overflow_unsubscribes"] is True
    assert websocket["loopback_only_origins"] is True
    assert websocket["remote_origin_rejected_by_contract"] is True
    assert websocket["recovery_endpoint"] == "/api/v1/stream/snapshot"
    assert client["openapi_runtime_matches_checked_artifact"] is True
    assert client["required_symbols_present"] is True
    assert client["generated_file_count"] == 16
    assert web["forbidden_surface_matches"] == []
    assert web["live_trading_locked"] is True
    assert web["read_only_marker_present"] is True
    assert web["real_account_connected"] is False


def test_p14_story_chart_state_e2e_and_performance_evidence_are_complete(
    project_root: Path,
) -> None:
    storybook = _json(project_root / "reports/web/P14_STORYBOOK_EVIDENCE.json")
    charts = _json(project_root / "reports/web/P14_CHART_EVIDENCE.json")
    states = _json(project_root / "reports/web/P14_STATE_EVIDENCE.json")
    e2e = _json(project_root / "reports/web/P14_E2E_EVIDENCE.json")
    benchmark = _json(project_root / "reports/performance/P14_OVERVIEW_BENCHMARK.json")
    assert storybook["component_count"] == 24 and storybook["missing_components"] == []
    assert storybook["state_count"] == 10 and storybook["missing_states"] == []
    assert charts["missing_charts"] == []
    assert charts["semantic_data_table_present"] is True
    assert charts["text_summary_present"] is True
    assert states["missing_states"] == []
    assert e2e["test_count"] == 4
    assert e2e["formal_acceptance_performed"] is False
    assert benchmark["status"] == "passed"
    assert cast("int", benchmark["p75_ms"]) < cast("int", benchmark["target_p75_ms"])
    assert benchmark["qualifies_as_12h_or_24h_acceptance"] is False
