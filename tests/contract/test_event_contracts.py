"""Generated JSON Schema, versioned event, and migration compatibility contracts."""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator

from aegisquant.domain.identifiers import AssetId, EventId
from aegisquant.domain.serialization import (
    EventEnvelope,
    SchemaMigrationRegistry,
    canonical_json,
    deserialize_event,
    serialize_event,
)
from aegisquant.domain.values import Money


def test_every_generated_contract_is_valid_and_registry_hash_is_exact() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = json.loads((root / "schemas/events/registry.json").read_text(encoding="utf-8"))
    assert len(registry["event_contracts"]) >= 18
    names = {entry["schema_name"] for entry in registry["event_contracts"]}
    assert {
        "aegisquant.source-identity",
        "aegisquant.engagement-snapshot",
        "aegisquant.collected-content",
        "aegisquant.source-batch",
        "aegisquant.official-web-change-snapshot",
        "aegisquant.bluesky-stream-selection",
    } <= names
    for entry in registry["event_contracts"]:
        path = root / entry["path"]
        raw = path.read_bytes()
        schema = json.loads(raw)
        Draft202012Validator.check_schema(schema)
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_event_round_trip_preserves_economic_fields_and_version() -> None:
    now = datetime(2026, 8, 31, 8, tzinfo=UTC)
    original = Money(amount=Decimal("123.4500"), asset_id=AssetId("USDT"))
    raw = serialize_event(
        original,
        schema_name="aegisquant.money-contract",
        schema_version="1.0.0",
        event_id=EventId("event-roundtrip"),
        occurred_at=now,
        available_at=now,
    )
    envelope = EventEnvelope.model_validate_json(raw)
    restored = deserialize_event(
        raw,
        Money,
        expected_schema_name="aegisquant.money-contract",
        current_version="1.0.0",
    )
    assert envelope.schema_version == "1.0.0"
    assert envelope.payload["amount"] == "123.4500"
    assert restored.amount.as_tuple() == original.amount.as_tuple()
    assert restored.asset_id == original.asset_id


def test_explicit_schema_migration_is_deterministic_and_compatible() -> None:
    now = datetime(2026, 8, 31, 8, tzinfo=UTC)
    legacy = EventEnvelope(
        schema_name="aegisquant.money-contract",
        schema_version="0.9.0",
        event_id=EventId("legacy-event"),
        occurred_at=now,
        available_at=now,
        payload={"minor_units": "12345", "asset_id": "USDT"},
    )
    registry = SchemaMigrationRegistry()

    def migrate_minor_units(payload: dict[str, object]) -> dict[str, object]:
        minor_units = Decimal(str(payload.pop("minor_units")))
        payload["amount"] = format(minor_units / Decimal("100"), ".2f")
        return payload

    registry.register(
        schema_name="aegisquant.money-contract",
        from_version="0.9.0",
        to_version="1.0.0",
        migration=migrate_minor_units,  # type: ignore[arg-type]
    )
    raw = canonical_json(legacy.model_dump(mode="json"))
    migrated = deserialize_event(
        raw,
        Money,
        expected_schema_name="aegisquant.money-contract",
        current_version="1.0.0",
        migrations=registry,
    )
    assert migrated == Money(amount=Decimal("123.45"), asset_id=AssetId("USDT"))
