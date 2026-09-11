"""Content-hashed Binance official changelog watcher state."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from pydantic import Field, field_validator

from aegisquant.data.hashing import canonical_json_bytes, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime

_DATE_PATTERN = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


class ChangelogSnapshot(DomainModel):
    source_name: str
    source_url: str
    observed_at: UtcDateTime
    content_sha256: str
    content_bytes: int = Field(ge=1)
    latest_entry_date: str | None
    previous_sha256: str | None
    changed: bool

    @field_validator("content_sha256", "previous_sha256")
    @classmethod
    def validate_hash(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name=str(getattr(info, "field_name", "hash")))


def inspect_changelog(
    *,
    source_name: str,
    source_url: str,
    content: bytes,
    observed_at: UtcDateTime,
    previous: ChangelogSnapshot | None = None,
) -> ChangelogSnapshot:
    if not content:
        raise ValueError("changelog content cannot be empty")
    digest = hashlib.sha256(content).hexdigest()
    dates = _DATE_PATTERN.findall(content.decode("utf-8", errors="replace"))
    previous_sha = previous.content_sha256 if previous is not None else None
    return ChangelogSnapshot(
        source_name=source_name,
        source_url=source_url,
        observed_at=observed_at,
        content_sha256=digest,
        content_bytes=len(content),
        latest_entry_date=max(dates) if dates else None,
        previous_sha256=previous_sha,
        changed=previous_sha is not None and previous_sha != digest,
    )


def write_changelog_state(path: Path, snapshot: ChangelogSnapshot) -> None:
    content = canonical_json_bytes(snapshot.model_dump(mode="json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def load_changelog_state(path: Path) -> ChangelogSnapshot | None:
    if not path.is_file():
        return None
    return ChangelogSnapshot.model_validate_json(path.read_bytes())
