"""Vector/event consistency and deterministic replay acceptance evidence."""

from decimal import Decimal

from aegisquant.backtest.models import EngineKind
from aegisquant.backtest.vector import VectorBacktestEngine, buy_and_hold_benchmark
from tests.p06.helpers import bars, engine, run_spec, spot_instrument, zero_cost_policy


def test_zero_cost_immediate_fill_vector_and_event_engines_match() -> None:
    values = bars()
    instrument = spot_instrument()
    event_engine = engine(zero_cost_policy())
    orders = buy_and_hold_benchmark(bars=values, instrument=instrument, quantity=Decimal("1"))

    event_result = event_engine.run(
        spec=run_spec(EngineKind.EVENT, run_id="p06-consistency-event"),
        instrument=instrument,
        market_events=values,
        orders=orders,
    )
    vector_result = VectorBacktestEngine(event_engine).run(
        spec=run_spec(EngineKind.VECTOR, run_id="p06-consistency-vector"),
        instrument=instrument,
        bars=values,
        orders=orders,
    )

    assert [str(fill.source_event_id) for fill in event_result.fills] == ["bar-1", "bar-3"]
    assert event_result.fills == vector_result.fills
    assert event_result.positions == vector_result.positions
    assert event_result.equity_curve == vector_result.equity_curve
    assert event_result.pnl_attribution == vector_result.pnl_attribution
    assert event_result.economic_event_hash == vector_result.economic_event_hash
    assert all(fill.fee.amount == 0 for fill in event_result.fills)


def test_event_replay_is_byte_semantically_deterministic() -> None:
    values = bars()
    instrument = spot_instrument()
    event_engine = engine(zero_cost_policy())
    orders = buy_and_hold_benchmark(bars=values, instrument=instrument, quantity=Decimal("1"))
    spec = run_spec(EngineKind.EVENT, run_id="p06-replay-event")

    first = event_engine.run(
        spec=spec,
        instrument=instrument,
        market_events=values,
        orders=orders,
    )
    second = event_engine.run(
        spec=spec,
        instrument=instrument,
        market_events=values,
        orders=orders,
    )

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert first.economic_event_hash == second.economic_event_hash
