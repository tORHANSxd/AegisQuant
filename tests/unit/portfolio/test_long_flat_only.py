from decimal import Decimal

import pytest

from aegisquant.portfolio.economic_gate import (
    EconomicAction,
    EconomicGatePolicy,
    decide_economic_transition,
)
from aegisquant.portfolio.optimizer import target_quantity_adjustment
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from tests.p06.helpers import NOW
from tests.unit.portfolio.test_dynamic_economic_gate import forecast


def test_bearish_forecast_cannot_open_short() -> None:
    costs = estimate_spot_transition_costs(
        available_time=NOW,
        natr=Decimal("0.01"),
        quote_volume=Decimal("10000000"),
        order_notional=Decimal("10000"),
    )
    result = decide_economic_transition(
        policy=EconomicGatePolicy(),
        forecast=forecast("-0.1"),
        costs=costs,
        decision_time=NOW,
        current_weight=Decimal("0"),
        trend_candidate=False,
        trend_exit_confirmed=True,
        data_quality_passed=True,
        risk_allows_entry=True,
    )
    assert result.action is EconomicAction.NO_TRADE
    assert result.target_weight == 0
    with pytest.raises(ValueError, match="long/flat quantities"):
        target_quantity_adjustment(
            target_quantity=Decimal("-1"),
            current_quantity=Decimal("0"),
            signed_pending_quantity=Decimal("0"),
            price=Decimal("100"),
            quantity_step=Decimal("0.1"),
            minimum_notional=Decimal("10"),
        )
