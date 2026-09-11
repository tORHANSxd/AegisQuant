"""Complete, unfiltered base-opportunity labels; no strategy execution or ML fit."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal
from aegisquant.labels.generators import generate_return_path_label
from aegisquant.labels.models import CostAssumption, PricePathObservation, ReturnPathLabel
from aegisquant.research.validation.splits import SampleSpan


class BaseOpportunity(DomainModel):
    opportunity_id: str
    episode_id: str
    base_policy_sha256: str
    instrument_id: str
    decision_index: int = Field(ge=0)
    exit_index: int = Field(gt=0)
    feature_dependency_start: UtcDateTime
    decision_time: UtcDateTime
    exit_reason: Literal["TREND_EXIT", "RISK_EXIT", "FROZEN_TERMINAL_EXIT"]
    exit_reason_available_time: UtcDateTime
    capital_committed: NonNegativeDecimal
    accepted_by_ml: bool | None = None

    @model_validator(mode="after")
    def validate_opportunity(self) -> BaseOpportunity:
        ensure_sha256(self.base_policy_sha256, field_name="base policy")
        if not all(v.strip() for v in (self.opportunity_id, self.episode_id, self.instrument_id)):
            raise ValueError("opportunity identities cannot be empty")
        if (
            self.exit_index <= self.decision_index
            or self.feature_dependency_start > self.decision_time
        ):
            raise ValueError("opportunity must have a causal future exit")
        if self.exit_reason_available_time <= self.decision_time:
            raise ValueError("exit reason must be observed after the entry decision")
        return self


class EpisodeLabel(DomainModel):
    opportunity: BaseOpportunity
    span: SampleSpan
    return_path: ReturnPathLabel
    evidence_kind: Literal["COUNTERFACTUAL_FROZEN_BASE"] = "COUNTERFACTUAL_FROZEN_BASE"
    worth_accepting: bool
    capital_seconds: NonNegativeDecimal
    opportunity_set_sha256: str
    risk_exit_may_be_vetoed_by_ml: Literal[False] = False


def label_base_opportunities(
    *,
    opportunities: tuple[BaseOpportunity, ...],
    expected_opportunity_ids: tuple[str, ...],
    opportunity_set_sha256: str,
    observations: dict[str, tuple[PricePathObservation, ...]],
    costs: dict[str, CostAssumption],
    observed_through: UtcDateTime,
) -> tuple[EpisodeLabel, ...]:
    """The caller supplies a frozen complete opportunity ledger, including ML rejects.

    The hash binds the supplied ID set; it is not proof of empirical completeness.
    Counterfactual executable paths reuse the existing t+1, two-leg cost generator.
    """
    ids = tuple(item.opportunity_id for item in opportunities)
    if (
        len(ids) != len(set(ids))
        or len(expected_opportunity_ids) != len(set(expected_opportunity_ids))
        or set(ids) != set(expected_opportunity_ids)
    ):
        raise ValueError("must label the complete unfiltered opportunity set")
    if opportunity_set_sha256 != canonical_sha256(sorted(expected_opportunity_ids)):
        raise ValueError("frozen opportunity identity hash mismatch")
    output: list[EpisodeLabel] = []
    for item in sorted(opportunities, key=lambda x: (x.decision_time, x.opportunity_id)):
        path = observations[item.instrument_id]
        if (
            item.exit_index >= len(path)
            or path[item.decision_index].available_time != item.decision_time
        ):
            raise ValueError("opportunity path/decision identity mismatch")
        if any(
            p.instrument_id != item.instrument_id
            for p in path[item.decision_index : item.exit_index + 1]
        ):
            raise ValueError("opportunity path instrument mismatch")
        if item.exit_reason_available_time >= path[item.exit_index].event_time:
            raise ValueError("exit cannot precede the causal exit reason")
        available = max(
            item.exit_reason_available_time,
            *(p.available_time for p in path[item.decision_index + 1 : item.exit_index + 1]),
        )
        if available > observed_through:
            raise ValueError("episode label has not matured")
        label = generate_return_path_label(
            observations=path,
            decision_index=item.decision_index,
            horizon_steps=item.exit_index - item.decision_index,
            cost=costs[item.opportunity_id],
            risk_flat_threshold=Decimal(0),
        )
        output.append(
            EpisodeLabel(
                opportunity=item,
                span=SampleSpan(
                    sample_id=item.opportunity_id,
                    group_time=item.decision_time,
                    label_start_time=label.label_start_time,
                    label_end_time=label.label_end_time,
                    feature_dependency_start=item.feature_dependency_start,
                    label_available_time=available,
                    episode_id=item.episode_id,
                ),
                return_path=label,
                worth_accepting=label.net_return > 0,
                capital_seconds=item.capital_committed
                * Decimal(str((label.label_end_time - label.label_start_time).total_seconds())),
                opportunity_set_sha256=opportunity_set_sha256,
            )
        )
    return tuple(output)
