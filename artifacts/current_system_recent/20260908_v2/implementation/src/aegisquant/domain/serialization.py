"""Canonical versioned event serialization and explicit schema migrations."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import JsonValue, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import EventId
from aegisquant.domain.time import UtcDateTime

SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
Migration = Callable[[dict[str, JsonValue]], dict[str, JsonValue]]


def _empty_migrations() -> dict[tuple[str, str], tuple[str, Migration]]:
    return {}


class EventEnvelope(DomainModel):
    schema_name: str
    schema_version: str
    event_id: EventId
    occurred_at: UtcDateTime
    available_at: UtcDateTime
    payload: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_envelope(self) -> EventEnvelope:
        if SEMVER_RE.fullmatch(self.schema_version) is None:
            raise ValueError("event schema version must be semantic x.y.z")
        if self.occurred_at > self.available_at:
            raise ValueError("event cannot be available before it occurs")
        return self


def canonical_json(value: JsonValue | dict[str, JsonValue]) -> bytes:
    """Serialize JSON deterministically and reject non-standard numeric values."""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def canonical_content_hash(value: JsonValue | dict[str, JsonValue]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(slots=True)
class SchemaMigrationRegistry:
    """Directed, deterministic migrations between adjacent schema versions."""

    _migrations: dict[tuple[str, str], tuple[str, Migration]] = field(
        default_factory=_empty_migrations
    )

    def register(
        self,
        *,
        schema_name: str,
        from_version: str,
        to_version: str,
        migration: Migration,
    ) -> None:
        key = (schema_name, from_version)
        if key in self._migrations:
            raise ValueError(f"duplicate schema migration: {schema_name} {from_version}")
        if from_version == to_version:
            raise ValueError("schema migration must advance the version")
        self._migrations[key] = (to_version, migration)

    def migrate(
        self,
        *,
        schema_name: str,
        from_version: str,
        to_version: str,
        payload: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        current = from_version
        migrated = payload.copy()
        visited: set[str] = set()
        while current != to_version:
            if current in visited:
                raise ValueError("schema migration cycle detected")
            visited.add(current)
            step = self._migrations.get((schema_name, current))
            if step is None:
                raise ValueError(f"no migration path for {schema_name} {current} -> {to_version}")
            current, migration = step
            migrated = migration(migrated.copy())
        return migrated


def serialize_event(
    model: DomainModel,
    *,
    schema_name: str,
    schema_version: str,
    event_id: EventId,
    occurred_at: UtcDateTime,
    available_at: UtcDateTime,
) -> bytes:
    payload = model.model_dump(mode="json")
    envelope = EventEnvelope(
        schema_name=schema_name,
        schema_version=schema_version,
        event_id=event_id,
        occurred_at=occurred_at,
        available_at=available_at,
        payload=payload,
    )
    return canonical_json(envelope.model_dump(mode="json"))


def deserialize_event[ModelT: DomainModel](
    raw: bytes,
    model_type: type[ModelT],
    *,
    expected_schema_name: str,
    current_version: str,
    migrations: SchemaMigrationRegistry | None = None,
) -> ModelT:
    envelope = EventEnvelope.model_validate_json(raw)
    if envelope.schema_name != expected_schema_name:
        raise ValueError("event schema name does not match the requested model")
    payload = envelope.payload
    if envelope.schema_version != current_version:
        if migrations is None:
            raise ValueError("schema migration registry is required for legacy events")
        payload = migrations.migrate(
            schema_name=envelope.schema_name,
            from_version=envelope.schema_version,
            to_version=current_version,
            payload=payload,
        )
    return model_type.model_validate_json(canonical_json(payload))
