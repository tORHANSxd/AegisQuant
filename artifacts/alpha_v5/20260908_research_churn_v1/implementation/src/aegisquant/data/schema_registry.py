"""Deterministic Arrow schema registry with atomic local persistence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pyarrow as pa

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256


@dataclass(frozen=True, slots=True)
class ArrowSchemaEntry:
    schema_name: str
    schema_version: str
    schema_sha256: str
    arrow_schema: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "schema_sha256": self.schema_sha256,
            "arrow_schema": self.arrow_schema,
        }


@dataclass(frozen=True, slots=True)
class ArrowSchemaRegistry:
    path: Path

    def _load(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        loaded = cast(object, json.loads(self.path.read_text(encoding="utf-8")))
        if not isinstance(loaded, dict):
            raise ValueError("AQ-DATA-SCHEMA-REGISTRY-INVALID: root must be an object")
        payload = cast(dict[str, object], loaded)
        entries = payload.get("schemas")
        if not isinstance(entries, list):
            raise ValueError("AQ-DATA-SCHEMA-REGISTRY-INVALID: schemas must be a list")
        entry_items = cast(list[object], entries)
        if not all(isinstance(item, dict) for item in entry_items):
            raise ValueError("AQ-DATA-SCHEMA-REGISTRY-INVALID: schemas must contain objects")
        typed_entries = [cast(dict[object, object], item) for item in entry_items]
        return [{str(key): str(value) for key, value in item.items()} for item in typed_entries]

    def register(
        self, *, schema_name: str, schema_version: str, schema: pa.Schema
    ) -> ArrowSchemaEntry:
        """Register a schema idempotently; reject incompatible reuse of a name/version."""
        arrow_schema = schema.to_string(show_field_metadata=True, show_schema_metadata=True)
        entry = ArrowSchemaEntry(
            schema_name=schema_name,
            schema_version=schema_version,
            schema_sha256=canonical_sha256({"arrow_schema": arrow_schema}),
            arrow_schema=arrow_schema,
        )
        entries = self._load()
        existing = next(
            (
                item
                for item in entries
                if item.get("schema_name") == schema_name
                and item.get("schema_version") == schema_version
            ),
            None,
        )
        if existing is not None:
            if existing != entry.as_dict():
                raise ValueError("AQ-DATA-SCHEMA-CONFLICT: name/version already has another schema")
            return entry
        entries.append(entry.as_dict())
        entries.sort(key=lambda item: (item["schema_name"], item["schema_version"]))
        payload = {"schema_version": "1.0.0", "schemas": entries}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        with temporary.open("wb") as output:
            output.write(canonical_json_bytes(payload))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)
        return entry
