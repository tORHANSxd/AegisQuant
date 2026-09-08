from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import bars, engine, order, run_spec, spot_instrument, zero_cost_policy


def test_last_bar_revalues_an_open_position_without_a_new_order() -> None:
    values = list(bars(6))
    values[-1] = values[-1].model_copy(update={"close": Decimal("50"), "low": Decimal("49")})
    result = engine(zero_cost_policy()).run(
        spec=run_spec(),
        instrument=spot_instrument(),
        market_events=values,
        orders=(order(sequence=1, side=OrderSide.BUY),),
    )
    assert result.positions[0].mark_price == Decimal("50")
    assert result.mark_to_market_final_equity == Decimal("9949")
    assert result.forced_close_final_equity == Decimal("9949")
