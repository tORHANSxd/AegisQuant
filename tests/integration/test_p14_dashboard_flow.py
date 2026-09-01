"""Dashboard API must expose the exact immutable service-side Read Model snapshot."""
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from aegisquant.api import create_app
from aegisquant.readmodels.bootstrap import build_snapshot
from aegisquant.readmodels.models import ProjectionKind


def test_overview_records_are_the_service_side_projection(project_root: Path) -> None:
    snapshot = build_snapshot(project_root)
    response = TestClient(create_app(snapshot)).get("/api/v1/overview")
    assert response.status_code == 200
    payload = cast("dict[str, object]", response.json())

    expected = {
        "account": ProjectionKind.ACCOUNT_OVERVIEW,
        "pnl": ProjectionKind.DAILY_PNL,
        "risk": ProjectionKind.RISK_SUMMARY,
    }
    for response_key, projection in expected.items():
        source = next(record for record in snapshot.records if record.projection is projection)
        actual = cast("dict[str, object]", payload[response_key])
        assert actual["content_sha256"] == source.content_sha256
        assert actual["source_sha256"] == source.source_sha256
        assert actual["source_watermark"] == source.source_watermark
        assert actual["payload"] == source.payload

    assert payload["snapshot_sha256"] == snapshot.content_sha256
    assert payload["live_trading_locked"] is True
