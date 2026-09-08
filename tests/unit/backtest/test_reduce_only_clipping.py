from datetime import timedelta
from decimal import Decimal

from aegisquant.domain.execution import OrderSide, VenueOrderStatus
from tests.p06.helpers import NOW, bars, engine, order, run_spec, spot_instrument, zero_cost_policy


def test_reduce_only_excess_is_cancelled_without_opening_a_short() -> None:
    exit_order = order(
        sequence=2,
        side=OrderSide.SELL,
        quantity="10",
        submitted_at=NOW + timedelta(seconds=1, microseconds=1),
    ).model_copy(update={"reduce_only": True})
    result = engine(zero_cost_policy()).run(
        spec=run_spec(),
        instrument=spot_instrument(),
        market_events=bars(),
        orders=(order(sequence=1, side=OrderSide.BUY), exit_order),
    )
    exit_result = result.orders[1]
    assert exit_result.cumulative_filled_quantity == Decimal("1")
    assert exit_result.status is VenueOrderStatus.CANCELED
    assert exit_result.rejection_code == "AQ-BACKTEST-REDUCE-ONLY-EXCESS-CLIPPED"
    assert result.positions[0].quantity == 0


def test_reduce_only_cannot_open_from_flat_or_add_to_a_long() -> None:
    for existing in (False, True):
        reducing = order(
            sequence=2,
            side=OrderSide.BUY,
            submitted_at=NOW + timedelta(seconds=1, microseconds=1),
        ).model_copy(update={"reduce_only": True})
        orders = (order(sequence=1, side=OrderSide.BUY), reducing) if existing else (reducing,)
        result = engine(zero_cost_policy()).run(
            spec=run_spec(),
            instrument=spot_instrument(),
            market_events=bars(),
            orders=orders,
        )
        assert result.orders[-1].rejection_code == "AQ-BACKTEST-REDUCE-ONLY-NO-REDUCIBLE-POSITION"
        assert result.positions[0].quantity == int(existing)
