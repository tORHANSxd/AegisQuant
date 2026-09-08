from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.portfolio.economic_gate import (
    EconomicAction,
    EconomicGatePolicy,
    decide_economic_transition,
)
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.models.economic_gate import CalibrationStatus, EconomicForecast
from tests.p06.helpers import NOW


def forecast(mean: str = "0.012") -> EconomicForecast:
    value = Decimal(mean)
    return EconomicForecast(
        expected_gross_return=value,
        q10_return=value - Decimal("0.002"),
        q50_return=value,
        q90_return=value + Decimal("0.002"),
        p_net_positive=Decimal("0.75"),
        prediction_uncertainty=Decimal("0.002"),
        available_time=NOW,
        calibration_status=CalibrationStatus.VALIDATION_CALIBRATED,
        calibrated_through=NOW - timedelta(days=1),
        calibration_sha256="a" * 64,
    )


def test_full_round_trip_hurdle_rises_with_volatility_and_liquidity_cost() -> None:
    actions: list[EconomicAction] = []
    hurdles: list[Decimal] = []
    for natr in ("0.01", "0.30"):
        costs = estimate_spot_transition_costs(
            available_time=NOW,
            natr=Decimal(natr),
            quote_volume=Decimal("10000000"),
            order_notional=Decimal("10000"),
        )
        decision = decide_economic_transition(
            policy=EconomicGatePolicy(),
            forecast=forecast(),
            costs=costs,
            decision_time=NOW,
            current_weight=Decimal("0"),
            trend_candidate=True,
            trend_exit_confirmed=False,
            data_quality_passed=True,
            risk_allows_entry=True,
            annualized_volatility=Decimal("0.20"),
        )
        actions.append(decision.action)
        hurdles.append(decision.entry_hurdle)
        assert decision.entry_hurdle > 2 * costs.entry.total
    assert actions == [EconomicAction.ENTER_LONG, EconomicAction.NO_TRADE]
    assert hurdles[1] > hurdles[0]


def test_future_execution_cost_estimate_is_rejected() -> None:
    costs = estimate_spot_transition_costs(
        available_time=NOW + timedelta(seconds=1),
        natr=Decimal("0.01"),
        quote_volume=Decimal("1000"),
        order_notional=Decimal("10"),
    )
    with pytest.raises(ValueError, match="future forecasts or costs"):
        decide_economic_transition(
            policy=EconomicGatePolicy(),
            forecast=forecast(),
            costs=costs,
            decision_time=NOW,
            current_weight=Decimal("0"),
            trend_candidate=True,
            trend_exit_confirmed=False,
            data_quality_passed=True,
            risk_allows_entry=True,
        )
