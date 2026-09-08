from datetime import timedelta
from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import (
    NOW,
    engine,
    perp_bars,
    perp_instrument,
    perp_order,
    run_spec,
    zero_cost_policy,
)


def test_market_gap_automatically_liquidates_and_books_one_penalty() -> None:
    result = engine(zero_cost_policy()).run(
        spec=run_spec(initial_cash="100"),
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
    liquidations = [
        order
        for order in result.orders
        if str(order.order.backtest_order_id).startswith("liquidation:")
    ]
    assert len(liquidations) == 1
    assert liquidations[0].order.reduce_only
    assert result.positions[0].quantity == 0
    assert result.fills[-1].reference_price.amount == Decimal("80")
    assert result.fills[-1].execution_price.amount == Decimal("80")
    assert result.pnl_attribution[-1].liquidation_penalties == Decimal("4")
    assert result.equity_curve[-1].equity == Decimal("-104")
    assert result.cost_identity_residual == 0


def test_intrabar_maintenance_breach_cannot_hide_behind_recovered_close() -> None:
    values = list(perp_bars())
    for i in (2, 3):
        values[i] = values[i].model_copy(
            update={
                "open": Decimal("100"),
                "close": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("92") if i == 2 else Decimal("99"),
            }
        )
    result = engine(zero_cost_policy()).run(
        spec=run_spec(initial_cash="100"),
        instrument=perp_instrument(),
        market_events=values,
        orders=(
            perp_order(
                sequence=1,
                side=OrderSide.BUY,
                quantity="10",
                submitted_at=NOW + timedelta(microseconds=1),
            ),
        ),
    )
    assert result.positions[0].quantity == 0
    assert result.fills[-1].reference_price.amount == Decimal("92")
    assert result.equity_curve[-1].equity == Decimal("15.4")
