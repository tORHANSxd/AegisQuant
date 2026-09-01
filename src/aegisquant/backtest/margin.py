"""Versioned conservative margin and liquidation approximation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from aegisquant.accounting.models import AccountingInstrument
from aegisquant.backtest.models import BacktestOrder, MarginBracket, MarginEvaluation, MarginPolicy
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    BacktestOrderId,
    ClientOrderId,
    OrderIntentId,
    VenueId,
)
from aegisquant.domain.values import (
    FiniteDecimal,
    PositiveDecimal,
    Quantity,
    canonical_result,
)

BPS = Decimal("10000")


class LiquidationInstruction(DomainModel):
    side: OrderSide
    quantity: PositiveDecimal
    mark_price: PositiveDecimal
    liquidation_price: PositiveDecimal
    penalty: FiniteDecimal
    reason: str


def select_margin_bracket(policy: MarginPolicy, notional: Decimal) -> MarginBracket:
    if notional < 0:
        raise ValueError("margin notional cannot be negative")
    matches = tuple(
        bracket
        for bracket in policy.brackets
        if bracket.notional_floor <= notional
        and (bracket.notional_cap is None or notional < bracket.notional_cap)
    )
    if len(matches) != 1:
        raise ValueError("AQ-BACKTEST-MARGIN-BRACKET-MISSING")
    return matches[0]


def evaluate_margin(
    *,
    policy: MarginPolicy,
    signed_quantity: Decimal,
    entry_price: Decimal,
    mark_price: Decimal,
    collateral: Decimal,
    contract_multiplier: Decimal = Decimal("1"),
) -> MarginEvaluation:
    if min(entry_price, mark_price, contract_multiplier) <= 0:
        raise ValueError("margin prices and multiplier must be positive")
    notional = canonical_result(abs(signed_quantity) * mark_price * contract_multiplier)
    bracket = select_margin_bracket(policy, notional)
    unrealized = canonical_result(
        signed_quantity * contract_multiplier * (mark_price - entry_price)
    )
    equity = canonical_result(collateral + unrealized)
    initial = canonical_result(notional * bracket.initial_margin_rate)
    maintenance = canonical_result(notional * bracket.maintenance_margin_rate)
    buffered = canonical_result(maintenance * (Decimal("1") + policy.conservative_buffer_rate))
    ratio = canonical_result(equity / maintenance) if maintenance > 0 else None
    return MarginEvaluation(
        policy_version=policy.version,
        mode=policy.mode,
        mark_price=mark_price,
        position_quantity=signed_quantity,
        notional=notional,
        equity=equity,
        initial_margin=initial,
        maintenance_margin=maintenance,
        buffered_maintenance_margin=buffered,
        margin_ratio=ratio,
        liquidation_required=signed_quantity != 0 and equity <= buffered,
        precision="CONSERVATIVE_BRACKET_APPROXIMATION",
    )


def require_leverage_allowed(
    *, policy: MarginPolicy, notional: Decimal, collateral: Decimal
) -> Decimal:
    if collateral <= 0:
        raise ValueError("AQ-BACKTEST-MARGIN-COLLATERAL-NONPOSITIVE")
    bracket = select_margin_bracket(policy, notional)
    leverage = canonical_result(notional / collateral)
    if leverage > bracket.maximum_leverage:
        raise ValueError("AQ-BACKTEST-MARGIN-LEVERAGE-EXCEEDED")
    return leverage


def liquidation_instruction(
    *, evaluation: MarginEvaluation, policy: MarginPolicy
) -> LiquidationInstruction:
    if not evaluation.liquidation_required or evaluation.position_quantity == 0:
        raise ValueError("liquidation instruction requires a breached position")
    side = OrderSide.SELL if evaluation.position_quantity > 0 else OrderSide.BUY
    adverse = policy.liquidation_penalty_bps / BPS
    liquidation_price = (
        evaluation.mark_price * (Decimal("1") - adverse)
        if side is OrderSide.SELL
        else evaluation.mark_price * (Decimal("1") + adverse)
    )
    penalty = canonical_result(evaluation.notional * policy.liquidation_penalty_bps / BPS)
    return LiquidationInstruction(
        side=side,
        quantity=abs(evaluation.position_quantity),
        mark_price=evaluation.mark_price,
        liquidation_price=canonical_result(liquidation_price),
        penalty=penalty,
        reason="AQ-BACKTEST-CONSERVATIVE-LIQUIDATION",
    )


def create_liquidation_order(
    *,
    instruction: LiquidationInstruction,
    instrument: AccountingInstrument,
    venue_id: VenueId,
    decision_time: datetime,
    identity: str,
) -> BacktestOrder:
    """Translate a breached margin evaluation into an explicit reduce-only IOC order."""

    if not identity.strip():
        raise ValueError("liquidation identity is required")
    return BacktestOrder(
        backtest_order_id=BacktestOrderId(f"liquidation:{identity}"),
        client_order_id=ClientOrderId(f"liquidation-client:{identity}"),
        order_intent_id=OrderIntentId(f"liquidation-intent:{identity}"),
        instrument_id=instrument.instrument_id,
        venue_id=venue_id,
        side=instruction.side,
        order_type=OrderType.MARKET,
        quantity=Quantity(
            amount=instruction.quantity,
            asset_id=instrument.quantity_asset_id,
        ),
        time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
        decision_time=decision_time,
        submitted_at=decision_time,
        reduce_only=True,
    )
