"""Machine-readable hypotheses and an append-only approval queue."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from pydantic import Field, JsonValue, field_validator, model_validator

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.research.budgets import ResourceBudget

ZERO_HASH = "0" * 64


class HypothesisAuthor(StrEnum):
    HUMAN = "human"
    AI = "ai"


class ProposalState(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class HypothesisSpec(DomainModel):
    hypothesis_id: str
    claim: str = Field(min_length=1, max_length=2000)
    economic_rationale: str = Field(min_length=1, max_length=4000)
    falsification_conditions: tuple[str, ...] = Field(min_length=1)
    markets: tuple[str, ...] = Field(min_length=1)
    horizons: tuple[str, ...] = Field(min_length=1)
    required_data: tuple[str, ...] = Field(min_length=1)
    feature_candidates: tuple[str, ...] = Field(min_length=1)
    label_id: str
    baselines: tuple[str, ...] = Field(min_length=1)
    metrics: tuple[str, ...] = Field(min_length=1)
    validation_policy_id: str
    compute_budget: ResourceBudget
    search_space: dict[str, JsonValue]
    expected_failure_modes: tuple[str, ...] = Field(min_length=1)
    source_lineage: tuple[str, ...] = Field(min_length=1)
    created_by: HypothesisAuthor
    created_at_utc: UtcDateTime

    @field_validator("hypothesis_id", "label_id", "validation_policy_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not value.strip() or len(value) > 255:
            raise ValueError("hypothesis identifiers must be non-empty and bounded")
        return value

    @property
    def spec_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class HypothesisProposal(DomainModel):
    proposal_id: str
    hypothesis: HypothesisSpec
    state: ProposalState
    proposed_by: str
    reviewed_by: str | None = None
    decision_reason: str | None = None
    recorded_at_utc: UtcDateTime

    @model_validator(mode="after")
    def enforce_approval_boundary(self) -> HypothesisProposal:
        if self.state is ProposalState.PROPOSED:
            if self.reviewed_by is not None or self.decision_reason is not None:
                raise ValueError("unreviewed proposal cannot contain a decision")
        elif not self.reviewed_by or not self.decision_reason:
            raise ValueError("reviewed proposal requires reviewer and reason")
        if self.state is ProposalState.APPROVED and (
            self.reviewed_by is None or self.reviewed_by.casefold() == "ai"
        ):
            raise ValueError("AI cannot approve a hypothesis")
        return self


class HypothesisQueueEntry(DomainModel):
    sequence: int = Field(ge=1)
    previous_hash: str
    proposal: HypothesisProposal
    entry_hash: str

    @model_validator(mode="after")
    def validate_hash_chain_entry(self) -> HypothesisQueueEntry:
        ensure_sha256(self.previous_hash, field_name="hypothesis previous hash")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"entry_hash"}))
        if self.entry_hash != expected:
            raise ValueError("hypothesis queue entry hash mismatch")
        return self


class HypothesisQueue:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists() and (not path.is_file() or path.is_symlink()):
            raise ValueError("hypothesis queue must be a regular file")

    def entries(self) -> tuple[HypothesisQueueEntry, ...]:
        if not self.path.exists():
            return ()
        output: list[HypothesisQueueEntry] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                raise ValueError(f"blank hypothesis queue line: {line_number}")
            entry = HypothesisQueueEntry.model_validate_json(line)
            previous = output[-1].entry_hash if output else ZERO_HASH
            if entry.sequence != line_number or entry.previous_hash != previous:
                raise ValueError("hypothesis queue sequence or chain is invalid")
            output.append(entry)
        return tuple(output)

    def append(self, proposal: HypothesisProposal) -> HypothesisQueueEntry:
        entries = self.entries()
        latest = tuple(
            item.proposal for item in entries if item.proposal.proposal_id == proposal.proposal_id
        )
        if latest and latest[-1].state is not ProposalState.PROPOSED:
            raise ValueError("AQ-HYPOTHESIS-PROPOSAL-TERMINAL")
        if latest and proposal.state is ProposalState.PROPOSED:
            raise ValueError("AQ-HYPOTHESIS-PROPOSAL-DUPLICATE")
        if latest and latest[-1].hypothesis != proposal.hypothesis:
            raise ValueError("AQ-HYPOTHESIS-PROPOSAL-MUTATED")
        if not latest and proposal.state is not ProposalState.PROPOSED:
            raise ValueError("AQ-HYPOTHESIS-DECISION-WITHOUT-PROPOSAL")
        payload = {
            "sequence": len(entries) + 1,
            "previous_hash": entries[-1].entry_hash if entries else ZERO_HASH,
            "proposal": proposal.model_dump(mode="json"),
        }
        entry = HypothesisQueueEntry(
            sequence=len(entries) + 1,
            previous_hash=entries[-1].entry_hash if entries else ZERO_HASH,
            proposal=proposal,
            entry_hash=canonical_sha256(payload),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as stream:
            stream.write(canonical_json_bytes(entry.model_dump(mode="json")))
            stream.flush()
            os.fsync(stream.fileno())
        return entry

    def approved(self) -> tuple[HypothesisSpec, ...]:
        latest: dict[str, HypothesisProposal] = {}
        for entry in self.entries():
            latest[entry.proposal.proposal_id] = entry.proposal
        return tuple(
            item.hypothesis for item in latest.values() if item.state is ProposalState.APPROVED
        )
