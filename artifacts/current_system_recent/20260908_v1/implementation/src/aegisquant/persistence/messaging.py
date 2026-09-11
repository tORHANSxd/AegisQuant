"""Atomic event/Outbox writes and Inbox deduplication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Select, select, update
from sqlalchemy.dialects.postgresql import insert

from aegisquant.domain.serialization import canonical_content_hash
from aegisquant.domain.time import ensure_utc
from aegisquant.persistence.tables import domain_events, inbox_messages, outbox_messages


@dataclass(frozen=True, slots=True)
class StoredEvent:
    event_id: str
    event_type: str
    schema_version: str
    available_time: datetime
    ingest_time: datetime
    payload: dict[str, Any]
    idempotency_key: str

    def __post_init__(self) -> None:
        available = ensure_utc(self.available_time)
        ingest = ensure_utc(self.ingest_time)
        if available > ingest:
            raise ValueError("event cannot be ingested before it is available")
        object.__setattr__(self, "available_time", available)
        object.__setattr__(self, "ingest_time", ingest)


def append_event_with_outbox(
    connection: Connection,
    *,
    event: StoredEvent,
    message_id: str,
    topic: str,
    outbox_idempotency_key: str,
) -> bool:
    """Append one economic fact and Outbox row in the caller's transaction."""
    content_hash = canonical_content_hash(event.payload)
    event_statement = (
        insert(domain_events)
        .values(
            event_id=event.event_id,
            event_type=event.event_type,
            schema_version=event.schema_version,
            available_time=event.available_time,
            ingest_time=event.ingest_time,
            payload=event.payload,
            content_hash=content_hash,
            idempotency_key=event.idempotency_key,
        )
        .on_conflict_do_nothing()
        .returning(domain_events.c.event_id)
    )
    inserted_event_id = connection.execute(event_statement).scalar_one_or_none()
    if inserted_event_id is None:
        return False
    connection.execute(
        insert(outbox_messages).values(
            message_id=message_id,
            event_id=event.event_id,
            topic=topic,
            schema_version=event.schema_version,
            payload=event.payload,
            idempotency_key=outbox_idempotency_key,
        )
    )
    return True


def record_inbox_once(
    connection: Connection,
    *,
    consumer_name: str,
    message_id: str,
    idempotency_key: str,
    payload_hash: str,
    result_code: str,
) -> bool:
    """Record consumption once for either message ID or semantic idempotency key."""
    statement = (
        insert(inbox_messages)
        .values(
            consumer_name=consumer_name,
            message_id=message_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            result_code=result_code,
        )
        .on_conflict_do_nothing()
        .returning(inbox_messages.c.message_id)
    )
    return connection.execute(statement).scalar_one_or_none() is not None


def pending_outbox(limit: int = 100) -> Select[tuple[Any, ...]]:
    """Build a stable pending-message query; caller owns locking and transaction."""
    if limit < 1:
        raise ValueError("outbox limit must be positive")
    return (
        select(outbox_messages)
        .where(outbox_messages.c.published_at.is_(None))
        .order_by(outbox_messages.c.created_at, outbox_messages.c.message_id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def mark_outbox_published(
    connection: Connection, *, message_id: str, published_at: datetime
) -> bool:
    result = connection.execute(
        update(outbox_messages)
        .where(
            outbox_messages.c.message_id == message_id,
            outbox_messages.c.published_at.is_(None),
        )
        .values(
            published_at=ensure_utc(published_at),
            publish_attempts=outbox_messages.c.publish_attempts + 1,
        )
    )
    return result.rowcount == 1
