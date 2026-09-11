"""Conservative bar, trade/quote and L2 fill decisions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from aegisquant.backtest.models import (
    BacktestOrder,
    BarEvent,
    ExecutionReference,
    ExitTrigger,
    FillPrecision,
    FillSlice,
    L2BookEvent,
    LiquidityRole,
    MarketEvent,
    TradeQuoteEvent,
)
from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import InstrumentId, VenueId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import PositiveDecimal


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


def exit_trigger_reference(order: BacktestOrder, event: MarketEvent) -> Decimal | None:
    """Known bar range only: stop gaps get the adverse open, TP gets its threshold."""
    if order.exit_trigger is None or order.trigger_price is None:
        raise ValueError("exit trigger reference requires a triggered order")
    trigger = order.trigger_price.amount
    sells = order.side is OrderSide.SELL
    stop = order.exit_trigger is ExitTrigger.STOP_LOSS
    if isinstance(event, BarEvent):
        lower, upper, opening = event.low, event.high, event.open
    else:
        if isinstance(event, TradeQuoteEvent):
            opening = event.bid_price if sells else event.ask_price
        else:
            opening = event.bids[0].price if sells else event.asks[0].price
        lower = upper = opening
    downward = sells == stop
    touched = lower <= trigger if downward else upper >= trigger
    if not touched:
        return None
    if not stop:
        return trigger
    return min(opening, trigger) if sells else max(opening, trigger)


def decide_fills(
    *,
    order: BacktestOrder,
    event: MarketEvent,
    remaining: Decimal,
    participation_cap: Decimal,
    triggered: bool = False,
) -> tuple[FillSlice, ...]:
    """Return deterministic fill slices without mutating historical market data."""
    if event.instrument_id != order.instrument_id or event.venue_id != order.venue_id:
        return ()
    if remaining <= 0:
        return ()
    if order.exit_trigger is not None and not triggered:
        reference = exit_trigger_reference(order, event)
        if reference is None:
            return ()
        if isinstance(event, BarEvent):
            event = event.model_copy(update={"open": reference})
    if isinstance(event, BarEvent):
        return _bar_fill(order, event, remaining, participation_cap)
    if isinstance(event, TradeQuoteEvent):
        return _trade_quote_fill(order, event, remaining, participation_cap)
    return _l2_fill(order, event, remaining, participation_cap)


class ParticipationWindow(DomainModel):
    """Known cumulative quote turnover; neither ADV nor snapshot depth is turnover."""

    window_id: str = Field(min_length=1)
    instrument_id: InstrumentId
    venue_id: VenueId
    start: UtcDateTime
    end: UtcDateTime
    available_at: UtcDateTime
    quote_turnover: PositiveDecimal
    source_sha256: str

    @field_validator("source_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="participation window source hash")

    @model_validator(mode="after")
    def validate_window(self) -> ParticipationWindow:
        if not self.start < self.end <= self.available_at:
            raise ValueError("participation window must be complete before availability")
        if (self.end - self.start).total_seconds() % 1:
            raise ValueError("participation horizon uses whole seconds")
        return self


@dataclass(frozen=True)
class ExecutionFillDecision:
    slices: tuple[FillSlice, ...]
    unfilled_quantity: Decimal
    reason: str


class EventLiquidityBudget:
    """A shared window budget around decide_fills; caller commits only settled fills."""

    def __init__(self, window: ParticipationWindow, maximum_participation: Decimal) -> None:
        if not maximum_participation.is_finite() or not 0 <= maximum_participation <= 1:
            raise ValueError("invalid shared participation cap")
        self.window = window
        self.maximum_quote_notional = window.quote_turnover * maximum_participation
        self.used_quote_notional = Decimal("0")
        # ponytail: retain event/fill keys for one supplied window; rotate only after it closes.
        self._events: dict[str, str] = {}
        self._levels: dict[tuple[str, OrderSide, Decimal], Decimal] = {}
        self._prepared: set[str] = set()
        self._fills: dict[str, str] = {}
        self._order_filled: dict[str, Decimal] = {}

    def preview(
        self,
        *,
        order: BacktestOrder,
        event: MarketEvent,
        remaining: Decimal,
        arrival_at: UtcDateTime,
        cancel_effective_at: UtcDateTime | None = None,
        queue_ahead: Decimal | None = None,
        queue_source_sha256: str | None = None,
    ) -> ExecutionFillDecision:
        """Event wins an equal-time cancellation, matching the existing engine convention."""
        order_id = str(order.backtest_order_id)
        if (
            not remaining.is_finite()
            or remaining <= 0
            or arrival_at < order.submitted_at
            or remaining > order.quantity.amount - self._order_filled.get(order_id, Decimal("0"))
        ):
            raise ValueError("invalid execution remaining quantity or arrival clock")
        if (
            order.instrument_id != self.window.instrument_id
            or order.venue_id != self.window.venue_id
        ):
            raise ValueError("AQ-EXECUTION-PARTICIPATION-WINDOW-INSTRUMENT-MISMATCH")
        reason = (
            "ORDER_NOT_AT_VENUE"
            if event.event_time < arrival_at
            else "CANCEL_ALREADY_EFFECTIVE"
            if cancel_effective_at is not None and cancel_effective_at < event.event_time
            else "BAR_PROXY_ONLY"
            if isinstance(event, BarEvent)
            else "WINDOW_NOT_KNOWN"
            if self.window.available_at > event.available_time
            or self.window.end != event.event_time
            else None
        )
        if reason is not None:
            return ExecutionFillDecision((), remaining, reason)
        event_id = str(event.event_id)
        event_hash = canonical_sha256(event.model_dump(mode="json"))
        if event_id in self._events and self._events[event_id] != event_hash:
            raise ValueError("AQ-EXECUTION-CONFLICTING-MARKET-EVENT")
        self._events[event_id] = event_hash
        execution_event = event
        if isinstance(event, L2BookEvent):
            levels = event.asks if order.side is OrderSide.BUY else event.bids
            # Use the existing engine's residual-book convention to reach deeper levels.
            execution_event = event.model_copy(
                update={
                    "asks" if order.side is OrderSide.BUY else "bids": tuple(
                        level.model_copy(
                            update={
                                "quantity": self._levels.get(
                                    (event_id, order.side, level.price), level.quantity
                                )
                            }
                        )
                        for level in levels
                    )
                }
            )
        raw = decide_fills(
            order=order, event=execution_event, remaining=remaining, participation_cap=Decimal("1")
        )
        if any(item.liquidity_role is LiquidityRole.MAKER for item in raw):
            if queue_ahead is None or queue_source_sha256 is None:
                return ExecutionFillDecision((), remaining, "MAKER_QUEUE_UNKNOWN")
            ensure_sha256(queue_source_sha256, field_name="maker queue source hash")
            if not queue_ahead.is_finite() or queue_ahead < 0:
                raise ValueError("maker queue ahead must be finite and nonnegative")
        left_quote = self.maximum_quote_notional - self.used_quote_notional
        output: list[FillSlice] = []
        for item in raw:
            key = (event_id, order.side, item.reference_price)
            available = item.available_liquidity
            if item.liquidity_role is LiquidityRole.MAKER:
                available = max(Decimal("0"), available - (queue_ahead or Decimal("0")))
            self._levels.setdefault(key, available)
            quantity = min(item.quantity, self._levels[key], left_quote / item.reference_price)
            if quantity <= 0:
                continue
            kind = (
                "MAKER_LIMIT"
                if item.liquidity_role is LiquidityRole.MAKER
                else "DEPTH_VWAP"
                if isinstance(event, L2BookEvent)
                else "BBO"
            )
            reference = ExecutionReference(
                reference_price_kind=kind,
                included_cost_components=("SPREAD", "VISIBLE_DEPTH")
                if kind == "DEPTH_VWAP"
                else ("SPREAD",)
                if kind == "BBO"
                else (),
                source_sha256=event_hash,
                evidence_kind="SYNTHETIC_ONLY",
                participation_window_seconds=int(
                    (self.window.end - self.window.start).total_seconds()
                ),
                window_quote_turnover=self.window.quote_turnover,
            )
            selected = item.model_copy(update={"quantity": quantity, "reference": reference})
            output.append(selected)
            left_quote -= quantity * item.reference_price
        filled = sum((item.quantity for item in output), Decimal("0"))
        if order.time_in_force is TimeInForce.FILL_OR_KILL and filled < remaining:
            return ExecutionFillDecision((), remaining, "FOK_INSUFFICIENT_SHARED_LIQUIDITY")
        self._prepared.update(self._identity(order, selected) for selected in output)
        return ExecutionFillDecision(
            tuple(output),
            remaining - filled,
            "FILLED" if filled == remaining else "UNFILLED_RESIDUAL",
        )

    @staticmethod
    def _identity(order: BacktestOrder, item: FillSlice) -> str:
        return canonical_sha256(
            {"order": order.model_dump(mode="json"), "slice": item.model_dump(mode="json")}
        )

    def commit(self, *, fill_id: str, order: BacktestOrder, item: FillSlice) -> bool:
        """Idempotent consumption; opposite sides cannot net out window usage."""
        identity = self._identity(order, item)
        if fill_id in self._fills:
            if self._fills[fill_id] != identity:
                raise ValueError("AQ-EXECUTION-CONFLICTING-FILL-ID")
            return False
        if identity not in self._prepared:
            raise ValueError("AQ-EXECUTION-FILL-WAS-NOT-PREPARED")
        key = (str(item.source_event_id), order.side, item.reference_price)
        order_id = str(order.backtest_order_id)
        if self._order_filled.get(order_id, Decimal("0")) + item.quantity > order.quantity.amount:
            raise ValueError("AQ-EXECUTION-FILL-EXCEEDS-ORDER-QUANTITY")
        notional = item.quantity * item.reference_price
        if (
            item.quantity > self._levels[key]
            or self.used_quote_notional + notional > self.maximum_quote_notional
        ):
            raise ValueError("AQ-EXECUTION-STALE-PREVIEW-EXCEEDS-LIQUIDITY")
        self._levels[key] -= item.quantity
        self.used_quote_notional += notional
        self._fills[fill_id] = identity
        self._order_filled[order_id] = (
            self._order_filled.get(order_id, Decimal("0")) + item.quantity
        )
        return True
