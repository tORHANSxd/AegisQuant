from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import bars, engine, order, run_spec, spot_instrument


def test_terminal_close_deducts_full_modelled_exit_cost_from_mtm() -> None:
    result = engine().run(
        spec=run_spec(),
        instrument=spot_instrument(),
        market_events=bars(6),
        orders=(order(sequence=1, side=OrderSide.BUY),),
    )
    assert result.forced_close_cost is not None
    assert result.mark_to_market_final_equity is not None
    assert (
        result.forced_close_final_equity
        == result.mark_to_market_final_equity - result.forced_close_cost.total
    )
    assert result.forced_close_cost.fee > 0
    assert result.forced_close_cost.spread > 0
    assert result.forced_close_cost.slippage > 0
    assert result.forced_close_cost.impact > Decimal("0")
