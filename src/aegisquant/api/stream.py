"""Bounded WebSocket snapshot-plus-sequence stream with REST recovery snapshots."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Final, cast

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import JsonValue, ValidationError

from aegisquant.api.models import StreamEvent, StreamSnapshotResponse, StreamSubscribe
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.time import ensure_utc
from aegisquant.readmodels.engine import ReadModelQuery
from aegisquant.readmodels.models import ProjectionKind

TOPIC_PROJECTIONS: Final[dict[str, tuple[ProjectionKind, ...]]] = {
    "account.summary": (ProjectionKind.ACCOUNT_OVERVIEW,),
    "pnl.live": (ProjectionKind.DAILY_PNL,),
    "positions.live": (ProjectionKind.POSITIONS_CURRENT,),
    "risk.state": (ProjectionKind.RISK_SUMMARY,),
    "orders.live": (ProjectionKind.ORDERS,),
    "intelligence.events": (ProjectionKind.EVENT_CLUSTERS, ProjectionKind.EVENT_CLAIMS),
    "intelligence.narratives": (ProjectionKind.NARRATIVE_STATES,),
    "intelligence.sources": (ProjectionKind.SOURCE_POLICY_STATUS,),
    "data.health": (ProjectionKind.DATA_HEALTH,),
}
ALLOWED_ORIGINS: Final = {
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://testserver",
}
QUEUE_CAPACITY: Final = 64


class SequencedStream:
    """Keep monotonic topic sequences and bounded subscriber queues."""

    def __init__(self, query: ReadModelQuery) -> None:
        self.query = query
        self._sequences = {
            topic: max(
                (
                    record.source_sequence
                    for projection in projections
                    for record in query.snapshot.records
                    if record.projection is projection
                ),
                default=0,
            )
            for topic, projections in TOPIC_PROJECTIONS.items()
        }
        self._subscribers: dict[int, tuple[frozenset[str], asyncio.Queue[StreamEvent]]] = {}
        self._next_subscriber_id = 1

    def validate_topics(self, topics: Iterable[str]) -> tuple[str, ...]:
        selected = tuple(dict.fromkeys(topics))
        if (
            not selected
            or len(selected) > 16
            or any(item not in TOPIC_PROJECTIONS for item in selected)
        ):
            raise ValueError("AQ-API-INVALID-TOPIC")
        return selected

    def snapshots(self, topics: Iterable[str], *, server_time: datetime) -> StreamSnapshotResponse:
        now = ensure_utc(server_time)
        messages: list[StreamEvent] = []
        for topic in self.validate_topics(topics):
            projections = TOPIC_PROJECTIONS[topic]
            records = [
                item.model_dump(mode="json")
                for item in self.query.snapshot.records
                if item.projection in projections
            ]
            sequence = self._sequences[topic]
            messages.append(
                StreamEvent(
                    message_type="snapshot",
                    topic=topic,
                    event_id=f"snapshot:{topic}:{sequence}",
                    event_time=self.query.snapshot.rebuilt_at,
                    server_time=now,
                    sequence=sequence,
                    payload={"records": cast("list[JsonValue]", records)},
                )
            )
        return StreamSnapshotResponse(messages=tuple(messages))

    def subscribe(self, topics: Iterable[str]) -> tuple[int, asyncio.Queue[StreamEvent]]:
        selected = frozenset(self.validate_topics(topics))
        subscriber_id = self._next_subscriber_id
        self._next_subscriber_id += 1
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=QUEUE_CAPACITY)
        self._subscribers[subscriber_id] = (selected, queue)
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: int) -> None:
        self._subscribers.pop(subscriber_id, None)

    @property
    def subscriber_ids(self) -> frozenset[int]:
        return frozenset(self._subscribers)

    def publish(
        self,
        topic: str,
        payload: dict[str, JsonValue],
        *,
        event_time: datetime,
        server_time: datetime,
    ) -> StreamEvent:
        self.validate_topics((topic,))
        self._sequences[topic] += 1
        sequence = self._sequences[topic]
        message = StreamEvent(
            message_type="increment",
            topic=topic,
            event_id=f"increment:{topic}:{sequence}:{canonical_sha256(payload)[:16]}",
            event_time=ensure_utc(event_time),
            server_time=ensure_utc(server_time),
            sequence=sequence,
            payload=payload,
        )
        overflowed: list[int] = []
        for subscriber_id, (topics, queue) in self._subscribers.items():
            if topic not in topics:
                continue
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                overflowed.append(subscriber_id)
        for subscriber_id in overflowed:
            self.unsubscribe(subscriber_id)
        return message


async def websocket_session(websocket: WebSocket, stream: SequencedStream) -> None:
    origin = websocket.headers.get("origin")
    if origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008, reason="origin denied")
        return
    await websocket.accept()
    subscriber_id: int | None = None
    try:
        try:
            request = StreamSubscribe.model_validate_json(await websocket.receive_text())
            topics = stream.validate_topics(request.topics)
        except (ValidationError, ValueError):
            await websocket.close(code=1008, reason="invalid subscription")
            return
        for message in stream.snapshots(topics, server_time=datetime.now(UTC)).messages:
            await websocket.send_json(message.model_dump(mode="json"))
        subscriber_id, queue = stream.subscribe(topics)
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                now = datetime.now(UTC)
                message = StreamEvent(
                    message_type="heartbeat",
                    topic="system.heartbeat",
                    event_id=f"heartbeat:{int(now.timestamp())}",
                    event_time=now,
                    server_time=now,
                    sequence=0,
                    payload={"status": "ok"},
                )
            await websocket.send_json(message.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    finally:
        if subscriber_id is not None:
            stream.unsubscribe(subscriber_id)
