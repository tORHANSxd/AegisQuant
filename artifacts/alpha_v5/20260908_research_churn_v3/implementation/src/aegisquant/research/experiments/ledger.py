"""Append-only, hash-chained experiment ledger that retains every outcome."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import Field, JsonValue, field_validator, model_validator

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal

ZERO_HASH = "0" * 64


class ExperimentStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ERROR = "ERROR"


class PromotionDecision(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    PROMOTE = "PROMOTE"
    HOLD = "HOLD"
    REJECT = "REJECT"


class ExperimentRecord(DomainModel):
    run_id: str
    status: ExperimentStatus
    code_commit: str
    environment_sha256: str
    dataset_sha256: str
    feature_set_sha256: str
    label_set_sha256: str
    universe_sha256: str
    split_sha256: str
    cost_policy_sha256: str
    model_id: str
    hyperparameters: dict[str, JsonValue]
    seed: Annotated[int, Field(ge=0)]
    started_at: UtcDateTime
    finished_at: UtcDateTime
    cpu_seconds: NonNegativeDecimal
    peak_memory_mb: NonNegativeDecimal
    metrics: dict[str, Decimal]
    artifact_hashes: dict[str, str]
    parent_run_id: str | None = None
    ai_proposed: bool = False
    failure_reason: str | None = None
    promotion_decision: PromotionDecision = PromotionDecision.NOT_EVALUATED

    @field_validator(
        "environment_sha256",
        "dataset_sha256",
        "feature_set_sha256",
        "label_set_sha256",
        "universe_sha256",
        "split_sha256",
        "cost_policy_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="experiment component hash")

    @field_validator("artifact_hashes")
    @classmethod
    def validate_artifact_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        for value in values.values():
            ensure_sha256(value, field_name="experiment artifact hash")
        return values

    @model_validator(mode="after")
    def validate_outcome(self) -> ExperimentRecord:
        if self.finished_at < self.started_at:
            raise ValueError("experiment cannot finish before it starts")
        if self.status is ExperimentStatus.SUCCEEDED and self.failure_reason is not None:
            raise ValueError("successful experiment cannot have failure reason")
        if self.status is not ExperimentStatus.SUCCEEDED and not self.failure_reason:
            raise ValueError("failed or error experiment requires failure reason")
        if any(not value.is_finite() for value in self.metrics.values()):
            raise ValueError("experiment metrics must be finite")
        return self


class ExperimentLedgerEntry(DomainModel):
    sequence: int
    previous_hash: str
    record: ExperimentRecord
    entry_hash: str

    @model_validator(mode="after")
    def validate_entry(self) -> ExperimentLedgerEntry:
        if self.sequence < 1:
            raise ValueError("experiment ledger sequence starts at one")
        ensure_sha256(self.previous_hash, field_name="experiment previous hash")
        payload = self.model_dump(mode="json", exclude={"entry_hash"})
        if self.entry_hash != canonical_sha256(payload):
            raise ValueError("experiment ledger hash mismatch")
        return self


class ExperimentLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists() and (not path.is_file() or path.is_symlink()):
            raise ValueError("experiment ledger path must be a regular file")

    def entries(self) -> tuple[ExperimentLedgerEntry, ...]:
        if not self.path.exists():
            return ()
        output: list[ExperimentLedgerEntry] = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise ValueError(f"blank experiment ledger line: {line_number}")
                entry = ExperimentLedgerEntry.model_validate_json(line)
                expected_previous = output[-1].entry_hash if output else ZERO_HASH
                if entry.sequence != line_number or entry.previous_hash != expected_previous:
                    raise ValueError("experiment ledger sequence or hash chain is invalid")
                output.append(entry)
        if len({item.record.run_id for item in output}) != len(output):
            raise ValueError("experiment ledger contains duplicate run id")
        return tuple(output)

    def append(self, record: ExperimentRecord) -> ExperimentLedgerEntry:
        entries = self.entries()
        if any(item.record.run_id == record.run_id for item in entries):
            raise ValueError("AQ-EXPERIMENT-RUN-ID-DUPLICATE")
        payload = {
            "sequence": len(entries) + 1,
            "previous_hash": entries[-1].entry_hash if entries else ZERO_HASH,
            "record": record.model_dump(mode="json"),
        }
        entry = ExperimentLedgerEntry(
            sequence=len(entries) + 1,
            previous_hash=entries[-1].entry_hash if entries else ZERO_HASH,
            record=record,
            entry_hash=canonical_sha256(payload),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as stream:
            stream.write(canonical_json_bytes(entry.model_dump(mode="json")))
            stream.flush()
        return entry

    def get(self, run_id: str) -> ExperimentRecord:
        for entry in self.entries():
            if entry.record.run_id == run_id:
                return entry.record
        raise KeyError(f"experiment run not found: {run_id}")

    def query(self, *, status: ExperimentStatus | None = None) -> tuple[ExperimentRecord, ...]:
        return tuple(
            entry.record
            for entry in self.entries()
            if status is None or entry.record.status is status
        )
