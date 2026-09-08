"""Fair Model Council comparison with no complexity privilege."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.data.hashing import ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal
from aegisquant.research.models.baselines import ResearchModality


class CandidateState(StrEnum):
    EVALUATED = "EVALUATED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"


class CouncilDecision(StrEnum):
    SELECTED = "SELECTED"
    NO_PROVEN_ALPHA = "NO_PROVEN_ALPHA"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED_FOR_INSTABILITY = "REJECTED_FOR_INSTABILITY"


class CouncilCandidate(DomainModel):
    model_id: str
    family: str
    modality: ResearchModality
    target: str
    split_sha256: str
    cost_policy_sha256: str
    search_budget_sha256: str
    seed: int = Field(ge=0)
    state: CandidateState
    primary_loss: NonNegativeDecimal | None = None
    net_return: FiniteDecimal | None = None
    train_seconds: NonNegativeDecimal
    peak_memory_mb: NonNegativeDecimal
    abstain_or_failure_reason: str | None = None
    statistical_gate_passed: bool | None = None
    economic_gate_passed: bool | None = None
    cost_stress_gate_passed: bool | None = None
    stability_gate_passed: bool | None = None
    gate_evidence_sha256: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> CouncilCandidate:
        for value in (
            self.split_sha256,
            self.cost_policy_sha256,
            self.search_budget_sha256,
        ):
            ensure_sha256(value, field_name="council comparison hash")
        if self.state is CandidateState.EVALUATED:
            if self.primary_loss is None or self.net_return is None:
                raise ValueError("evaluated council candidate requires metrics")
            if self.abstain_or_failure_reason is not None:
                raise ValueError("evaluated council candidate cannot have failure reason")
        elif not self.abstain_or_failure_reason:
            raise ValueError("non-evaluated council candidate requires reason")
        if self.gate_evidence_sha256 is not None:
            ensure_sha256(self.gate_evidence_sha256, field_name="council gate evidence")
        return self

    @property
    def all_gates_passed(self) -> bool:
        return (
            self.state is CandidateState.EVALUATED
            and self.net_return is not None
            and self.net_return > 0
            and self.gate_evidence_sha256 is not None
            and all(
                gate is True
                for gate in (
                    self.statistical_gate_passed,
                    self.economic_gate_passed,
                    self.cost_stress_gate_passed,
                    self.stability_gate_passed,
                )
            )
        )


class CouncilReport(DomainModel):
    candidates: tuple[CouncilCandidate, ...]
    baseline_model_id: str
    selected_model_id: str | None
    decision: CouncilDecision
    reason: str
    new_positions_allowed: bool = False
    rejected_model_ids: tuple[str, ...]
    fair_comparison: bool
    complexity_privilege: bool = False
    final_holdout_opened: bool = False

    @model_validator(mode="after")
    def enforce_safety(self) -> CouncilReport:
        if self.complexity_privilege or self.final_holdout_opened:
            raise ValueError("council cannot privilege complexity or open final holdout")
        selected = self.decision is CouncilDecision.SELECTED
        if (
            selected != (self.selected_model_id is not None)
            or selected != self.new_positions_allowed
        ):
            raise ValueError("council decision and position permission disagree")
        if selected and not any(
            item.model_id == self.selected_model_id and item.all_gates_passed
            for item in self.candidates
        ):
            raise ValueError("selected candidate must pass every evidenced promotion gate")
        return self


def run_model_council(
    *,
    candidates: tuple[CouncilCandidate, ...],
    baseline_model_id: str,
    minimum_incremental_improvement: Decimal,
) -> CouncilReport:
    if not candidates or len({item.model_id for item in candidates}) != len(candidates):
        raise ValueError("model council requires unique nonempty candidates")
    if minimum_incremental_improvement < 0:
        raise ValueError("incremental improvement cannot be negative")
    if baseline_model_id not in {item.model_id for item in candidates}:
        raise ValueError("model council baseline is absent")
    comparison_keys = {
        (item.split_sha256, item.cost_policy_sha256, item.search_budget_sha256, item.seed)
        for item in candidates
    }
    if len(comparison_keys) != 1 or len({item.target for item in candidates}) != 1:
        raise ValueError("model council candidates do not share split, cost, budget, seed, target")
    evaluated = tuple(item for item in candidates if item.state is CandidateState.EVALUATED)
    eligible = tuple(item for item in evaluated if item.all_gates_passed)
    best: CouncilCandidate | None = None
    decision = CouncilDecision.INSUFFICIENT_EVIDENCE
    reason = "No candidate has complete statistical, economic, stress and stability evidence."
    if eligible:
        best = max(eligible, key=lambda item: (item.net_return, item.model_id == baseline_model_id))
        baseline = next((item for item in eligible if item.model_id == baseline_model_id), None)
        if (
            baseline is not None
            and best.model_id != baseline_model_id
            and (
                best.net_return is not None
                and baseline.net_return is not None
                and best.net_return - baseline.net_return < minimum_incremental_improvement
            )
        ):
            best = baseline
        decision = CouncilDecision.SELECTED
        reason = "Positive net return and all four evidenced gates passed; complexity grants no preference."
    elif evaluated and all(
        item.net_return is not None and item.net_return <= 0 for item in evaluated
    ):
        decision = CouncilDecision.NO_PROVEN_ALPHA
        reason = "All evaluated candidates have nonpositive net returns."
    elif any(item.stability_gate_passed is False for item in evaluated):
        decision = CouncilDecision.REJECTED_FOR_INSTABILITY
        reason = "Observed instability prevents selection."
    elif any(
        item.economic_gate_passed is False
        or item.cost_stress_gate_passed is False
        or item.statistical_gate_passed is False
        for item in evaluated
    ):
        decision = CouncilDecision.NO_PROVEN_ALPHA
        reason = "Available evidence fails a required economic, stress or statistical gate."
    return CouncilReport(
        candidates=candidates,
        baseline_model_id=baseline_model_id,
        selected_model_id=best.model_id if best is not None else None,
        decision=decision,
        reason=reason,
        new_positions_allowed=best is not None,
        rejected_model_ids=tuple(
            item.model_id for item in candidates if best is None or item.model_id != best.model_id
        ),
        fair_comparison=True,
    )
