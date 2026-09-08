from decimal import Decimal

from aegisquant.domain.execution import OrderSide, TimeInForce
from tests.p06.helpers import engine, l2_book, order, run_spec, spot_instrument, zero_cost_policy


def test_second_order_cannot_reuse_consumed_best_depth_level() -> None:
    result = engine(zero_cost_policy()).run(
        spec=run_spec(),
        instrument=spot_instrument(),
        market_events=(l2_book(),),
        orders=(order(sequence=1, side=OrderSide.BUY), order(sequence=2, side=OrderSide.BUY)),
    )
    assert [fill.reference_price.amount for fill in result.fills] == [
        Decimal("100.01"),
        Decimal("100.02"),
    ]


def test_fok_cannot_partially_execute_after_another_order_consumes_depth() -> None:
    result = engine(zero_cost_policy()).run(
        spec=run_spec(),
        instrument=spot_instrument(),
        market_events=(l2_book(),),
        orders=(
            order(sequence=1, side=OrderSide.BUY),
            order(
                sequence=2, side=OrderSide.BUY, quantity="3", time_in_force=TimeInForce.FILL_OR_KILL
            ),
        ),
    )
    assert len(result.fills) == 1
    assert result.orders[1].cumulative_filled_quantity == 0


def test_duplicate_market_event_is_idempotent_and_cannot_refill_depth() -> None:
    event = l2_book()
    result = engine(zero_cost_policy()).run(
        spec=run_spec(),
        instrument=spot_instrument(),
        market_events=(event, event),
        orders=(order(sequence=1, side=OrderSide.BUY, quantity="4"),),
    )
    assert result.events_processed == 1
    assert sum(fill.quantity.amount for fill in result.fills) == Decimal("3")
