from decimal import Decimal

from aegisquant.backtest.models import EngineKind
from aegisquant.backtest.vector import VectorBacktestEngine
from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import bars, engine, order, run_spec, spot_instrument, zero_cost_policy


def test_sparse_orders_retain_every_market_event_and_final_valuation() -> None:
    values = bars(6)
    result = VectorBacktestEngine(engine(zero_cost_policy())).run(
        spec=run_spec(EngineKind.VECTOR),
        instrument=spot_instrument(),
        bars=values,
        orders=(order(sequence=1, side=OrderSide.BUY),),
    )
    assert result.events_processed == len(values)
    assert {point.time for point in result.equity_curve} == {bar.available_time for bar in values}
    assert result.positions[0].mark_price == Decimal("105")
    assert result.mark_to_market_final_equity == Decimal("10004")


def test_cash_baseline_accepts_no_orders() -> None:
    result = VectorBacktestEngine(engine(zero_cost_policy())).run(
        spec=run_spec(EngineKind.VECTOR),
        instrument=spot_instrument(),
        bars=bars(6),
        orders=(),
    )
    assert result.events_processed == 6
    assert all(point.equity == Decimal("10000") for point in result.equity_curve)
