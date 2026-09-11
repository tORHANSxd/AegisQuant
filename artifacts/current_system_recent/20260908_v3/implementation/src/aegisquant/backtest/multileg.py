"""Non-atomic multi-leg execution accounting and exposure measurement."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from aegisquant.backtest.models import (
    BacktestFill,
    BacktestOrderResult,
    MultiLegExposure,
    MultiLegPlan,
)
from aegisquant.domain.execution import OrderSide, VenueOrderStatus
from aegisquant.domain.values import canonical_result


def summarize_multi_leg_exposure(
    *,
    plan: MultiLegPlan,
    order_results: tuple[BacktestOrderResult, ...],
    fills: tuple[BacktestFill, ...],
    failed_leg_index: int | None,
    failure_reason: str | None,
) -> MultiLegExposure:
    plan_order_ids = {order.backtest_order_id for order in plan.orders}
    relevant_results = tuple(
        result for result in order_results if result.order.backtest_order_id in plan_order_ids
    )
    relevant_fills = tuple(fill for fill in fills if fill.backtest_order_id in plan_order_ids)
    signed_notional = sum(
        (
            fill.quantity.amount
            * fill.execution_price.amount
            * (Decimal("1") if fill.side is OrderSide.BUY else Decimal("-1"))
            for fill in relevant_fills
        ),
        Decimal("0"),
    )
    filled_legs = sum(result.cumulative_filled_quantity > 0 for result in relevant_results)
    if relevant_fills:
        first = min(fill.available_time for fill in relevant_fills)
        terminal_times = tuple(
            result.completed_at for result in relevant_results if result.completed_at is not None
        )
        terminal = max(terminal_times, default=first)
        delta: timedelta = terminal - first
        duration_ns = (
            delta.days * 86_400 + delta.seconds
        ) * 1_000_000_000 + delta.microseconds * 1_000
    else:
        duration_ns = 0
    if failed_leg_index is None and any(
        result.status in {VenueOrderStatus.REJECTED, VenueOrderStatus.UNKNOWN}
        for result in relevant_results
    ):
        raise ValueError("multi-leg failure must identify the failed leg")
    return MultiLegExposure(
        multi_leg_plan_id=plan.multi_leg_plan_id,
        filled_legs=filled_legs,
        failed_leg_index=failed_leg_index,
        exposed_notional=canonical_result(abs(signed_notional)),
        exposure_duration_ns=duration_ns,
        failure_reason=failure_reason,
    )
