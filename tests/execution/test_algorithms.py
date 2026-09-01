"""Cost-aware maker/taker and exact TWAP slicing."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from aegisquant.domain.values import Quantity
from aegisquant.execution.algorithms import (
    ExecutionStyle,
    MarketExecutionQuote,
    build_twap_slices,
    choose_maker_or_taker,
    protected_limit_price,
)
from tests.p12_helpers import BTC, NOW, reference_price


def quote(*, passive_nonfill: str = "1") -> MarketExecutionQuote:
    return MarketExecutionQuote(
        bid=reference_price(Decimal("49990")),
        ask=reference_price(Decimal("50010")),
        maker_fee_bps=Decimal("-1"),
        taker_fee_bps=Decimal("4"),
        estimated_taker_impact_bps=Decimal("2"),
        passive_nonfill_cost_bps=Decimal(passive_nonfill),
        available_at=NOW,
    )


def test_maker_taker_choice_uses_total_expected_cost() -> None:
    maker = choose_maker_or_taker(
        quote=quote(), maximum_passive_cost_bps=Decimal("10"), reduce_only=False
    )
    taker = choose_maker_or_taker(
        quote=quote(passive_nonfill="20"),
        maximum_passive_cost_bps=Decimal("10"),
        reduce_only=False,
    )
    assert maker.style is ExecutionStyle.MAKER
    assert taker.style is ExecutionStyle.TAKER


def test_twap_preserves_exact_total_and_time_bounds() -> None:
    slices = build_twap_slices(
        total_quantity=Quantity(amount=Decimal("1"), asset_id=BTC),
        slice_count=3,
        start_at=NOW,
        interval_seconds=30,
        passive_seconds=20,
    )
    assert sum((item.quantity.amount for item in slices), start=Decimal("0")) == Decimal("1")
    assert [item.sequence for item in slices] == [0, 1, 2]
    assert all(item.expire_at > item.release_at for item in slices)


def test_reduce_only_protected_price_is_side_aware() -> None:
    buy = protected_limit_price(side=OrderSide.BUY, quote=quote(), protection_bps=Decimal("100"))
    sell = protected_limit_price(side=OrderSide.SELL, quote=quote(), protection_bps=Decimal("100"))
    assert buy.amount > quote().ask.amount
    assert sell.amount < quote().bid.amount
