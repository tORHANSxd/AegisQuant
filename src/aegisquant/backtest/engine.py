"""Deterministic event backtest engine connected to the P05 authoritative ledger."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from aegisquant.accounting.ledger import AccountingPolicy, LedgerEngine, calculate_contract_pnl
from aegisquant.accounting.models import (
    AccountingInstrument,
    CashflowDirection,
    CashflowEvent,
    CashflowType,
)
from aegisquant.backtest.costs import HistoricalCostBook, execution_price_and_cost, funding_cost
from aegisquant.backtest.fills import decide_fills
from aegisquant.backtest.metrics import calculate_metrics
from aegisquant.backtest.models import (
    BacktestFill,
    BacktestOrder,
    BacktestOrderResult,
    BacktestResult,
    BacktestRunSpec,
    BarEvent,
    CancelRequest,
    EquityPoint,
    FaultType,
    FaultWindow,
    FillSlice,
    FundingEvent,
    L2BookEvent,
    LatencyPolicy,
    MarketEvent,
    MultiLegExposure,
    MultiLegPlan,
    PnLAttributionPoint,
    PositionPoint,
    TradeQuoteEvent,
    nanoseconds_after,
)
from aegisquant.backtest.multileg import summarize_multi_leg_exposure
from aegisquant.backtest.rules import HistoricalRuleBook
from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.market import InstrumentType
from aegisquant.domain.execution import Fill, OrderSide, TimeInForce, VenueOrderStatus
from aegisquant.domain.identifiers import (
    ArtifactId,
    BacktestOrderId,
    FillId,
    IdempotencyKey,
    MultiLegPlanId,
    VenueOrderId,
)
from aegisquant.domain.values import Money, Price, Quantity, canonical_result


@dataclass(slots=True)
class _MutableOrderState:
    order: BacktestOrder
    arrival_time: datetime
    status: VenueOrderStatus
    venue_order_id: VenueOrderId | None
    filled: Decimal = Decimal("0")
    fill_value: Decimal = Decimal("0")
    completed_at: datetime | None = None
    rejection_code: str | None = None
    unknown_reason: str | None = None
    recovery_evidence: tuple[str, ...] = ()
    fill_sequence: int = 0


def _delta_nanoseconds(later: datetime, earlier: datetime) -> int:
    delta = later - earlier
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _event_reference(event: MarketEvent, side: OrderSide) -> Decimal:
    if isinstance(event, BarEvent):
        return event.open
    if isinstance(event, TradeQuoteEvent):
        return event.ask_price if side is OrderSide.BUY else event.bid_price
    return event.asks[0].price if side is OrderSide.BUY else event.bids[0].price


def _event_mark(event: MarketEvent) -> Decimal:
    if isinstance(event, BarEvent):
        return event.close
    if isinstance(event, TradeQuoteEvent):
        return event.trade_price
    return canonical_result((event.bids[0].price + event.asks[0].price) / Decimal("2"))


def _active_fault(
    faults: tuple[FaultWindow, ...], order: BacktestOrder, at_time: datetime
) -> FaultWindow | None:
    for fault in faults:
        if fault.venue_id == order.venue_id and fault.starts_at <= at_time < fault.ends_at:
            return fault
    return None


def _fee_in_settlement_asset(
    *,
    quote_fee: Decimal,
    execution_price: Decimal,
    instrument: AccountingInstrument,
) -> Money:
    if instrument.settlement_asset_id == instrument.quote_asset_id:
        amount = quote_fee
    elif instrument.settlement_asset_id == instrument.base_asset_id:
        amount = canonical_result(quote_fee / execution_price)
    else:
        raise ValueError("AQ-BACKTEST-FEE-CONVERSION-UNAVAILABLE")
    return Money(amount=amount, asset_id=instrument.settlement_asset_id)


class EventBacktestEngine:
    """Single-process deterministic simulator; it owns no account or network capability."""

    def __init__(
        self,
        *,
        project_root: Path,
        cost_book: HistoricalCostBook,
        rule_book: HistoricalRuleBook,
        latency_policy: LatencyPolicy,
        liquidity_consumption: bool = True,
    ) -> None:
        self.project_root = project_root
        self.cost_book = cost_book
        self.rule_book = rule_book
        self.latency_policy = latency_policy
        self.liquidity_consumption = liquidity_consumption

    def _ledger(self, spec: BacktestRunSpec) -> LedgerEngine:
        policy = AccountingPolicy.from_yaml(
            self.project_root / "configs/accounting/accounting_policy_v1.yaml"
        )
        if policy.policy_version != spec.accounting_policy_version:
            raise ValueError("AQ-BACKTEST-ACCOUNTING-POLICY-MISMATCH")
        ledger = LedgerEngine(policy=policy, effective_from=spec.start_time)
        if spec.initial_cash.amount > 0:
            ledger.process_cashflow(
                CashflowEvent(
                    event_id=ArtifactId(f"initial-capital:{spec.run_id}"),
                    venue="SIM",
                    cashflow_type=CashflowType.EXTERNAL_TRANSFER_IN,
                    direction=CashflowDirection.INFLOW,
                    amount=spec.initial_cash,
                    event_time=spec.start_time,
                    recorded_at=spec.start_time,
                    idempotency_key=IdempotencyKey(f"initial-capital:{spec.run_id}"),
                    reference="deterministic backtest initial capital",
                )
            )
        return ledger

    def _initial_states(
        self,
        *,
        spec: BacktestRunSpec,
        orders: tuple[BacktestOrder, ...],
        market_events: tuple[MarketEvent, ...],
        faults: tuple[FaultWindow, ...],
        failed_leg_indices: Mapping[MultiLegPlanId, int],
    ) -> dict[BacktestOrderId, _MutableOrderState]:
        states: dict[BacktestOrderId, _MutableOrderState] = {}
        for order in orders:
            arrival = nanoseconds_after(order.submitted_at, self.latency_policy.order_arrival_ns)
            venue_order_id = VenueOrderId(f"simorder:{order.backtest_order_id}")
            relevant = next(
                (
                    event
                    for event in market_events
                    if event.instrument_id == order.instrument_id
                    and event.venue_id == order.venue_id
                    and event.available_time >= arrival
                ),
                None,
            )
            state = _MutableOrderState(
                order=order,
                arrival_time=arrival,
                status=VenueOrderStatus.ACCEPTED,
                venue_order_id=venue_order_id,
            )
            if relevant is None:
                state.status = VenueOrderStatus.EXPIRED
                state.completed_at = spec.end_time
            else:
                decision = self.rule_book.validate_order(
                    order,
                    reference_price=_event_reference(relevant, order.side),
                )
                if not decision.valid:
                    state.status = VenueOrderStatus.REJECTED
                    state.rejection_code = decision.rejection_code
                    state.completed_at = arrival
            if order.multi_leg_plan_id is not None:
                failed_index = failed_leg_indices.get(order.multi_leg_plan_id)
                if failed_index is not None and order.leg_index is not None:
                    if order.leg_index == failed_index:
                        state.status = VenueOrderStatus.REJECTED
                        state.rejection_code = "AQ-BACKTEST-MULTILEG-LEG-FAILURE"
                        state.completed_at = arrival
                    elif order.leg_index > failed_index:
                        state.status = VenueOrderStatus.REJECTED
                        state.rejection_code = "AQ-BACKTEST-MULTILEG-ABORTED-AFTER-FAILURE"
                        state.completed_at = arrival
            arrival_fault = _active_fault(faults, order, arrival)
            if (
                arrival_fault is not None
                and arrival_fault.fault_type is FaultType.REQUEST_TIMEOUT
                and state.status is VenueOrderStatus.ACCEPTED
            ):
                state.status = VenueOrderStatus.UNKNOWN
                state.unknown_reason = "AQ-BACKTEST-ORDER-ACK-TIMEOUT"
                state.recovery_evidence = (
                    arrival_fault.evidence,
                    "requery-required:no-blind-resubmit",
                )
            states[order.backtest_order_id] = state
        return states

    def _backtest_fill(
        self,
        *,
        state: _MutableOrderState,
        fill_slice: FillSlice,
        instrument: AccountingInstrument,
    ) -> tuple[BacktestFill, Fill]:
        state.fill_sequence += 1
        schedule = self.cost_book.at(state.order, fill_slice.event_time)
        execution_price, breakdown = execution_price_and_cost(
            order=state.order,
            fill_slice=fill_slice,
            schedule=schedule,
            base_asset_id=instrument.base_asset_id,
            quote_asset_id=instrument.quote_asset_id,
        )
        fill_id = FillId(f"simfill:{state.order.backtest_order_id}:{state.fill_sequence}")
        if state.venue_order_id is None:
            raise RuntimeError("accepted simulated order lacks venue order id")
        fee = _fee_in_settlement_asset(
            quote_fee=breakdown.fee,
            execution_price=execution_price.amount,
            instrument=instrument,
        )
        ingest_time = nanoseconds_after(
            fill_slice.available_time, self.latency_policy.acknowledgement_ns
        )
        latency_ns = _delta_nanoseconds(fill_slice.available_time, state.order.decision_time)
        backtest_fill = BacktestFill(
            fill_id=fill_id,
            venue_order_id=state.venue_order_id,
            backtest_order_id=state.order.backtest_order_id,
            client_order_id=state.order.client_order_id,
            order_intent_id=state.order.order_intent_id,
            instrument_id=state.order.instrument_id,
            side=state.order.side,
            quantity=Quantity(
                amount=fill_slice.quantity,
                asset_id=instrument.quantity_asset_id,
            ),
            reference_price=Price(
                amount=fill_slice.reference_price,
                base_asset_id=instrument.base_asset_id,
                quote_asset_id=instrument.quote_asset_id,
            ),
            execution_price=execution_price,
            fee=fee,
            cost_breakdown=breakdown,
            precision=fill_slice.precision,
            liquidity_role=fill_slice.liquidity_role,
            source_event_id=fill_slice.source_event_id,
            available_liquidity=fill_slice.available_liquidity,
            event_time=fill_slice.event_time,
            available_time=fill_slice.available_time,
            ingest_time=ingest_time,
            latency_ns=latency_ns,
        )
        ledger_fill = Fill(
            fill_id=fill_id,
            venue_order_id=state.venue_order_id,
            client_order_id=state.order.client_order_id,
            order_intent_id=state.order.order_intent_id,
            instrument_id=state.order.instrument_id,
            side=state.order.side,
            quantity=backtest_fill.quantity,
            price=execution_price,
            fee=fee,
            event_time=fill_slice.event_time,
            available_time=fill_slice.available_time,
            ingest_time=ingest_time,
            idempotency_key=IdempotencyKey(f"simfill:{fill_id}"),
        )
        return backtest_fill, ledger_fill

    @staticmethod
    def _clip_for_consumption(
        slices: tuple[FillSlice, ...], available: Decimal
    ) -> tuple[FillSlice, ...]:
        if available < 0:
            raise ValueError("consumed liquidity cannot be negative")
        output: list[FillSlice] = []
        left = available
        for item in slices:
            quantity = min(item.quantity, left)
            if quantity <= 0:
                break
            output.append(item.model_copy(update={"quantity": quantity}))
            left -= quantity
        return tuple(output)

    @staticmethod
    def _position(
        *, ledger: LedgerEngine, instrument: AccountingInstrument, mark_price: Decimal
    ) -> tuple[Decimal, Decimal | None, Decimal]:
        lots = ledger.open_lots(instrument.instrument_id)
        signed_quantity = sum(
            (
                lot.remaining_quantity
                * (Decimal("1") if lot.side.value == "LONG" else Decimal("-1"))
                for lot in lots
            ),
            Decimal("0"),
        )
        total_quantity = sum((lot.remaining_quantity for lot in lots), Decimal("0"))
        average = (
            canonical_result(
                sum(
                    (lot.entry_price * lot.remaining_quantity for lot in lots),
                    Decimal("0"),
                )
                / total_quantity
            )
            if total_quantity > 0
            else None
        )
        if instrument.instrument_type is InstrumentType.SPOT:
            unrealized = canonical_result(
                sum(
                    (
                        lot.remaining_quantity
                        * (mark_price - lot.entry_price)
                        * (Decimal("1") if lot.side.value == "LONG" else Decimal("-1"))
                        for lot in lots
                    ),
                    Decimal("0"),
                )
            )
        else:
            unrealized = canonical_result(
                sum(
                    (
                        calculate_contract_pnl(
                            side=lot.side,
                            quantity=lot.remaining_quantity,
                            entry_price=lot.entry_price,
                            exit_price=mark_price,
                            instrument=instrument,
                        ).amount
                        for lot in lots
                    ),
                    Decimal("0"),
                )
            )
        return signed_quantity, average, unrealized

    @staticmethod
    def _order_results(
        states: Mapping[BacktestOrderId, _MutableOrderState], end_time: datetime
    ) -> tuple[BacktestOrderResult, ...]:
        output: list[BacktestOrderResult] = []
        for state in states.values():
            status = state.status
            completed_at = state.completed_at
            if status is VenueOrderStatus.ACCEPTED:
                status = VenueOrderStatus.EXPIRED
                completed_at = end_time
            elif status is VenueOrderStatus.PARTIALLY_FILLED and completed_at is None:
                completed_at = end_time
            average = (
                canonical_result(state.fill_value / state.filled) if state.filled > 0 else None
            )
            output.append(
                BacktestOrderResult(
                    order=state.order,
                    status=status,
                    venue_order_id=state.venue_order_id,
                    arrival_time=state.arrival_time,
                    cumulative_filled_quantity=state.filled,
                    average_fill_price=average,
                    completed_at=completed_at,
                    rejection_code=state.rejection_code,
                    unknown_reason=state.unknown_reason,
                    recovery_evidence=state.recovery_evidence,
                )
            )
        return tuple(sorted(output, key=lambda item: str(item.order.backtest_order_id)))

    def run(
        self,
        *,
        spec: BacktestRunSpec,
        instrument: AccountingInstrument,
        market_events: Iterable[MarketEvent],
        orders: Iterable[BacktestOrder],
        cancel_requests: Iterable[CancelRequest] = (),
        faults: Iterable[FaultWindow] = (),
        funding_events: Iterable[FundingEvent] = (),
        multi_leg_plans: Iterable[MultiLegPlan] = (),
        failed_leg_indices: Mapping[MultiLegPlanId, int] | None = None,
    ) -> BacktestResult:
        events = tuple(
            sorted(
                (
                    event
                    for event in market_events
                    if spec.start_time <= event.available_time <= spec.end_time
                ),
                key=lambda item: (item.available_time, item.event_time, str(item.event_id)),
            )
        )
        if not events:
            raise ValueError("AQ-BACKTEST-MARKET-EVENTS-EMPTY")
        if any(event.instrument_id != instrument.instrument_id for event in events):
            raise ValueError("market event instrument differs from accounting instrument")
        order_values = tuple(
            sorted(orders, key=lambda item: (item.submitted_at, str(item.backtest_order_id)))
        )
        if len({order.backtest_order_id for order in order_values}) != len(order_values):
            raise ValueError("duplicate backtest order id")
        fault_values = tuple(sorted(faults, key=lambda item: item.starts_at))
        failures = failed_leg_indices or {}
        states = self._initial_states(
            spec=spec,
            orders=order_values,
            market_events=events,
            faults=fault_values,
            failed_leg_indices=failures,
        )
        cancel_by_order = {
            request.backtest_order_id: nanoseconds_after(
                request.requested_at, self.latency_policy.cancel_ns
            )
            for request in cancel_requests
        }
        ledger = self._ledger(spec)
        fills: list[BacktestFill] = []
        cash = spec.initial_cash.amount
        realized = Decimal("0")
        funding_total = Decimal("0")
        equity_curve: list[EquityPoint] = [
            EquityPoint(
                time=spec.start_time,
                cash=cash,
                position_value=Decimal("0"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                equity=cash,
                reporting_asset_id=spec.reporting_asset_id,
            )
        ]
        latest_mark = _event_mark(events[0])
        event_capacity: dict[str, Decimal] = {}
        funding_values = tuple(
            sorted(
                (
                    event
                    for event in funding_events
                    if spec.start_time <= event.available_time <= spec.end_time
                ),
                key=lambda item: (item.available_time, str(item.event_id)),
            )
        )
        timeline: list[tuple[datetime, int, MarketEvent | FundingEvent]] = []
        timeline.extend((event.available_time, 0, event) for event in events)
        timeline.extend((event.available_time, 1, event) for event in funding_values)
        timeline.sort(key=lambda item: (item[0], item[1]))
        for _, kind, item in timeline:
            if kind == 1:
                funding_event = item
                if not isinstance(funding_event, FundingEvent):
                    raise TypeError("funding timeline item has the wrong type")
                signed_quantity, _, unrealized = self._position(
                    ledger=ledger,
                    instrument=instrument,
                    mark_price=funding_event.mark_price,
                )
                cost = funding_cost(
                    signed_quantity=signed_quantity,
                    mark_price=funding_event.mark_price,
                    funding_rate=funding_event.funding_rate,
                )
                latest_mark = funding_event.mark_price
                if cost != 0:
                    if instrument.settlement_asset_id != spec.reporting_asset_id:
                        raise ValueError("AQ-BACKTEST-FUNDING-FX-REQUIRED")
                    ledger.process_cashflow(
                        CashflowEvent(
                            event_id=ArtifactId(f"funding:{funding_event.event_id}"),
                            venue=str(funding_event.venue_id),
                            cashflow_type=CashflowType.FUNDING,
                            direction=(
                                CashflowDirection.OUTFLOW if cost > 0 else CashflowDirection.INFLOW
                            ),
                            amount=Money(
                                amount=abs(cost),
                                asset_id=instrument.settlement_asset_id,
                            ),
                            event_time=funding_event.event_time,
                            recorded_at=funding_event.available_time,
                            idempotency_key=IdempotencyKey(f"funding:{funding_event.event_id}"),
                            reference="historical funding event",
                        )
                    )
                    cash = canonical_result(cash - cost)
                    funding_total = canonical_result(funding_total + cost)
                    position_value = (
                        signed_quantity * latest_mark
                        if instrument.instrument_type is InstrumentType.SPOT
                        else unrealized
                    )
                    equity_curve.append(
                        EquityPoint(
                            time=funding_event.available_time,
                            cash=cash,
                            position_value=position_value,
                            realized_pnl=realized,
                            unrealized_pnl=unrealized,
                            equity=canonical_result(cash + position_value),
                            reporting_asset_id=spec.reporting_asset_id,
                        )
                    )
                continue
            event = item
            if not isinstance(event, (BarEvent, TradeQuoteEvent, L2BookEvent)):
                raise TypeError("market timeline item has the wrong type")
            latest_mark = _event_mark(event)
            if isinstance(event, BarEvent):
                raw_capacity = event.volume
            elif isinstance(event, TradeQuoteEvent):
                raw_capacity = max(event.bid_quantity, event.ask_quantity, event.trade_quantity)
            else:
                raw_capacity = max(
                    sum((level.quantity for level in event.bids), Decimal("0")),
                    sum((level.quantity for level in event.asks), Decimal("0")),
                )
            capacity_key = str(event.event_id)
            event_capacity.setdefault(capacity_key, raw_capacity)
            for state in states.values():
                if state.status not in {
                    VenueOrderStatus.ACCEPTED,
                    VenueOrderStatus.PARTIALLY_FILLED,
                }:
                    continue
                if event.available_time < state.arrival_time:
                    continue
                cancel_time = cancel_by_order.get(state.order.backtest_order_id)
                if cancel_time is not None and cancel_time < event.available_time:
                    state.status = VenueOrderStatus.CANCELED
                    state.completed_at = cancel_time
                    continue
                fault = _active_fault(fault_values, state.order, event.available_time)
                if fault is not None:
                    state.status = VenueOrderStatus.UNKNOWN
                    state.unknown_reason = f"AQ-BACKTEST-{fault.fault_type.value}"
                    state.recovery_evidence = (
                        fault.evidence,
                        "requery-required:no-blind-resubmit",
                    )
                    state.completed_at = event.available_time
                    continue
                remaining = state.order.quantity.amount - state.filled
                schedule = self.cost_book.at(state.order, event.event_time)
                slices = decide_fills(
                    order=state.order,
                    event=event,
                    remaining=remaining,
                    participation_cap=schedule.participation_cap,
                )
                if self.liquidity_consumption:
                    slices = self._clip_for_consumption(slices, event_capacity[capacity_key])
                if (
                    state.order.time_in_force is TimeInForce.FILL_OR_KILL
                    and sum((slice_.quantity for slice_ in slices), Decimal("0")) < remaining
                ):
                    slices = ()
                for fill_slice in slices:
                    backtest_fill, ledger_fill = self._backtest_fill(
                        state=state,
                        fill_slice=fill_slice,
                        instrument=instrument,
                    )
                    outcome = ledger.process_fill(ledger_fill, instrument)
                    fills.append(backtest_fill)
                    state.filled = canonical_result(state.filled + fill_slice.quantity)
                    state.fill_value = canonical_result(
                        state.fill_value
                        + fill_slice.quantity * backtest_fill.execution_price.amount
                    )
                    if self.liquidity_consumption:
                        event_capacity[capacity_key] = canonical_result(
                            event_capacity[capacity_key] - fill_slice.quantity
                        )
                    if instrument.settlement_asset_id != spec.reporting_asset_id:
                        raise ValueError("AQ-BACKTEST-REPORTING-ASSET-FX-REQUIRED")
                    if instrument.instrument_type is InstrumentType.SPOT:
                        notional = fill_slice.quantity * backtest_fill.execution_price.amount
                        cash = canonical_result(
                            cash
                            + (-notional if state.order.side is OrderSide.BUY else notional)
                            - backtest_fill.fee.amount
                        )
                    else:
                        cash = canonical_result(
                            cash
                            + outcome.applied_fill.realized_pnl.amount
                            - backtest_fill.fee.amount
                        )
                    realized = canonical_result(realized + outcome.applied_fill.realized_pnl.amount)
                    signed_quantity, _, unrealized = self._position(
                        ledger=ledger,
                        instrument=instrument,
                        mark_price=latest_mark,
                    )
                    position_value = (
                        signed_quantity * latest_mark
                        if instrument.instrument_type is InstrumentType.SPOT
                        else unrealized
                    )
                    equity_curve.append(
                        EquityPoint(
                            time=backtest_fill.available_time,
                            cash=cash,
                            position_value=canonical_result(position_value),
                            realized_pnl=realized,
                            unrealized_pnl=unrealized,
                            equity=canonical_result(cash + position_value),
                            reporting_asset_id=spec.reporting_asset_id,
                        )
                    )
                if state.filled == state.order.quantity.amount:
                    state.status = VenueOrderStatus.FILLED
                    state.completed_at = event.available_time
                elif state.filled > 0:
                    state.status = VenueOrderStatus.PARTIALLY_FILLED
                if state.order.time_in_force is TimeInForce.IMMEDIATE_OR_CANCEL:
                    if state.status is not VenueOrderStatus.FILLED:
                        state.status = VenueOrderStatus.CANCELED
                        state.completed_at = event.available_time
                elif state.order.time_in_force is TimeInForce.FILL_OR_KILL and not slices:
                    state.status = VenueOrderStatus.REJECTED
                    state.rejection_code = "AQ-BACKTEST-FOK-NOT-FILLABLE"
                    state.completed_at = event.available_time
                if (
                    cancel_time is not None
                    and cancel_time <= event.available_time
                    and state.status
                    in {
                        VenueOrderStatus.ACCEPTED,
                        VenueOrderStatus.PARTIALLY_FILLED,
                    }
                ):
                    state.status = VenueOrderStatus.CANCELED
                    state.completed_at = cancel_time
        signed_quantity, average_entry, unrealized = self._position(
            ledger=ledger,
            instrument=instrument,
            mark_price=latest_mark,
        )
        position_value = (
            signed_quantity * latest_mark
            if instrument.instrument_type is InstrumentType.SPOT
            else unrealized
        )
        if equity_curve[-1].time < spec.end_time:
            equity_curve.append(
                EquityPoint(
                    time=spec.end_time,
                    cash=cash,
                    position_value=canonical_result(position_value),
                    realized_pnl=realized,
                    unrealized_pnl=unrealized,
                    equity=canonical_result(cash + position_value),
                    reporting_asset_id=spec.reporting_asset_id,
                )
            )
        order_results = self._order_results(states, spec.end_time)
        fills_tuple = tuple(fills)
        plan_values = tuple(multi_leg_plans)
        exposures: list[MultiLegExposure] = []
        for plan in plan_values:
            failed_index = failures.get(plan.multi_leg_plan_id)
            exposures.append(
                summarize_multi_leg_exposure(
                    plan=plan,
                    order_results=order_results,
                    fills=fills_tuple,
                    failed_leg_index=failed_index,
                    failure_reason=(
                        "injected deterministic leg failure" if failed_index is not None else None
                    ),
                )
            )
        fees = sum((fill.cost_breakdown.fee for fill in fills), Decimal("0"))
        spread = sum((fill.cost_breakdown.spread for fill in fills), Decimal("0"))
        slippage = sum((fill.cost_breakdown.slippage for fill in fills), Decimal("0"))
        impact = sum((fill.cost_breakdown.impact for fill in fills), Decimal("0"))
        net_pnl = canonical_result(equity_curve[-1].equity - spec.initial_cash.amount)
        gross_pnl = canonical_result(net_pnl + fees + spread + slippage + impact + funding_total)
        attribution = (
            PnLAttributionPoint(
                time=spec.end_time,
                gross_trading_pnl=gross_pnl,
                trading_fees=fees,
                spread_cost=spread,
                slippage_cost=slippage,
                impact_cost=impact,
                funding=funding_total,
                borrow_interest=Decimal("0"),
                net_pnl=net_pnl,
            ),
        )
        positions = (
            PositionPoint(
                time=spec.end_time,
                instrument_id=instrument.instrument_id,
                quantity=signed_quantity,
                average_entry_price=average_entry,
                mark_price=latest_mark,
                unrealized_pnl=unrealized,
            ),
        )
        exposure_tuple = tuple(exposures)
        metrics = calculate_metrics(
            equity_curve=tuple(equity_curve),
            fills=fills_tuple,
            orders=order_results,
            multi_leg_exposures=exposure_tuple,
        )
        economic_hash = canonical_sha256(
            {
                "orders": [
                    {
                        "order_id": str(result.order.backtest_order_id),
                        "status": result.status.value,
                        "filled": str(result.cumulative_filled_quantity),
                        "average_price": (
                            str(result.average_fill_price)
                            if result.average_fill_price is not None
                            else None
                        ),
                    }
                    for result in order_results
                ],
                "fills": [
                    {
                        "order_id": str(fill.backtest_order_id),
                        "side": fill.side.value,
                        "quantity": str(fill.quantity.amount),
                        "price": str(fill.execution_price.amount),
                        "fee": str(fill.fee.amount),
                        "event": str(fill.source_event_id),
                    }
                    for fill in fills
                ],
                "equity": [
                    {"time": point.time.isoformat(), "equity": str(point.equity)}
                    for point in equity_curve
                ],
                "position": str(signed_quantity),
            }
        )
        return BacktestResult(
            spec=spec,
            engine_kind=spec.engine_kind,
            orders=order_results,
            fills=fills_tuple,
            ledger_records=ledger.records,
            positions=positions,
            equity_curve=tuple(equity_curve),
            pnl_attribution=attribution,
            metrics=metrics,
            multi_leg_exposures=exposure_tuple,
            events_processed=len(timeline),
            economic_event_hash=economic_hash,
            precision_levels=tuple(
                sorted({fill.precision for fill in fills}, key=lambda item: item.value)
            ),
            warnings=tuple(
                rule.approximation
                for rule in self.rule_book.rules
                if rule.approximation is not None
            ),
        )
