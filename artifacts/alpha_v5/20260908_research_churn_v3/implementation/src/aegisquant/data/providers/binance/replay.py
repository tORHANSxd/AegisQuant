"""Content-hashed Binance public fixtures and deterministic offline replay."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_json_bytes, ensure_sha256
from aegisquant.data.providers.binance.contracts import Product
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime


class FixtureEnvelope(DomainModel):
    sequence: int = Field(ge=0)
    product: Product
    channel: str
    observed_at: UtcDateTime
    payload: dict[str, object] | list[object]
    payload_sha256: str

    @field_validator("payload_sha256")
    @classmethod
    def validate_payload_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="payload_sha256")

    @model_validator(mode="after")
    def verify_payload(self) -> FixtureEnvelope:
        actual = hashlib.sha256(canonical_json_bytes(self.payload)).hexdigest()
        if actual != self.payload_sha256:
            raise ValueError("AQ-DATA-FIXTURE-HASH-MISMATCH")
        return self

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        product: Product,
        channel: str,
        observed_at: UtcDateTime,
        payload: dict[str, object] | list[object],
    ) -> FixtureEnvelope:
        return cls(
            sequence=sequence,
            product=product,
            channel=channel,
            observed_at=observed_at,
            payload=payload,
            payload_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        )


class FixtureManifest(DomainModel):
    schema_version: str = "1.0.0"
    file: str
    sha256: str
    event_count: int = Field(ge=0)
    first_observed_at: UtcDateTime | None
    last_observed_at: UtcDateTime | None
    source: str
    contains_credentials: bool = False

    @field_validator("sha256")
    @classmethod
    def validate_file_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="sha256")

    @model_validator(mode="after")
    def forbid_credentials(self) -> FixtureManifest:
        if self.contains_credentials:
            raise ValueError("public fixture cannot contain credentials")
        return self


def write_fixture(path: Path, records: Iterable[FixtureEnvelope]) -> FixtureManifest:
    rows = tuple(records)
    for index, record in enumerate(rows):
        if record.sequence != index:
            raise ValueError("fixture sequence must be contiguous and zero-based")
        if index and record.observed_at < rows[index - 1].observed_at:
            raise ValueError("fixture observed_at must be non-decreasing")
    content = b"".join(canonical_json_bytes(row.model_dump(mode="json")) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError("AQ-DATA-FIXTURE-IMMUTABLE-CONFLICT")
    else:
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    return FixtureManifest(
        file=path.as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        event_count=len(rows),
        first_observed_at=rows[0].observed_at if rows else None,
        last_observed_at=rows[-1].observed_at if rows else None,
        source="Binance official public market-data response samples",
        contains_credentials=False,
    )


def load_fixture(path: Path) -> tuple[FixtureEnvelope, ...]:
    rows: list[FixtureEnvelope] = []
    for line_number, line in enumerate(path.read_bytes().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = FixtureEnvelope.model_validate_json(line)
        except ValueError as error:
            raise ValueError(f"invalid fixture line {line_number}") from error
        if row.sequence != len(rows):
            raise ValueError("fixture sequence is not contiguous")
        if rows and row.observed_at < rows[-1].observed_at:
            raise ValueError("fixture observed_at moved backwards")
        rows.append(row)
    return tuple(rows)
