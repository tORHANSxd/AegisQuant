"""Polars vector alignment with authoritative AegisQuant fill and ledger outputs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

from aegisquant.accounting.models import AccountingInstrument
from aegisquant.backtest.engine import EventBacktestEngine
from aegisquant.backtest.models import (
    BacktestOrder,
    BacktestResult,
    BacktestRunSpec,
    BarEvent,
    CancelRequest,
    EngineKind,
    FaultWindow,
    FundingEvent,
    MultiLegPlan,
)
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    BacktestOrderId,
    ClientOrderId,
    OrderIntentId,
)
from aegisquant.domain.values import Quantity


class VectorBacktestEngine:
    """Batch signals with authoritative event alignment and full position-path replay."""

    def __init__(self, event_engine: EventBacktestEngine) -> None:
        self.event_engine = event_engine

    def run(
        self,
        *,
        spec: BacktestRunSpec,
        instrument: AccountingInstrument,
        bars: Iterable[BarEvent],
        orders: Iterable[BacktestOrder],
        cancel_requests: Iterable[CancelRequest] = (),
        faults: Iterable[FaultWindow] = (),
        funding_events: Iterable[FundingEvent] = (),
        multi_leg_plans: Iterable[MultiLegPlan] = (),
    ) -> BacktestResult:
        if spec.engine_kind is not EngineKind.VECTOR:
            raise ValueError("vector engine requires a VECTOR run spec")
        bar_values = tuple(sorted(bars, key=lambda item: item.available_time))
        order_values = tuple(sorted(orders, key=lambda item: item.submitted_at))
        if any(order.order_type is not OrderType.MARKET for order in order_values):
            raise ValueError("vector engine only supports market benchmark orders")
        if not bar_values:
            raise ValueError("vector backtest requires bars")
        return self.event_engine.run(
            spec=spec,
            instrument=instrument,
            market_events=bar_values,
            orders=order_values,
            cancel_requests=cancel_requests,
            faults=faults,
            funding_events=funding_events,
            multi_leg_plans=multi_leg_plans,
        )


def buy_and_hold_benchmark(
    *,
    bars: Iterable[BarEvent],
    instrument: AccountingInstrument,
    quantity: Decimal,
) -> tuple[BacktestOrder, BacktestOrder]:
    """Create decisions before their execution bars, avoiding same-bar lookahead."""
    values = tuple(sorted(bars, key=lambda item: item.available_time))
    if len(values) < 3:
        raise ValueError("buy-and-hold benchmark requires at least three bars")
    if quantity <= 0:
        raise ValueError("benchmark quantity must be positive")
    buy_decision = values[0].available_time
    sell_decision = values[-2].available_time
    buy_submitted = buy_decision + timedelta(microseconds=1)
    sell_submitted = sell_decision + timedelta(microseconds=1)

    def order(
        sequence: int, side: OrderSide, decision: datetime, submitted: datetime
    ) -> BacktestOrder:
        return BacktestOrder(
            backtest_order_id=BacktestOrderId(f"benchmark-{sequence}"),
            client_order_id=ClientOrderId(f"benchmark-client-{sequence}"),
            order_intent_id=OrderIntentId(f"benchmark-intent-{sequence}"),
            instrument_id=instrument.instrument_id,
            venue_id=values[0].venue_id,
            side=side,
            order_type=OrderType.MARKET,
            quantity=Quantity(
                amount=quantity,
                asset_id=instrument.quantity_asset_id,
            ),
            time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
            decision_time=decision,
            submitted_at=submitted,
        )

    return (
        order(1, OrderSide.BUY, buy_decision, buy_submitted),
        order(2, OrderSide.SELL, sell_decision, sell_submitted),
    )
