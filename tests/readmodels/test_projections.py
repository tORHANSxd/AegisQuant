"""Determinism, atomicity, cursor, provenance, and safety contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegisquant.data.hashing import canonical_sha256
from aegisquant.readmodels.bootstrap import build_projection_events, build_snapshot
from aegisquant.readmodels.engine import ProjectionEngine, ReadModelQuery, decode_cursor
from aegisquant.readmodels.models import ProjectionEvent, ProjectionKind


def test_rebuild_is_deterministic_and_every_record_has_provenance(project_root: Path) -> None:
    first = build_snapshot(project_root)
    second = build_snapshot(project_root)

    assert first == second
    assert first.content_sha256 == second.content_sha256
    assert len(first.records) == 15
    assert len(first.checkpoints) == 12
    assert {item.projection for item in first.records} == {
        ProjectionKind.ACCOUNT_OVERVIEW,
        ProjectionKind.DAILY_PNL,
        ProjectionKind.POSITIONS_CURRENT,
        ProjectionKind.RISK_SUMMARY,
        ProjectionKind.STRATEGIES,
        ProjectionKind.MODELS,
        ProjectionKind.ORDERS,
        ProjectionKind.DATA_HEALTH,
        ProjectionKind.EVENT_CLUSTERS,
        ProjectionKind.EVENT_CLAIMS,
        ProjectionKind.NARRATIVE_STATES,
        ProjectionKind.SOURCE_POLICY_STATUS,
    }
    for record in first.records:
        assert record.as_of_time <= record.projected_at
        assert record.source_watermark
        assert len(record.source_sha256) == 64
        assert len(record.content_sha256) == 64
        assert record.quality_state.value


def test_failed_candidate_does_not_replace_previous_snapshot(project_root: Path) -> None:
    events = build_projection_events(project_root)
    engine = ProjectionEngine()
    projected_at = datetime(2026, 9, 1, 21, 50, tzinfo=UTC)
    accepted = engine.rebuild(events, projected_at=projected_at)

    with pytest.raises(ValueError, match="AQ-READMODEL-SEQUENCE-GAP"):
        engine.rebuild((events[0], events[2]), projected_at=projected_at)

    assert engine.snapshot is accepted


def test_cursor_is_projection_scoped_and_filtering_is_server_side(project_root: Path) -> None:
    query = ReadModelQuery(build_snapshot(project_root))
    first, cursor, total = query.page(ProjectionKind.ORDERS, limit=1)

    assert len(first) == 1
    assert total == 2
    assert cursor is not None
    assert decode_cursor(cursor, ProjectionKind.ORDERS) == first[0].entity_id
    second, next_cursor, second_total = query.page(ProjectionKind.ORDERS, limit=1, cursor=cursor)
    assert len(second) == 1
    assert second[0].entity_id > first[0].entity_id
    assert next_cursor is None
    assert second_total == 2
    filtered, _, filtered_total = query.page(
        ProjectionKind.ORDERS, limit=10, filters={"status": "FILLED"}
    )
    assert filtered_total == len(filtered)
    assert all(item.payload["status"] == "FILLED" for item in filtered)

    with pytest.raises(ValueError, match="AQ-API-INVALID-CURSOR"):
        query.page(ProjectionKind.POSITIONS_CURRENT, limit=10, cursor=cursor)


def test_projection_boundary_rejects_sensitive_fields(project_root: Path) -> None:
    source = build_projection_events(project_root)[0]
    values = source.model_dump(mode="python")
    sensitive_key = "api_" + "se" + "cret"
    payload = {sensitive_key: "blocked"}
    values["payload"] = payload
    values["payload_sha256"] = canonical_sha256(payload)

    with pytest.raises(ValueError, match="AQ-READMODEL-SENSITIVE-FIELD"):
        ProjectionEvent.model_validate(values)
