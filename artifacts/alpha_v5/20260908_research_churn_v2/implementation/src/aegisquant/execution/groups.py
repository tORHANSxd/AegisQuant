"""Multi-leg execution group exposure accounting and fail-safe actions."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import AssetId, InstrumentId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal, PositiveDecimal, canonical_result


class GroupAction(StrEnum):
    CONTINUE = "CONTINUE"
    HEDGE = "HEDGE"
    HALT = "HALT"
    COMPLETE = "COMPLETE"


class ExecutionGroupLeg(DomainModel):
    leg_id: str = Field(min_length=1, max_length=255)
    instrument_id: InstrumentId
    side: OrderSide
    target_notional: PositiveDecimal
    filled_notional: NonNegativeDecimal = Decimal("0")

    @model_validator(mode="after")
    def validate_fill(self) -> ExecutionGroupLeg:
        if self.filled_notional > self.target_notional:
            raise ValueError("execution group leg overfill")
        return self


class ExecutionGroupPolicy(DomainModel):
    maximum_naked_notional: NonNegativeDecimal
    maximum_naked_seconds: int = Field(ge=0)
    halt_notional: PositiveDecimal

    @model_validator(mode="after")
    def validate_limits(self) -> ExecutionGroupPolicy:
        if self.halt_notional < self.maximum_naked_notional:
            raise ValueError("halt notional must not be below hedge threshold")
        return self


class ExecutionGroup(DomainModel):
    execution_group_id: str = Field(min_length=1, max_length=255)
    notional_asset_id: AssetId
    created_at: UtcDateTime
    legs: tuple[ExecutionGroupLeg, ...] = Field(min_length=2)
    policy: ExecutionGroupPolicy

    @model_validator(mode="after")
    def validate_legs(self) -> ExecutionGroup:
        if len({leg.leg_id for leg in self.legs}) != len(self.legs):
            raise ValueError("execution group leg ids must be unique")
        return self


class GroupExposureDecision(DomainModel):
    execution_group_id: str
    naked_notional: NonNegativeDecimal
    elapsed_seconds: int = Field(ge=0)
    action: GroupAction
    reason_code: str


def record_group_fill(
    group: ExecutionGroup,
    *,
    leg_id: str,
    fill_notional: PositiveDecimal,
) -> ExecutionGroup:
    matched = False
    updated: list[ExecutionGroupLeg] = []
    for leg in group.legs:
        if leg.leg_id != leg_id:
            updated.append(leg)
            continue
        matched = True
        cumulative = canonical_result(leg.filled_notional + fill_notional)
        if cumulative > leg.target_notional:
            raise ValueError("AQ-EXEC-GROUP-LEG-OVERFILL")
        updated.append(leg.model_copy(update={"filled_notional": cumulative}))
    if not matched:
        raise ValueError("AQ-EXEC-GROUP-LEG-NOT-FOUND")
    return group.model_copy(update={"legs": tuple(updated)})


def evaluate_group_exposure(
    group: ExecutionGroup, *, evaluated_at: UtcDateTime
) -> GroupExposureDecision:
    if evaluated_at < group.created_at:
        raise ValueError("group evaluation cannot precede creation")
    signed = sum(
        (
            leg.filled_notional if leg.side is OrderSide.BUY else -leg.filled_notional
            for leg in group.legs
        ),
        start=Decimal("0"),
    )
    naked = canonical_result(abs(signed))
    elapsed = int((evaluated_at - group.created_at).total_seconds())
    complete = all(leg.filled_notional == leg.target_notional for leg in group.legs)
    if naked >= group.policy.halt_notional:
        action, reason = GroupAction.HALT, "AQ-EXEC-GROUP-NAKED-HALT"
    elif naked > group.policy.maximum_naked_notional or (
        naked > 0 and elapsed > group.policy.maximum_naked_seconds
    ):
        action, reason = GroupAction.HEDGE, "AQ-EXEC-GROUP-HEDGE-REQUIRED"
    elif complete:
        action, reason = GroupAction.COMPLETE, "AQ-EXEC-GROUP-COMPLETE"
    else:
        action, reason = GroupAction.CONTINUE, "AQ-EXEC-GROUP-WITHIN-LIMIT"
    return GroupExposureDecision(
        execution_group_id=group.execution_group_id,
        naked_notional=naked,
        elapsed_seconds=elapsed,
        action=action,
        reason_code=reason,
    )
