from datetime import timedelta

from aegisquant.domain.execution import OrderSide, VenueOrderStatus
from tests.p06.helpers import (
    NOW,
    bars,
    engine,
    order,
    perp_bars,
    perp_instrument,
    perp_order,
    run_spec,
    spot_instrument,
    zero_cost_policy,
)


def test_spot_cannot_spend_unfunded_cash_or_sell_unborrowed_inventory() -> None:
    for side, code in (
        (OrderSide.BUY, "AQ-BACKTEST-SPOT-INSUFFICIENT-CASH"),
        (OrderSide.SELL, "AQ-BACKTEST-SPOT-INSUFFICIENT-INVENTORY"),
    ):
        result = engine(zero_cost_policy()).run(
            spec=run_spec(initial_cash="100"),
            instrument=spot_instrument(),
            market_events=bars(),
            orders=(order(sequence=1, side=side),),
        )
        assert not result.fills
        assert result.orders[0].status is VenueOrderStatus.REJECTED
        assert result.orders[0].rejection_code == code
        assert result.equity_curve[-1].equity == 100


def test_perpetual_initial_margin_is_checked_before_opening() -> None:
    result = engine(zero_cost_policy()).run(
        spec=run_spec(initial_cash="10"),
        instrument=perp_instrument(),
        market_events=perp_bars(),
        orders=(
            perp_order(
                sequence=1,
                side=OrderSide.BUY,
                quantity="10",
                submitted_at=NOW + timedelta(microseconds=1),
            ),
        ),
    )
    assert not result.fills
    assert result.orders[0].rejection_code == "AQ-BACKTEST-INITIAL-MARGIN-INSUFFICIENT"
