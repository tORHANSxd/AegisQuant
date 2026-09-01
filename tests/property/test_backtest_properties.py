"""Property checks for adverse cost direction and deterministic arithmetic."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from aegisquant.backtest.costs import execution_price_and_cost
from aegisquant.backtest.models import FillPrecision, FillSlice, LiquidityRole
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import BacktestEventId
from tests.p06.helpers import NOW, USDT, order, policy


@settings(max_examples=50, deadline=None)
@given(
    quantity=st.decimals(min_value="0.001", max_value="10", places=3, allow_nan=False),
    reference=st.decimals(min_value="1", max_value="100000", places=2, allow_nan=False),
    side=st.sampled_from((OrderSide.BUY, OrderSide.SELL)),
)
def test_nonnegative_cost_model_is_always_adverse_and_deterministic(
    quantity: Decimal, reference: Decimal, side: OrderSide
) -> None:
    candidate = order(sequence=1, side=side, quantity=str(quantity))
    fill_slice = FillSlice(
        quantity=quantity,
        reference_price=reference,
        available_liquidity=quantity * Decimal("2"),
        precision=FillPrecision.L2_DEPTH,
        liquidity_role=LiquidityRole.TAKER,
        source_event_id=BacktestEventId("property-cost-event"),
        event_time=NOW,
        available_time=NOW,
    )

    first = execution_price_and_cost(
        order=candidate,
        fill_slice=fill_slice,
        schedule=policy().cost_schedules[0],
        base_asset_id=candidate.quantity.asset_id,
        quote_asset_id=USDT,
    )
    second = execution_price_and_cost(
        order=candidate,
        fill_slice=fill_slice,
        schedule=policy().cost_schedules[0],
        base_asset_id=candidate.quantity.asset_id,
        quote_asset_id=USDT,
    )

    assert first == second
    if side is OrderSide.BUY:
        assert first[0].amount >= reference
    else:
        assert first[0].amount <= reference
    assert first[1].fee >= 0
    assert first[1].spread >= 0
    assert first[1].slippage >= 0
    assert first[1].impact >= 0
