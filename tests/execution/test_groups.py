"""Multi-leg naked-exposure limits and hedge actions."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.execution import OrderSide
from aegisquant.execution.groups import (
    ExecutionGroup,
    ExecutionGroupLeg,
    ExecutionGroupPolicy,
    GroupAction,
    evaluate_group_exposure,
    record_group_fill,
)
from tests.p12_helpers import INSTRUMENT, NOW, USDT


def group() -> ExecutionGroup:
    return ExecutionGroup(
        execution_group_id="group-p12",
        notional_asset_id=USDT,
        created_at=NOW,
        legs=(
            ExecutionGroupLeg(
                leg_id="long",
                instrument_id=INSTRUMENT,
                side=OrderSide.BUY,
                target_notional=Decimal("100"),
            ),
            ExecutionGroupLeg(
                leg_id="short",
                instrument_id=INSTRUMENT.__class__("ETH-USDT-PERP"),
                side=OrderSide.SELL,
                target_notional=Decimal("100"),
            ),
        ),
        policy=ExecutionGroupPolicy(
            maximum_naked_notional=Decimal("50"),
            maximum_naked_seconds=10,
            halt_notional=Decimal("90"),
        ),
    )


def test_unbalanced_partial_group_requires_hedge_or_halt() -> None:
    partial = record_group_fill(group(), leg_id="long", fill_notional=Decimal("60"))
    assert (
        evaluate_group_exposure(partial, evaluated_at=NOW + timedelta(seconds=1)).action
        is GroupAction.HEDGE
    )
    larger = record_group_fill(group(), leg_id="long", fill_notional=Decimal("95"))
    assert (
        evaluate_group_exposure(larger, evaluated_at=NOW + timedelta(seconds=1)).action
        is GroupAction.HALT
    )


def test_balanced_group_completes_without_naked_exposure() -> None:
    completed = record_group_fill(group(), leg_id="long", fill_notional=Decimal("100"))
    completed = record_group_fill(completed, leg_id="short", fill_notional=Decimal("100"))
    decision = evaluate_group_exposure(completed, evaluated_at=NOW + timedelta(seconds=2))
    assert decision.action is GroupAction.COMPLETE
    assert decision.naked_notional == 0


def test_group_leg_overfill_is_rejected() -> None:
    with pytest.raises(ValueError, match="OVERFILL"):
        record_group_fill(group(), leg_id="long", fill_notional=Decimal("101"))
