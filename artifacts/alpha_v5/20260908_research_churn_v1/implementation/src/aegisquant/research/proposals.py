"""Proposal-only boundary between AI output and executable research."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.research.budgets import ResourceBudget, ResourceRequest, require_budget


class ApprovalState(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExperimentProposal(DomainModel):
    proposal_id: str
    hypothesis_id: str
    model_id: str
    dataset_sha256: str
    split_sha256: str
    cost_policy_sha256: str
    requested_resources: ResourceRequest
    approved_budget: ResourceBudget
    ai_generated: bool
    state: ApprovalState
    approved_by: str | None = None
    created_at_utc: UtcDateTime

    @field_validator("dataset_sha256", "split_sha256", "cost_policy_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="experiment proposal hash")

    @model_validator(mode="after")
    def enforce_approval(self) -> ExperimentProposal:
        if self.state is ApprovalState.APPROVED:
            if not self.approved_by or self.approved_by.casefold() == "ai":
                raise ValueError("AI cannot approve an experiment")
        elif self.approved_by is not None:
            raise ValueError("only approved experiments may name an approver")
        return self


class EventProposal(DomainModel):
    proposal_id: str
    event_type: str
    claim_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    ai_generated: bool
    state: ApprovalState = ApprovalState.PROPOSED
    approved_by: str | None = None
    created_at_utc: UtcDateTime
    action: str = "RESEARCH_ONLY"

    @model_validator(mode="after")
    def enforce_no_execution(self) -> EventProposal:
        if self.action != "RESEARCH_ONLY":
            raise ValueError("event proposals cannot publish or execute")
        if self.state is ApprovalState.APPROVED:
            if not self.approved_by or self.approved_by.casefold() == "ai":
                raise ValueError("AI cannot approve an event proposal")
        elif self.approved_by is not None:
            raise ValueError("only approved events may name an approver")
        return self


def assert_experiment_launchable(proposal: ExperimentProposal) -> None:
    if proposal.state is not ApprovalState.APPROVED:
        raise PermissionError("AQ-EXPERIMENT-PROPOSAL-NOT-APPROVED")
    require_budget(budget=proposal.approved_budget, request=proposal.requested_resources)
