"""Deterministic, atomic Read Model projection and cursor query logic."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Final, cast

from pydantic import JsonValue

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256
from aegisquant.domain.time import ensure_utc
from aegisquant.readmodels.models import (
    PAYLOAD_MODELS,
    ProjectionCheckpoint,
    ProjectionEvent,
    ProjectionKind,
    ProjectionSnapshot,
    QualityState,
    ReadModelRecord,
)

CURSOR_VERSION: Final = 1


def _record_from_event(event: ProjectionEvent, *, projected_at: datetime) -> ReadModelRecord:
    validated = PAYLOAD_MODELS[event.projection].model_validate_json(
        canonical_json_bytes(event.payload)
    )
    payload = cast("dict[str, JsonValue]", validated.model_dump(mode="json"))
    source_watermark = f"{event.sequence}:{event.payload_sha256}"
    unhashed = ReadModelRecord.model_construct(
        projection=event.projection,
        entity_id=event.entity_id,
        source_sequence=event.sequence,
        as_of_time=event.as_of_time,
        projected_at=projected_at,
        source_watermark=source_watermark,
        quality_state=event.quality_state,
        authoritative=event.authoritative,
        estimated=event.estimated,
        source_artifact=event.source_artifact,
        source_sha256=event.source_sha256,
        payload=payload,
        content_sha256="",
    )
    serializable = unhashed.model_dump(mode="json", exclude={"content_sha256"})
    return ReadModelRecord(
        projection=event.projection,
        entity_id=event.entity_id,
        source_sequence=event.sequence,
        as_of_time=event.as_of_time,
        projected_at=projected_at,
        source_watermark=source_watermark,
        quality_state=event.quality_state,
        authoritative=event.authoritative,
        estimated=event.estimated,
        source_artifact=event.source_artifact,
        source_sha256=event.source_sha256,
        payload=payload,
        content_sha256=canonical_sha256(serializable),
    )


def _snapshot(
    records: Mapping[tuple[ProjectionKind, str], ReadModelRecord],
    *,
    events: tuple[ProjectionEvent, ...],
    rebuilt_at: datetime,
) -> ProjectionSnapshot:
    ordered_records = tuple(
        sorted(records.values(), key=lambda item: (item.projection, item.entity_id))
    )
    checkpoints: list[ProjectionCheckpoint] = []
    for projection in sorted({item.projection for item in ordered_records}):
        selected = tuple(item for item in ordered_records if item.projection is projection)
        last = max(selected, key=lambda item: item.source_sequence)
        state_sha256 = canonical_sha256([item.model_dump(mode="json") for item in selected])
        checkpoints.append(
            ProjectionCheckpoint(
                projection=projection,
                last_sequence=last.source_sequence,
                source_watermark=last.source_watermark,
                projected_at=rebuilt_at,
                record_count=len(selected),
                state_sha256=state_sha256,
            )
        )
    rebuild_id = canonical_sha256(
        {
            "event_ids": [item.event_id for item in events],
            "payload_hashes": [item.payload_sha256 for item in events],
        }
    )
    checkpoint_tuple = tuple(checkpoints)
    unhashed = ProjectionSnapshot.model_construct(
        rebuild_id=rebuild_id,
        rebuilt_at=rebuilt_at,
        source_event_count=len(events),
        records=ordered_records,
        checkpoints=checkpoint_tuple,
        content_sha256="",
    )
    serializable = unhashed.model_dump(mode="json", exclude={"content_sha256"})
    return ProjectionSnapshot(
        rebuild_id=rebuild_id,
        rebuilt_at=rebuilt_at,
        source_event_count=len(events),
        records=ordered_records,
        checkpoints=checkpoint_tuple,
        content_sha256=canonical_sha256(serializable),
    )


class ProjectionEngine:
    """Build a complete candidate snapshot before atomically replacing current state."""

    def __init__(self) -> None:
        self._snapshot: ProjectionSnapshot | None = None

    @property
    def snapshot(self) -> ProjectionSnapshot:
        if self._snapshot is None:
            raise RuntimeError("Read Model has not been projected")
        return self._snapshot

    def rebuild(
        self, events: Iterable[ProjectionEvent], *, projected_at: datetime
    ) -> ProjectionSnapshot:
        ordered = tuple(sorted(events, key=lambda item: item.sequence))
        if not ordered:
            raise ValueError("Read Model rebuild requires at least one event")
        expected_sequences = tuple(range(1, len(ordered) + 1))
        actual_sequences = tuple(item.sequence for item in ordered)
        if actual_sequences != expected_sequences:
            raise ValueError("AQ-READMODEL-SEQUENCE-GAP")
        if len({item.event_id for item in ordered}) != len(ordered):
            raise ValueError("AQ-READMODEL-DUPLICATE-EVENT")
        projected = ensure_utc(projected_at)
        records: dict[tuple[ProjectionKind, str], ReadModelRecord] = {}
        for event in ordered:
            records[(event.projection, event.entity_id)] = _record_from_event(
                event, projected_at=projected
            )
        candidate = _snapshot(records, events=ordered, rebuilt_at=projected)
        self._snapshot = candidate
        return candidate


def encode_cursor(projection: ProjectionKind, entity_id: str) -> str:
    raw = json.dumps([CURSOR_VERSION, projection.value, entity_id], separators=(",", ":")).encode(
        "utf-8"
    )
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, projection: ProjectionKind) -> str:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = cast("object", json.loads(base64.urlsafe_b64decode(padded).decode("utf-8")))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("AQ-API-INVALID-CURSOR") from error
    if not isinstance(decoded, list):
        raise ValueError("AQ-API-INVALID-CURSOR")
    values = cast("list[object]", decoded)
    if (
        len(values) != 3
        or values[0] != CURSOR_VERSION
        or values[1] != projection.value
        or not isinstance(values[2], str)
    ):
        raise ValueError("AQ-API-INVALID-CURSOR")
    return values[2]


class ReadModelQuery:
    """Read-only queries over one immutable projection snapshot."""

    def __init__(self, snapshot: ProjectionSnapshot) -> None:
        self.snapshot = snapshot
        self._by_projection = {
            projection: tuple(item for item in snapshot.records if item.projection is projection)
            for projection in ProjectionKind
        }

    def get(self, projection: ProjectionKind, entity_id: str) -> ReadModelRecord | None:
        return next(
            (item for item in self._by_projection[projection] if item.entity_id == entity_id),
            None,
        )

    def page(
        self,
        projection: ProjectionKind,
        *,
        limit: int,
        cursor: str | None = None,
        filters: Mapping[str, str] | None = None,
        quality_state: QualityState | None = None,
    ) -> tuple[tuple[ReadModelRecord, ...], str | None, int]:
        if not 1 <= limit <= 100:
            raise ValueError("AQ-API-INVALID-LIMIT")
        selected = self._by_projection[projection]
        if quality_state is not None:
            selected = tuple(item for item in selected if item.quality_state is quality_state)
        if filters:
            selected = tuple(
                item
                for item in selected
                if all(str(item.payload.get(key, "")) == value for key, value in filters.items())
            )
        selected = tuple(sorted(selected, key=lambda item: item.entity_id))
        total = len(selected)
        if cursor is not None:
            after = decode_cursor(cursor, projection)
            selected = tuple(item for item in selected if item.entity_id > after)
        page = selected[:limit]
        next_cursor = (
            encode_cursor(projection, page[-1].entity_id)
            if len(selected) > len(page) and page
            else None
        )
        return page, next_cursor, total
