"""Append-only event journal retaining every experiment and trial outcome."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from pydantic import Field, JsonValue, model_validator

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime

ZERO_HASH = "0" * 64


class ExperimentEventType(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    PRUNED = "PRUNED"
    TIMED_OUT = "TIMED_OUT"
    RECOVERED = "RECOVERED"


TERMINAL_EVENTS = frozenset(
    {
        ExperimentEventType.SUCCEEDED,
        ExperimentEventType.FAILED,
        ExperimentEventType.ERROR,
        ExperimentEventType.PRUNED,
        ExperimentEventType.TIMED_OUT,
    }
)


class ExperimentEvent(DomainModel):
    event_id: str
    run_id: str
    event_type: ExperimentEventType
    recorded_at_utc: UtcDateTime
    trial_number: int | None = Field(default=None, ge=0)
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reason_for_unsuccessful_terminal(self) -> ExperimentEvent:
        if self.event_type in TERMINAL_EVENTS - {ExperimentEventType.SUCCEEDED}:
            reason = self.details.get("reason")
            if not isinstance(reason, str) or not reason:
                raise ValueError("unsuccessful experiment event requires reason")
        return self


class ExperimentEventEntry(DomainModel):
    sequence: int = Field(ge=1)
    previous_hash: str
    event: ExperimentEvent
    entry_hash: str

    @model_validator(mode="after")
    def validate_hash(self) -> ExperimentEventEntry:
        ensure_sha256(self.previous_hash, field_name="event journal previous hash")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"entry_hash"}))
        if self.entry_hash != expected:
            raise ValueError("experiment event journal hash mismatch")
        return self


class ExperimentEventJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists() and (not path.is_file() or path.is_symlink()):
            raise ValueError("experiment event journal must be a regular file")

    def entries(self) -> tuple[ExperimentEventEntry, ...]:
        if not self.path.exists():
            return ()
        output: list[ExperimentEventEntry] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                raise ValueError(f"blank experiment journal line: {line_number}")
            entry = ExperimentEventEntry.model_validate_json(line)
            previous = output[-1].entry_hash if output else ZERO_HASH
            if entry.sequence != line_number or entry.previous_hash != previous:
                raise ValueError("experiment event journal sequence or chain is invalid")
            output.append(entry)
        if len({item.event.event_id for item in output}) != len(output):
            raise ValueError("experiment event journal contains duplicate event ids")
        return tuple(output)

    def append(self, event: ExperimentEvent) -> ExperimentEventEntry:
        entries = self.entries()
        history = tuple(item.event for item in entries if item.event.run_id == event.run_id)
        if any(item.event_id == event.event_id for item in history):
            raise ValueError("AQ-EXPERIMENT-EVENT-ID-DUPLICATE")
        if not history and event.event_type is not ExperimentEventType.STARTED:
            raise ValueError("AQ-EXPERIMENT-TERMINAL-WITHOUT-START")
        if history and history[-1].event_type in TERMINAL_EVENTS:
            raise ValueError("AQ-EXPERIMENT-RUN-ALREADY-TERMINAL")
        if history and event.event_type is ExperimentEventType.STARTED:
            raise ValueError("AQ-EXPERIMENT-RUN-ALREADY-STARTED")
        payload = {
            "sequence": len(entries) + 1,
            "previous_hash": entries[-1].entry_hash if entries else ZERO_HASH,
            "event": event.model_dump(mode="json"),
        }
        entry = ExperimentEventEntry(
            sequence=len(entries) + 1,
            previous_hash=entries[-1].entry_hash if entries else ZERO_HASH,
            event=event,
            entry_hash=canonical_sha256(payload),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as stream:
            stream.write(canonical_json_bytes(entry.model_dump(mode="json")))
            stream.flush()
            os.fsync(stream.fileno())
        return entry

    def history(self, run_id: str) -> tuple[ExperimentEvent, ...]:
        return tuple(item.event for item in self.entries() if item.event.run_id == run_id)
