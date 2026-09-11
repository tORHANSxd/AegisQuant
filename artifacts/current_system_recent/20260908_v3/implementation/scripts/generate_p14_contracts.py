"""Generate or verify the deterministic P14 snapshot and API contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Final, cast

from pydantic import JsonValue

from aegisquant.api.app import create_app
from aegisquant.api.models import StreamEvent, StreamSnapshotResponse, StreamSubscribe
from aegisquant.api.stream import QUEUE_CAPACITY, TOPIC_PROJECTIONS
from aegisquant.readmodels.bootstrap import build_snapshot

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUTS: Final = {
    "snapshot": ROOT / "reports/read_models/P14_SNAPSHOT.json",
    "openapi": ROOT / "reports/api/P14_OPENAPI.json",
    "web_openapi": ROOT / "apps/web/src/generated/openapi.json",
    "websocket": ROOT / "reports/api/P14_WEBSOCKET_SCHEMA.json",
    "web_websocket": ROOT / "apps/web/src/generated/websocket.schema.json",
}


def _render(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_payloads() -> dict[str, object]:
    snapshot = build_snapshot(ROOT)
    openapi = cast("dict[str, JsonValue]", create_app(snapshot).openapi())
    websocket_contract = {
        "schema_version": "p14-websocket-contract-v1",
        "path": "/ws/v1/stream",
        "allowed_topics": sorted(TOPIC_PROJECTIONS),
        "subscription_limit": 16,
        "subscriber_queue_capacity": QUEUE_CAPACITY,
        "heartbeat_seconds": 15,
        "recovery_endpoint": "/api/v1/stream/snapshot",
        "recovery_rule": (
            "On a sequence gap, stop applying increments and fetch a REST snapshot before resuming."
        ),
        "subscribe_schema": StreamSubscribe.model_json_schema(),
        "event_schema": StreamEvent.model_json_schema(),
        "snapshot_schema": StreamSnapshotResponse.model_json_schema(),
    }
    return {
        "snapshot": snapshot.model_dump(mode="json"),
        "openapi": openapi,
        "web_openapi": openapi,
        "websocket": websocket_contract,
        "web_websocket": websocket_contract,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    mismatches: list[str] = []
    for key, payload in build_payloads().items():
        target = OUTPUTS[key]
        rendered = _render(payload)
        if arguments.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
                mismatches.append(target.relative_to(ROOT).as_posix())
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="\n")
    if mismatches:
        raise SystemExit("P14 contract drift: " + ", ".join(mismatches))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
