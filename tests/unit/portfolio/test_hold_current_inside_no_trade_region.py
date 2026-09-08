from decimal import Decimal

import pytest

from aegisquant.portfolio.economic_gate import (
    EconomicAction,
    EconomicGatePolicy,
    decide_economic_transition,
)
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from tests.p06.helpers import NOW
from tests.unit.portfolio.test_dynamic_economic_gate import forecast


@pytest.mark.parametrize("mean", ("0.00001", "-0.00001"))
def test_tiny_forecast_changes_hold_current_position(mean: str) -> None:
    costs = estimate_spot_transition_costs(
        available_time=NOW,
        natr=Decimal("0.01"),
        quote_volume=Decimal("10000000"),
        order_notional=Decimal("10000"),
    )
    decision = decide_economic_transition(
        policy=EconomicGatePolicy(),
        forecast=forecast(mean),
        costs=costs,
        decision_time=NOW,
        current_weight=Decimal("0.6"),
        trend_candidate=True,
        trend_exit_confirmed=False,
        data_quality_passed=True,
        risk_allows_entry=True,
    )
    assert decision.action is EconomicAction.HOLD_CURRENT
    assert decision.target_weight == Decimal("0.6")
