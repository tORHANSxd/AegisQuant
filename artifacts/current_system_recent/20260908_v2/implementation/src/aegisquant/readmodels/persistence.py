"""Transactional PostgreSQL persistence for complete Read Model snapshots."""

from __future__ import annotations

from typing import Final, Literal, cast

from pydantic import JsonValue
from sqlalchemy import Connection, delete, insert, select

from aegisquant.persistence.tables import (
    read_model_projection_checkpoints,
    read_model_records,
    read_model_snapshot_state,
)
from aegisquant.readmodels.models import (
    ProjectionCheckpoint,
    ProjectionKind,
    ProjectionSnapshot,
    QualityState,
    ReadModelRecord,
)

READ_MODEL_TABLE_NAMES: Final = (
    "read_model_records",
    "read_model_projection_checkpoints",
    "read_model_snapshot_state",
)


def _schema_version(value: object) -> Literal["1.0.0"]:
    if value != "1.0.0":
        raise ValueError("AQ-READMODEL-SCHEMA-VERSION-UNSUPPORTED")
    return "1.0.0"


def replace_snapshot(connection: Connection, snapshot: ProjectionSnapshot) -> None:
    """Replace all projections in the caller's transaction; readers see old or new state."""
    connection.execute(delete(read_model_records))
    connection.execute(delete(read_model_projection_checkpoints))
    connection.execute(delete(read_model_snapshot_state))
    connection.execute(
        insert(read_model_records),
        [
            {
                "projection": item.projection.value,
                "entity_id": item.entity_id,
                "schema_version": item.schema_version,
                "source_sequence": item.source_sequence,
                "as_of_time": item.as_of_time,
                "projected_at": item.projected_at,
                "source_watermark": item.source_watermark,
                "quality_state": item.quality_state.value,
                "authoritative": item.authoritative,
                "estimated": item.estimated,
                "source_artifact": item.source_artifact,
                "source_sha256": item.source_sha256,
                "payload": item.payload,
                "content_sha256": item.content_sha256,
            }
            for item in snapshot.records
        ],
    )
    connection.execute(
        insert(read_model_projection_checkpoints),
        [
            {
                "projection": item.projection.value,
                "last_sequence": item.last_sequence,
                "source_watermark": item.source_watermark,
                "projected_at": item.projected_at,
                "record_count": item.record_count,
                "state_sha256": item.state_sha256,
            }
            for item in snapshot.checkpoints
        ],
    )
    connection.execute(
        insert(read_model_snapshot_state).values(
            singleton_id=1,
            schema_version=snapshot.schema_version,
            rebuild_id=snapshot.rebuild_id,
            rebuilt_at=snapshot.rebuilt_at,
            source_event_count=snapshot.source_event_count,
            content_sha256=snapshot.content_sha256,
        )
    )


def load_snapshot(connection: Connection) -> ProjectionSnapshot:
    """Load and hash-validate the current PostgreSQL Read Model snapshot."""
    header = connection.execute(select(read_model_snapshot_state)).mappings().one_or_none()
    if header is None:
        raise LookupError("AQ-READMODEL-SNAPSHOT-NOT-FOUND")
    records = tuple(
        ReadModelRecord(
            schema_version=_schema_version(row["schema_version"]),
            projection=ProjectionKind(cast("str", row["projection"])),
            entity_id=cast("str", row["entity_id"]),
            source_sequence=cast("int", row["source_sequence"]),
            as_of_time=row["as_of_time"],
            projected_at=row["projected_at"],
            source_watermark=cast("str", row["source_watermark"]),
            quality_state=QualityState(cast("str", row["quality_state"])),
            authoritative=cast("bool", row["authoritative"]),
            estimated=cast("bool", row["estimated"]),
            source_artifact=cast("str", row["source_artifact"]),
            source_sha256=cast("str", row["source_sha256"]),
            payload=cast("dict[str, JsonValue]", row["payload"]),
            content_sha256=cast("str", row["content_sha256"]),
        )
        for row in connection.execute(
            select(read_model_records).order_by(
                read_model_records.c.projection, read_model_records.c.entity_id
            )
        ).mappings()
    )
    checkpoints = tuple(
        ProjectionCheckpoint(
            projection=ProjectionKind(cast("str", row["projection"])),
            last_sequence=cast("int", row["last_sequence"]),
            source_watermark=cast("str", row["source_watermark"]),
            projected_at=row["projected_at"],
            record_count=cast("int", row["record_count"]),
            state_sha256=cast("str", row["state_sha256"]),
        )
        for row in connection.execute(
            select(read_model_projection_checkpoints).order_by(
                read_model_projection_checkpoints.c.projection
            )
        ).mappings()
    )
    return ProjectionSnapshot(
        schema_version=_schema_version(header["schema_version"]),
        rebuild_id=cast("str", header["rebuild_id"]),
        rebuilt_at=header["rebuilt_at"],
        source_event_count=cast("int", header["source_event_count"]),
        records=records,
        checkpoints=checkpoints,
        content_sha256=cast("str", header["content_sha256"]),
    )
