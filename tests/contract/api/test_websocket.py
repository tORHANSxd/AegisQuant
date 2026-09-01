"""WebSocket origin, snapshot, monotonic sequence, and backpressure contracts."""
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from aegisquant.api import create_app
from aegisquant.api.stream import QUEUE_CAPACITY, SequencedStream
from aegisquant.readmodels.bootstrap import build_snapshot
from aegisquant.readmodels.engine import ReadModelQuery


def test_websocket_starts_with_snapshot(project_root: Path) -> None:
    client = TestClient(create_app(build_snapshot(project_root)))
    with client.websocket_connect(
        "/ws/v1/stream", headers={"origin": "http://localhost:3000"}
    ) as websocket:
        websocket.send_json(
            {"action": "subscribe", "schema_version": "1", "topics": ["account.summary"]}
        )
        message = websocket.receive_json()

    assert message["message_type"] == "snapshot"
    assert message["topic"] == "account.summary"
    assert message["sequence"] >= 1
    assert message["payload"]["records"]


def test_websocket_rejects_remote_origin(project_root: Path) -> None:
    client = TestClient(create_app(build_snapshot(project_root)))
    with (
        pytest.raises(WebSocketDisconnect) as failure,
        client.websocket_connect("/ws/v1/stream", headers={"origin": "https://remote.example"}),
    ):
        pass
    assert failure.value.code == 1008


def test_stream_sequence_is_monotonic_and_overflow_unsubscribes(project_root: Path) -> None:
    stream = SequencedStream(ReadModelQuery(build_snapshot(project_root)))
    now = datetime(2026, 9, 2, tzinfo=UTC)
    subscriber_id, queue = stream.subscribe(("risk.state",))
    first = stream.publish("risk.state", {"state": "CAUTION"}, event_time=now, server_time=now)
    second = stream.publish("risk.state", {"state": "NORMAL"}, event_time=now, server_time=now)
    assert second.sequence == first.sequence + 1
    assert queue.qsize() == 2

    for index in range(QUEUE_CAPACITY):
        stream.publish("risk.state", {"index": index}, event_time=now, server_time=now)
    assert subscriber_id not in stream.subscriber_ids


def test_rest_snapshot_is_the_declared_gap_recovery(project_root: Path) -> None:
    client = TestClient(create_app(build_snapshot(project_root)))
    response = client.get(
        "/api/v1/stream/snapshot", params={"topics": "account.summary,risk.state"}
    )
    assert response.status_code == 200
    assert response.json()["recovery_required"] is False
    assert [item["topic"] for item in response.json()["messages"]] == [
        "account.summary",
        "risk.state",
    ]
