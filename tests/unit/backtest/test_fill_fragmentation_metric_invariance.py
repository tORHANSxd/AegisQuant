from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import bars, engine, order, run_spec, spot_instrument, zero_cost_policy


def test_same_timestamp_split_orders_do_not_change_fixed_frequency_risk_metrics() -> None:
    def run(split: bool):
        orders = tuple(
            order(sequence=i + 1, side=OrderSide.BUY, quantity="1" if split else "2")
            for i in range(2 if split else 1)
        )
        return engine(zero_cost_policy()).run(
            spec=run_spec().model_copy(update={"metric_frequency_seconds": 1}),
            instrument=spot_instrument(),
            market_events=bars(6),
            orders=orders,
        )

    whole, fragmented = run(False), run(True)
    assert whole.equity_curve == fragmented.equity_curve
    assert whole.metrics.sharpe == fragmented.metrics.sharpe
    assert whole.metrics.maximum_drawdown == fragmented.metrics.maximum_drawdown
    assert whole.mark_to_market_final_equity == Decimal("10008")
