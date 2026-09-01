"""Portfolio and independent risk action stress tests."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.risk.models import RiskAction, RiskState
from aegisquant.risk.stress import PortfolioStressScenario, run_portfolio_stress
from tests.p11_helpers import VENUE, proposal, risk_policy, snapshot


def test_price_correlation_liquidity_margin_and_venue_stress_change_action() -> None:
    portfolio = proposal()
    baseline = snapshot(portfolio=portfolio)
    reduce_result = run_portfolio_stress(
        proposal=portfolio,
        snapshot=baseline,
        policy=risk_policy(),
        scenario=PortfolioStressScenario(
            scenario_id="depeg-liquidity",
            asset_return_shocks={"BTC": Decimal("-0.30"), "ETH": Decimal("-0.25")},
            stablecoin_return_shocks={"USDT": Decimal("-0.10")},
            correlation_multiplier=Decimal("1.50"),
            liquidity_multiplier=Decimal("0.10"),
            margin_multiplier=Decimal("3"),
        ),
    )
    halted = run_portfolio_stress(
        proposal=portfolio,
        snapshot=baseline,
        policy=risk_policy(),
        scenario=PortfolioStressScenario(
            scenario_id="venue-loss",
            asset_return_shocks={"BTC": Decimal("-0.05"), "ETH": Decimal("-0.05")},
            stablecoin_return_shocks={},
            correlation_multiplier=Decimal("1"),
            liquidity_multiplier=Decimal("1"),
            margin_multiplier=Decimal("1"),
            unavailable_venues=(VENUE,),
        ),
    )
    assert reduce_result.state is RiskState.REDUCE_ONLY
    assert reduce_result.action is RiskAction.REDUCE
    assert halted.state is RiskState.HALTED
    assert halted.action is RiskAction.HALT
