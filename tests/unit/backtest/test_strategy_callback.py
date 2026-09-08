from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.backtest.models import (
    BacktestDecisionContext,
    BacktestDecisionUpdate,
    CancelRequest,
)
from aegisquant.domain.execution import OrderSide, VenueOrderStatus
from tests.p06.helpers import NOW, bars, engine, order, run_spec, spot_instrument, zero_cost_policy


def test_closed_bar_callback_sees_current_ledger_and_fills_only_next_event() -> None:
    events = tuple(
        b.model_copy(
            update={
                "event_time": NOW + timedelta(minutes=i),
                "available_time": NOW + timedelta(minutes=i, seconds=59),
            }
        )
        for i, b in enumerate(bars(3))
    )
    observed: list[Decimal] = []

    def callback(context: BacktestDecisionContext) -> BacktestDecisionUpdate:
        observed.append(context.position_quantity)
        if context.event is events[0]:
            return BacktestDecisionUpdate(
                orders=(
                    order(
                        sequence=1, side=OrderSide.BUY, submitted_at=context.event.available_time
                    ),
                )
            )
        return BacktestDecisionUpdate()

    result = engine(zero_cost_policy()).run(
        spec=run_spec(end_time=NOW + timedelta(minutes=3)),
        instrument=spot_instrument(),
        market_events=events,
        orders=(),
        decision_callback=callback,
    )
    assert observed == [0, 1, 1]
    assert len(result.fills) == 1
    assert result.fills[0].event_time == events[1].event_time
    assert result.fills[0].reference_price.amount == events[1].open
    assert result.fills[0].event_time > result.orders[0].order.decision_time


def test_callback_rejects_backdated_order() -> None:
    def callback(context: BacktestDecisionContext) -> BacktestDecisionUpdate:
        return BacktestDecisionUpdate(
            orders=(
                order(
                    sequence=1,
                    side=OrderSide.BUY,
                    submitted_at=context.event.available_time - timedelta(seconds=1),
                ),
            )
        )

    with pytest.raises(ValueError, match="BACKDATED"):
        engine(zero_cost_policy()).run(
            spec=run_spec(),
            instrument=spot_instrument(),
            market_events=bars(),
            orders=(),
            decision_callback=callback,
        )


def test_cancel_during_bar_cannot_erase_prior_open_fill() -> None:
    first = bars(1)[0].model_copy(update={"available_time": NOW + timedelta(seconds=59)})
    placed = order(sequence=1, side=OrderSide.BUY, submitted_at=NOW - timedelta(seconds=1))
    result = engine(zero_cost_policy()).run(
        spec=run_spec(end_time=NOW + timedelta(minutes=1)),
        instrument=spot_instrument(),
        market_events=(first,),
        orders=(placed,),
        cancel_requests=(
            CancelRequest(
                backtest_order_id=placed.backtest_order_id, requested_at=NOW + timedelta(seconds=30)
            ),
        ),
    )
    assert len(result.fills) == 1
    assert result.orders[0].status is VenueOrderStatus.FILLED


def test_callback_cancels_pending_order_before_next_eligible_event() -> None:
    events = tuple(
        b.model_copy(
            update={
                "event_time": NOW + timedelta(minutes=i),
                "available_time": NOW + timedelta(minutes=i, seconds=59),
            }
        )
        for i, b in enumerate(bars(3))
    )

    def callback(context: BacktestDecisionContext) -> BacktestDecisionUpdate:
        if context.event is events[0]:
            placed = order(
                sequence=1, side=OrderSide.BUY, submitted_at=NOW + timedelta(minutes=2)
            ).model_copy(update={"decision_time": context.event.available_time})
            return BacktestDecisionUpdate(orders=(placed,))
        if context.pending_orders:
            assert context.signed_pending_quantity == 1
            return BacktestDecisionUpdate(
                cancel_order_ids=tuple(p.backtest_order_id for p in context.pending_orders)
            )
        return BacktestDecisionUpdate()

    result = engine(zero_cost_policy()).run(
        spec=run_spec(end_time=NOW + timedelta(minutes=3)),
        instrument=spot_instrument(),
        market_events=events,
        orders=(),
        decision_callback=callback,
    )
    assert not result.fills
    assert result.orders[0].status is VenueOrderStatus.CANCELED
