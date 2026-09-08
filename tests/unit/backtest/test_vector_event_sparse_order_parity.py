from aegisquant.backtest.models import EngineKind
from aegisquant.backtest.vector import VectorBacktestEngine
from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import bars, engine, order, run_spec, spot_instrument


def test_sparse_partial_fills_preserve_event_vector_equity_and_costs() -> None:
    values = bars(6, volume="2")
    orders = (order(sequence=1, side=OrderSide.BUY, quantity="2"),)
    event_engine = engine()
    event = event_engine.run(
        spec=run_spec(), instrument=spot_instrument(), market_events=values, orders=orders
    )
    vector = VectorBacktestEngine(event_engine).run(
        spec=run_spec(EngineKind.VECTOR),
        instrument=spot_instrument(),
        bars=values,
        orders=orders,
    )
    assert vector.equity_curve == event.equity_curve
    assert vector.fills == event.fills
    assert vector.metrics == event.metrics
    assert vector.forced_close_final_equity == event.forced_close_final_equity
