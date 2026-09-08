from datetime import timedelta
from decimal import Decimal

from aegisquant.backtest.models import ExitTrigger
from aegisquant.domain.execution import OrderSide, VenueOrderStatus
from aegisquant.domain.values import Price
from tests.p06.helpers import (
    BTC,
    NOW,
    USDT,
    bars,
    engine,
    order,
    run_spec,
    spot_instrument,
    zero_cost_policy,
)


def test_bar_touching_both_exits_fills_stop_only_regardless_of_input_order() -> None:
    values = list(bars(4))
    values[2] = values[2].model_copy(
        update={
            "open": Decimal("100"),
            "close": Decimal("100"),
            "low": Decimal("90"),
            "high": Decimal("120"),
        }
    )
    exits = tuple(
        order(
            sequence=sequence,
            side=OrderSide.SELL,
            submitted_at=NOW + timedelta(seconds=1, microseconds=1),
        ).model_copy(
            update={
                "reduce_only": True,
                "exit_trigger": trigger,
                "oco_group_id": "bracket-1",
                "trigger_price": Price(
                    amount=Decimal(price), base_asset_id=BTC, quote_asset_id=USDT
                ),
            }
        )
        for sequence, trigger, price in (
            (2, ExitTrigger.TAKE_PROFIT, "110"),
            (3, ExitTrigger.STOP_LOSS, "95"),
        )
    )
    result = engine(zero_cost_policy()).run(
        spec=run_spec(),
        instrument=spot_instrument(),
        market_events=values,
        orders=(order(sequence=1, side=OrderSide.BUY), *exits),
    )
    assert len(result.fills) == 2
    assert result.fills[-1].execution_price.amount == Decimal("95")
    assert result.orders[1].status is VenueOrderStatus.CANCELED
    assert result.orders[1].rejection_code == "AQ-BACKTEST-OCO-SIBLING-TRIGGERED"
    assert result.positions[0].quantity == 0
