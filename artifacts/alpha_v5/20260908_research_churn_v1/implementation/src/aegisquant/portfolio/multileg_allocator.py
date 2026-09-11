"""Separately funded carry legs and reduce-only recovery after a failed or late leg."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from pydantic import Field

from aegisquant.backtest.models import BacktestOrder
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    AssetId,
    BacktestOrderId,
    ClientOrderId,
    InstrumentId,
    OrderIntentId,
    VenueId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal, PositiveDecimal, Quantity
from aegisquant.execution.groups import (
    ExecutionGroup,
    ExecutionGroupLeg,
    ExecutionGroupPolicy,
    GroupAction,
    evaluate_group_exposure,
)


class CarryAllocation(DomainModel):
    spot_quantity: PositiveDecimal
    perp_contracts: PositiveDecimal
    spot_cash_reserved: PositiveDecimal
    perp_collateral_reserved: PositiveDecimal
    cost_reserve: NonNegativeDecimal
    residual_base_delta: NonNegativeDecimal


def allocate_carry(
    *,
    capital: Decimal,
    spot_price: Decimal,
    perp_price: Decimal,
    contract_multiplier: Decimal,
    spot_capacity: Decimal,
    perp_capacity_contracts: Decimal,
    spot_step: Decimal,
    perp_step: Decimal,
    minimum_leg_notional: Decimal,
    maximum_base_delta: Decimal,
    cost_reserve_fraction: Decimal = Decimal("0.01"),
) -> CarryAllocation:
    if min(capital, spot_price, perp_price, contract_multiplier, spot_step, perp_step) <= 0:
        raise ValueError("carry allocation needs positive capital, prices and increments")
    if (
        min(spot_capacity, perp_capacity_contracts, minimum_leg_notional, maximum_base_delta) < 0
        or not 0 <= cost_reserve_fraction < 1
    ):
        raise ValueError("invalid carry capacity or reserves")
    available = capital * (1 - cost_reserve_fraction)
    # 100% collateral backs the perp leg; total gross notional stays <= capital.
    base = min(
        available / (spot_price + perp_price),
        spot_capacity,
        perp_capacity_contracts * contract_multiplier,
    )
    spot = (base / spot_step).to_integral_value(rounding=ROUND_DOWN) * spot_step
    contracts = (spot / contract_multiplier / perp_step).to_integral_value(
        rounding=ROUND_DOWN
    ) * perp_step
    delta = abs(spot - contracts * contract_multiplier)
    if (
        delta > maximum_base_delta
        or min(spot * spot_price, contracts * contract_multiplier * perp_price)
        < minimum_leg_notional
    ):
        raise ValueError("carry leg precision, delta or minimum notional cannot be satisfied")
    if spot == 0 or contracts == 0:
        raise ValueError("both carry legs require executable capacity")
    return CarryAllocation(
        spot_quantity=spot,
        perp_contracts=contracts,
        spot_cash_reserved=spot * spot_price,
        perp_collateral_reserved=contracts * contract_multiplier * perp_price,
        cost_reserve=capital * cost_reserve_fraction,
        residual_base_delta=delta,
    )


class CarryRecovery(DomainModel):
    cancel_unfilled_legs: bool
    reduce_only_orders: tuple[BacktestOrder, ...]
    reason: str


class CarryLegState(DomainModel):
    group_id: str = Field(min_length=1)
    created_at: UtcDateTime
    observed_at: UtcDateTime
    spot_filled: NonNegativeDecimal
    perp_contracts_filled: NonNegativeDecimal
    contract_multiplier: PositiveDecimal
    target_base_quantity: PositiveDecimal
    reference_spot_price: PositiveDecimal
    spot_instrument_id: InstrumentId
    perp_instrument_id: InstrumentId
    spot_venue_id: VenueId
    perp_venue_id: VenueId
    base_asset_id: AssetId
    perp_quantity_asset_id: AssetId
    failed_leg_observed: bool = False


def recover_carry_legs(
    state: CarryLegState,
    *,
    maximum_naked_notional: Decimal = Decimal("10"),
    timeout_seconds: int = 5,
) -> CarryRecovery:
    if state.observed_at < state.created_at or timeout_seconds < 1 or maximum_naked_notional < 0:
        raise ValueError("invalid carry recovery timing or exposure limit")
    common_price = state.reference_spot_price
    target = state.target_base_quantity * common_price
    # Both legs use the SAME base reference so basis is not mistaken for directional delta.
    group = ExecutionGroup(
        execution_group_id=state.group_id,
        notional_asset_id=AssetId("USDT"),
        created_at=state.created_at,
        policy=ExecutionGroupPolicy(
            maximum_naked_notional=maximum_naked_notional,
            maximum_naked_seconds=timeout_seconds,
            halt_notional=max(target, maximum_naked_notional),
        ),
        legs=(
            ExecutionGroupLeg(
                leg_id="spot",
                instrument_id=state.spot_instrument_id,
                side=OrderSide.BUY,
                target_notional=target,
                filled_notional=state.spot_filled * common_price,
            ),
            ExecutionGroupLeg(
                leg_id="perp",
                instrument_id=state.perp_instrument_id,
                side=OrderSide.SELL,
                target_notional=target,
                filled_notional=state.perp_contracts_filled
                * state.contract_multiplier
                * common_price,
            ),
        ),
    )
    decision = evaluate_group_exposure(group, evaluated_at=state.observed_at)
    timeout = state.observed_at - state.created_at >= timedelta(seconds=timeout_seconds)
    if (
        not state.failed_leg_observed
        and not timeout
        and decision.action not in {GroupAction.HEDGE, GroupAction.HALT}
    ):
        return CarryRecovery(
            cancel_unfilled_legs=False, reduce_only_orders=(), reason=decision.reason_code
        )
    if decision.action is GroupAction.COMPLETE and not state.failed_leg_observed:
        return CarryRecovery(
            cancel_unfilled_legs=False, reduce_only_orders=(), reason="DELTA_NEUTRAL_COMPLETE"
        )
    orders: list[BacktestOrder] = []
    for leg, instrument, venue, side, quantity, asset in (
        (
            "spot",
            state.spot_instrument_id,
            state.spot_venue_id,
            OrderSide.SELL,
            state.spot_filled,
            state.base_asset_id,
        ),
        (
            "perp",
            state.perp_instrument_id,
            state.perp_venue_id,
            OrderSide.BUY,
            state.perp_contracts_filled,
            state.perp_quantity_asset_id,
        ),
    ):
        if quantity == 0:
            continue
        key = f"{state.group_id}-recovery-{leg}"
        orders.append(
            BacktestOrder(
                backtest_order_id=BacktestOrderId(key),
                client_order_id=ClientOrderId(key),
                order_intent_id=OrderIntentId(key),
                instrument_id=instrument,
                venue_id=venue,
                side=side,
                quantity=Quantity(amount=quantity, asset_id=asset),
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
                reduce_only=True,
                decision_time=state.observed_at,
                submitted_at=state.observed_at,
            )
        )
    return CarryRecovery(
        cancel_unfilled_legs=True,
        reduce_only_orders=tuple(orders),
        reason="FAILED_OR_LATE_LEG_CANCEL_AND_FLATTEN_FILLED_INVENTORY",
    )
