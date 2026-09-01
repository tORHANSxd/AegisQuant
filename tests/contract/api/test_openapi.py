"""Generated OpenAPI and WebSocket artifacts must remain in lockstep with runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from aegisquant.api import create_app
from aegisquant.readmodels.bootstrap import build_snapshot


def test_checked_in_openapi_matches_runtime(project_root: Path) -> None:
    checked_in = cast(
        "dict[str, JsonValue]",
        json.loads((project_root / "reports/api/P14_OPENAPI.json").read_text(encoding="utf-8")),
    )
    generated = cast("dict[str, JsonValue]", create_app(build_snapshot(project_root)).openapi())
    assert checked_in == generated


def test_generated_types_expose_required_read_models(project_root: Path) -> None:
    index = (project_root / "apps/web/src/generated/client/index.ts").read_text(encoding="utf-8")
    for contract in (
        "OverviewResponse",
        "IntelligenceResponse",
        "StreamSnapshotResponse",
        "QualityState",
        "overviewApiV1OverviewGet",
    ):
        assert contract in index

    websocket = cast(
        "dict[str, JsonValue]",
        json.loads(
            (project_root / "reports/api/P14_WEBSOCKET_SCHEMA.json").read_text(encoding="utf-8")
        ),
    )
    assert websocket["recovery_endpoint"] == "/api/v1/stream/snapshot"
    assert websocket["subscriber_queue_capacity"] == 64
