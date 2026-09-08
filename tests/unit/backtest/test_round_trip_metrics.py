from datetime import timedelta
from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import NOW, bars, engine, order, run_spec, spot_instrument, zero_cost_policy


def test_fragmented_entry_and_exit_count_as_one_closed_losing_trade() -> None:
    values = list(bars(6, volume="100"))
    values[4] = values[4].model_copy(
        update={
            "open": Decimal("99"),
            "close": Decimal("99"),
            "low": Decimal("98"),
            "high": Decimal("100"),
        }
    )
    result = engine(zero_cost_policy()).run(
        spec=run_spec().model_copy(update={"metric_frequency_seconds": 1}),
        instrument=spot_instrument(),
        market_events=values,
        orders=(
            order(sequence=1, side=OrderSide.BUY),
            order(sequence=2, side=OrderSide.BUY),
            order(
                sequence=3,
                side=OrderSide.SELL,
                quantity="2",
                submitted_at=NOW + timedelta(seconds=3, microseconds=1),
            ),
        ),
    )
    assert result.metrics.trade_statistics.closed_trade_count == 1
    assert result.metrics.hit_rate == 0
    assert result.metrics.trade_statistics.average_loss == Decimal("4")
    assert result.closed_trades[0].net_pnl == Decimal("-4")


def test_open_marked_profit_is_not_a_winning_closed_trade() -> None:
    result = engine(zero_cost_policy()).run(
        spec=run_spec(),
        instrument=spot_instrument(),
        market_events=bars(),
        orders=(order(sequence=1, side=OrderSide.BUY),),
    )
    assert result.metrics.total_return > 0
    assert result.metrics.trade_statistics.closed_trade_count == 0
    assert result.metrics.hit_rate == 0
