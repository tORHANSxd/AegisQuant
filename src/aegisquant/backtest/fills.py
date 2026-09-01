"""Conservative bar, trade/quote and L2 fill decisions."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.backtest.models import (
    BacktestOrder,
    BarEvent,
    FillPrecision,
    FillSlice,
    L2BookEvent,
    LiquidityRole,
    MarketEvent,
    TradeQuoteEvent,
)
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce


def _capped_quantity(
    *, remaining: Decimal, available: Decimal, participation_cap: Decimal
) -> Decimal:
    if min(remaining, available, participation_cap) < 0:
        raise ValueError("fill quantities and participation cannot be negative")
    return min(remaining, available * participation_cap)


def _bar_fill(
    order: BacktestOrder,
    event: BarEvent,
    remaining: Decimal,
    participation_cap: Decimal,
) -> tuple[FillSlice, ...]:
    if event.volume == 0:
        return ()
    role = LiquidityRole.TAKER
    if order.order_type is OrderType.MARKET:
        reference = event.open
    else:
        if order.limit_price is None:
            raise RuntimeError("validated limit order lacks a limit price")
        limit = order.limit_price.amount
        if order.side is OrderSide.BUY:
            if event.low > limit:
                return ()
            role = LiquidityRole.TAKER if event.open <= limit else LiquidityRole.MAKER
        else:
            if event.high < limit:
                return ()
            role = LiquidityRole.TAKER if event.open >= limit else LiquidityRole.MAKER
        # Without intrabar sequence evidence, the limit itself is the conservative price.
        reference = limit
    quantity = _capped_quantity(
        remaining=remaining,
        available=event.volume,
        participation_cap=participation_cap,
    )
    if quantity == 0 or (order.time_in_force is TimeInForce.FILL_OR_KILL and quantity < remaining):
        return ()
    return (
        FillSlice(
            quantity=quantity,
            reference_price=reference,
            available_liquidity=event.volume,
            precision=FillPrecision.BAR_CONSERVATIVE,
            liquidity_role=role,
            source_event_id=event.event_id,
            event_time=event.event_time,
            available_time=event.available_time,
        ),
    )


def _trade_quote_fill(
    order: BacktestOrder,
    event: TradeQuoteEvent,
    remaining: Decimal,
    participation_cap: Decimal,
) -> tuple[FillSlice, ...]:
    if order.side is OrderSide.BUY:
        taker_price, taker_liquidity = event.ask_price, event.ask_quantity
        maker_touched = (
            event.trade_price
            <= (order.limit_price.amount if order.limit_price is not None else Decimal("-1"))
            and event.aggressor_side is OrderSide.SELL
        )
        crosses = order.limit_price is None or event.ask_price <= order.limit_price.amount
    else:
        taker_price, taker_liquidity = event.bid_price, event.bid_quantity
        maker_touched = (
            event.trade_price
            >= (order.limit_price.amount if order.limit_price is not None else Decimal("Infinity"))
            and event.aggressor_side is OrderSide.BUY
        )
        crosses = order.limit_price is None or event.bid_price >= order.limit_price.amount
    if crosses:
        reference = taker_price
        available = taker_liquidity
        role = LiquidityRole.TAKER
    elif maker_touched:
        if order.limit_price is None:
            raise RuntimeError("maker fill requires a limit price")
        reference = order.limit_price.amount
        available = event.trade_quantity
        role = LiquidityRole.MAKER
    else:
        return ()
    quantity = _capped_quantity(
        remaining=remaining,
        available=available,
        participation_cap=participation_cap,
    )
    if quantity == 0 or (order.time_in_force is TimeInForce.FILL_OR_KILL and quantity < remaining):
        return ()
    return (
        FillSlice(
            quantity=quantity,
            reference_price=reference,
            available_liquidity=available,
            precision=FillPrecision.TRADE_QUOTE,
            liquidity_role=role,
            source_event_id=event.event_id,
            event_time=event.event_time,
            available_time=event.available_time,
        ),
    )


def _l2_fill(
    order: BacktestOrder,
    event: L2BookEvent,
    remaining: Decimal,
    participation_cap: Decimal,
) -> tuple[FillSlice, ...]:
    levels = event.asks if order.side is OrderSide.BUY else event.bids
    output: list[FillSlice] = []
    left = remaining
    for level in levels:
        if order.limit_price is not None:
            limit = order.limit_price.amount
            if order.side is OrderSide.BUY and level.price > limit:
                break
            if order.side is OrderSide.SELL and level.price < limit:
                break
        quantity = _capped_quantity(
            remaining=left,
            available=level.quantity,
            participation_cap=participation_cap,
        )
        if quantity == 0:
            continue
        output.append(
            FillSlice(
                quantity=quantity,
                reference_price=level.price,
                available_liquidity=level.quantity,
                precision=FillPrecision.L2_DEPTH,
                liquidity_role=LiquidityRole.TAKER,
                source_event_id=event.event_id,
                event_time=event.event_time,
                available_time=event.available_time,
            )
        )
        left -= quantity
        if left == 0:
            break
    if order.time_in_force is TimeInForce.FILL_OR_KILL and left != 0:
        return ()
    return tuple(output)


def decide_fills(
    *,
    order: BacktestOrder,
    event: MarketEvent,
    remaining: Decimal,
    participation_cap: Decimal,
) -> tuple[FillSlice, ...]:
    """Return deterministic fill slices without mutating historical market data."""
    if event.instrument_id != order.instrument_id or event.venue_id != order.venue_id:
        return ()
    if remaining <= 0:
        return ()
    if isinstance(event, BarEvent):
        return _bar_fill(order, event, remaining, participation_cap)
    if isinstance(event, TradeQuoteEvent):
        return _trade_quote_fill(order, event, remaining, participation_cap)
    return _l2_fill(order, event, remaining, participation_cap)
