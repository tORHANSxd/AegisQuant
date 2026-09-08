from datetime import timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from aegisquant.backtest.models import BacktestResult, SpotBorrowPolicy
from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import NOW, bars, engine, order, run_spec, spot_instrument, zero_cost_policy


@settings(max_examples=25, deadline=None)
@given(held=st.integers(1, 10), requested=st.integers(1, 30), long=st.booleans())
def test_reduce_only_never_increases_or_reverses_absolute_position(
    held: int,
    requested: int,
    long: bool,
) -> None:
    entry_side = OrderSide.BUY if long else OrderSide.SELL
    exit_side = OrderSide.SELL if long else OrderSide.BUY
    result = engine(zero_cost_policy()).run(
        spec=run_spec().model_copy(
            update={
                "spot_borrow_policy": SpotBorrowPolicy(
                    maximum_quantity=Decimal("20"),
                    source="bounded property fixture",
                )
            }
        ),
        instrument=spot_instrument(),
        market_events=bars(4, volume="100"),
        orders=(
            order(sequence=1, side=entry_side, quantity=str(held)),
            order(
                sequence=2,
                side=exit_side,
                quantity=str(requested),
                submitted_at=NOW + timedelta(seconds=1, microseconds=1),
            ).model_copy(update={"reduce_only": True}),
        ),
    )
    remaining = max(0, held - requested)
    assert result.positions[0].quantity == (remaining if long else -remaining)
    assert sum(fill.quantity.amount for fill in result.fills if fill.side is exit_side) <= held


@settings(max_examples=25, deadline=None)
@given(base=st.integers(0, 30), extra=st.integers(0, 30))
def test_higher_fees_and_slippage_cannot_improve_net_pnl_on_the_same_fills(
    base: int,
    extra: int,
) -> None:
    results: list[BacktestResult] = []
    for bps in (base, base + extra):
        policy = zero_cost_policy()
        policy = policy.model_copy(
            update={
                "cost_schedules": tuple(
                    schedule.model_copy(
                        update={
                            "taker_fee_bps": Decimal(bps),
                            "slippage_bps": Decimal(bps),
                        }
                    )
                    for schedule in policy.cost_schedules
                )
            }
        )
        results.append(
            engine(policy).run(
                spec=run_spec(),
                instrument=spot_instrument(),
                market_events=bars(4, volume="100"),
                orders=(
                    order(sequence=1, side=OrderSide.BUY),
                    order(
                        sequence=2,
                        side=OrderSide.SELL,
                        submitted_at=NOW + timedelta(seconds=1, microseconds=1),
                    ),
                ),
            )
        )
    assert [(fill.source_event_id, fill.quantity) for fill in results[0].fills] == [
        (fill.source_event_id, fill.quantity) for fill in results[1].fills
    ]
    assert results[1].equity_curve[-1].equity <= results[0].equity_curve[-1].equity
