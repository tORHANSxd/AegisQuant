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
        return self


class CouncilReport(DomainModel):
    candidates: tuple[CouncilCandidate, ...]
    baseline_model_id: str
    selected_model_id: str
    rejected_model_ids: tuple[str, ...]
    fair_comparison: bool
    complexity_privilege: bool = False
    final_holdout_opened: bool = False

    @model_validator(mode="after")
    def enforce_safety(self) -> CouncilReport:
        if self.complexity_privilege or self.final_holdout_opened:
            raise ValueError("council cannot privilege complexity or open final holdout")
        return self


def run_model_council(
    *,
    candidates: tuple[CouncilCandidate, ...],
    baseline_model_id: str,
    minimum_incremental_improvement: Decimal,
) -> CouncilReport:
    if len(candidates) < 3 or len({item.model_id for item in candidates}) != len(candidates):
        raise ValueError("model council requires at least three unique candidates")
    comparison_keys = {
        (item.split_sha256, item.cost_policy_sha256, item.search_budget_sha256, item.seed)
        for item in candidates
    }
    if len(comparison_keys) != 1 or len({item.target for item in candidates}) != 1:
        raise ValueError("model council candidates do not share split, cost, budget, seed, target")
    if {item.modality for item in candidates} != set(ResearchModality):
        raise ValueError("model council requires Market-only, Event-only, and Fused candidates")
    evaluated = tuple(item for item in candidates if item.state is CandidateState.EVALUATED)
    if not evaluated:
        raise ValueError("model council has no evaluated candidates")
    try:
        baseline = next(item for item in evaluated if item.model_id == baseline_model_id)
    except StopIteration as error:
        raise ValueError("model council baseline must be evaluated") from error
    best = min(evaluated, key=lambda item: (item.primary_loss, item.model_id))
    if best.model_id != baseline_model_id and (
        baseline.primary_loss is None
        or best.primary_loss is None
        or baseline.primary_loss - best.primary_loss < minimum_incremental_improvement
    ):
        best = baseline
    return CouncilReport(
        candidates=candidates,
        baseline_model_id=baseline_model_id,
        selected_model_id=best.model_id,
        rejected_model_ids=tuple(
            item.model_id for item in candidates if item.model_id != best.model_id
        ),
        fair_comparison=True,
    )
