from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import bars, engine, order, run_spec, spot_instrument, zero_cost_policy


def test_mark_dip_without_any_fill_is_in_drawdown() -> None:
    values = list(bars(6, volume="100"))
    values[3] = values[3].model_copy(
        update={
            "open": Decimal("50"),
            "close": Decimal("50"),
            "low": Decimal("49"),
            "high": Decimal("51"),
        }
    )
    result = engine(zero_cost_policy()).run(
        spec=run_spec().model_copy(update={"metric_frequency_seconds": 1}),
        instrument=spot_instrument(),
        market_events=values,
        orders=(order(sequence=1, side=OrderSide.BUY, quantity="50"),),
    )
    assert len(result.fills) == 1
    assert result.metrics.maximum_drawdown > Decimal("0.25")
    assert len(result.equity_curve) == 6
