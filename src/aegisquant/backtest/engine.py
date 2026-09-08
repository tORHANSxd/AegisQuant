"""Deterministic event backtest engine connected to the P05 authoritative ledger."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from pydantic import TypeAdapter

from aegisquant.accounting.ledger import AccountingPolicy, LedgerEngine, calculate_contract_pnl
from aegisquant.accounting.models import (
    AccountingInstrument,
    CashflowDirection,
    CashflowEvent,
    CashflowType,
)
from aegisquant.backtest.costs import HistoricalCostBook, execution_price_and_cost, funding_cost
from aegisquant.backtest.fills import decide_fills, exit_trigger_reference
from aegisquant.backtest.margin import (
    create_liquidation_order,
    evaluate_margin,
    liquidation_instruction,
    margin_policy_at,
    select_margin_bracket,
)
from aegisquant.backtest.metrics import calculate_metrics
from aegisquant.backtest.models import (
    BacktestFill,
    BacktestOrder,
    BacktestOrderResult,
    BacktestResult,
    BacktestRunSpec,
    BarEvent,
    CancelRequest,
    CostBreakdown,
    EquityPoint,
    ExitTrigger,
    FaultType,
    FaultWindow,
    FillPrecision,
    FillSlice,
    FundingEvent,
    L2BookEvent,
    LatencyPolicy,
    LiquidityRole,
    MarginBracket,
    MarginMode,
    MarginPolicy,
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
from aegisquant.data.market import ContractForm, InstrumentType
from aegisquant.domain.execution import Fill, OrderSide, OrderType, TimeInForce, VenueOrderStatus
from aegisquant.domain.identifiers import (
    ArtifactId,
    BacktestOrderId,
    ClientOrderId,
    FillId,
    IdempotencyKey,
    MarginPolicyId,
    MultiLegPlanId,
    OrderIntentId,
    VenueId,
    VenueOrderId,
)
from aegisquant.domain.values import Money, Price, Quantity, canonical_result

_EQUITY_ADAPTER = TypeAdapter(tuple[EquityPoint, ...])


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
    triggered: bool = False
    liquidation_penalty_bps: Decimal | None = None


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
        margin_policies: Iterable[MarginPolicy] = (),
    ) -> None:
        self.project_root = project_root
        self.cost_book = cost_book
        self.rule_book = rule_book
        self.latency_policy = latency_policy
        self.liquidity_consumption = liquidity_consumption
        self.margin_policies = tuple(margin_policies)

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
                    and event.event_time >= arrival
                    and event.event_time > order.decision_time
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
        settlement_quantity: Decimal = Decimal("0"),
    ) -> tuple[BacktestFill, Fill]:
        state.fill_sequence += 1
        schedule = self.cost_book.at(state.order, fill_slice.event_time)
        execution_price, breakdown = execution_price_and_cost(
            order=state.order,
            fill_slice=fill_slice,
            schedule=schedule,
            base_asset_id=instrument.base_asset_id,
            quote_asset_id=instrument.quote_asset_id,
            contract_multiplier=instrument.contract_multiplier,
            settlement_quantity=settlement_quantity,
            liquidation_penalty_bps=state.liquidation_penalty_bps or Decimal("0"),
        )
        fill_id = FillId(f"simfill:{state.order.backtest_order_id}:{state.fill_sequence}")
        if state.venue_order_id is None:
            raise RuntimeError("accepted simulated order lacks venue order id")
        fee = _fee_in_settlement_asset(
            quote_fee=breakdown.fee + breakdown.settlement_fee + breakdown.liquidation_penalty,
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
        if (
            instrument.settlement_asset_id != spec.reporting_asset_id
            or instrument.quote_asset_id != spec.reporting_asset_id
        ):
            raise ValueError("AQ-BACKTEST-REPORTING-ASSET-FX-REQUIRED")
        if instrument.contract_form is ContractForm.INVERSE:
            raise ValueError("AQ-BACKTEST-INVERSE-MARGIN-NOT-IMPLEMENTED")
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
        unique_events: dict[str, MarketEvent] = {}
        for event in events:
            key = str(event.event_id)
            if key in unique_events and unique_events[key] != event:
                raise ValueError("AQ-BACKTEST-MARKET-EVENT-ID-CONFLICT")
            unique_events[key] = event
        events = tuple(unique_events.values())
        order_values = tuple(
            sorted(orders, key=lambda item: (item.submitted_at, str(item.backtest_order_id)))
        )
        if len({order.backtest_order_id for order in order_values}) != len(order_values):
            raise ValueError("duplicate backtest order id")
        if len({order.client_order_id for order in order_values}) != len(order_values):
            raise ValueError("duplicate client order id")
        if any(
            order.instrument_id != instrument.instrument_id
            or order.quantity.asset_id != instrument.quantity_asset_id
            for order in order_values
        ):
            raise ValueError("AQ-BACKTEST-ORDER-INSTRUMENT-OR-QUANTITY-UNIT-MISMATCH")
        oco_groups: dict[str, list[BacktestOrder]] = {}
        for order in order_values:
            if order.oco_group_id is not None:
                oco_groups.setdefault(order.oco_group_id, []).append(order)
        for group in oco_groups.values():
            if len(group) != 2 or {order.exit_trigger for order in group} != set(ExitTrigger):
                raise ValueError("AQ-BACKTEST-OCO-REQUIRES-ONE-STOP-AND-ONE-TAKE-PROFIT")
            if group[0].side is not group[1].side or group[0].venue_id != group[1].venue_id:
                raise ValueError("AQ-BACKTEST-OCO-EXIT-SIDES-OR-VENUES-DIFFER")
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
        borrow_total = Decimal("0")
        borrowed_quantity = Decimal("0")
        borrow_accrued_at = spec.start_time
        run_warnings: list[str] = []
        liquidation_sequence = 0
        is_spot = instrument.instrument_type is InstrumentType.SPOT
        borrow_policy = spec.spot_borrow_policy
        borrow_margin = (
            MarginPolicy(
                margin_policy_id=MarginPolicyId("explicit-spot-borrow-margin"),
                version="alpha-v4-spot-borrow",
                venue_id=VenueId(instrument.venue),
                instrument_id=instrument.instrument_id,
                mode=MarginMode.CROSS,
                effective_from=spec.start_time,
                brackets=(
                    MarginBracket(
                        notional_floor=Decimal("0"),
                        maximum_leverage=Decimal("1") / borrow_policy.initial_margin_rate,
                        initial_margin_rate=borrow_policy.initial_margin_rate,
                        maintenance_margin_rate=borrow_policy.maintenance_margin_rate,
                    ),
                ),
                liquidation_penalty_bps=borrow_policy.liquidation_penalty_bps,
                conservative_buffer_rate=Decimal("0"),
                collateral_asset_id=spec.reporting_asset_id,
                source=borrow_policy.source,
            )
            if borrow_policy is not None
            else None
        )
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
        cached_revision = -1
        cached_position = (Decimal("0"), None, Decimal("0"))
        cached_mark = latest_mark

        def position_at(mark: Decimal) -> tuple[Decimal, Decimal | None, Decimal]:
            # Open lots change only on fills. Reuse their basis across quiet market events.
            nonlocal cached_revision, cached_position, cached_mark
            if cached_revision != len(fills) or instrument.contract_form is ContractForm.INVERSE:
                cached_position = self._position(
                    ledger=ledger, instrument=instrument, mark_price=mark
                )
                cached_revision = len(fills)
                cached_mark = mark
            quantity, average, anchored_pnl = cached_position
            multiplier = (
                Decimal("1")
                if instrument.instrument_type is InstrumentType.SPOT
                else instrument.contract_multiplier
            )
            return (
                quantity,
                average,
                canonical_result(anchored_pnl + quantity * multiplier * (mark - cached_mark)),
            )

        def record_equity(at_time: datetime) -> None:
            quantity, _, unrealized_pnl = position_at(latest_mark)
            position_value = (
                quantity * latest_mark
                if instrument.instrument_type is InstrumentType.SPOT
                else unrealized_pnl
            )
            point = EquityPoint(
                time=at_time,
                cash=cash,
                position_value=canonical_result(position_value),
                realized_pnl=realized,
                unrealized_pnl=unrealized_pnl,
                equity=canonical_result(cash + position_value),
                reporting_asset_id=spec.reporting_asset_id,
            )
            if equity_curve[-1].time == at_time:
                equity_curve[-1] = point
            else:
                equity_curve.append(point)

        def margin_at(at_time: datetime, venue_id: VenueId) -> MarginPolicy:
            if is_spot:
                if borrow_margin is None:
                    raise ValueError("AQ-BACKTEST-SPOT-BORROW-NOT-AUTHORIZED")
                return borrow_margin
            policy = margin_policy_at(
                self.margin_policies,
                venue_id=venue_id,
                instrument_id=instrument.instrument_id,
                at_time=at_time,
            )
            if policy.collateral_asset_id != spec.reporting_asset_id:
                raise ValueError("AQ-BACKTEST-MARGIN-COLLATERAL-FX-REQUIRED")
            if policy.mode is not MarginMode.CROSS:
                raise ValueError("AQ-BACKTEST-ISOLATED-COLLATERAL-ALLOCATION-REQUIRED")
            return policy

        def cashflow(
            kind: CashflowType,
            amount: Decimal,
            *,
            at_time: datetime,
            identity: str,
            asset: Money | None = None,
        ) -> None:
            if amount == 0:
                return
            ledger.process_cashflow(
                CashflowEvent(
                    event_id=ArtifactId(identity),
                    venue=instrument.venue,
                    cashflow_type=kind,
                    direction=CashflowDirection.INFLOW if amount > 0 else CashflowDirection.OUTFLOW,
                    amount=asset or Money(amount=abs(amount), asset_id=spec.reporting_asset_id),
                    event_time=at_time,
                    recorded_at=at_time,
                    idempotency_key=IdempotencyKey(identity),
                    reference=identity,
                )
            )

        def accrue_borrow(at_time: datetime) -> None:
            nonlocal cash, borrow_total, borrow_accrued_at
            if borrowed_quantity > 0 and at_time > borrow_accrued_at:
                cost = self.cost_book.borrow_cost_between(
                    venue_id=VenueId(instrument.venue),
                    instrument_id=instrument.instrument_id,
                    start=borrow_accrued_at,
                    end=at_time,
                    borrowed_notional=borrowed_quantity * latest_mark,
                )
                cashflow(
                    CashflowType.BORROW_INTEREST,
                    -cost,
                    at_time=at_time,
                    identity=f"borrow-interest:{spec.run_id}:{at_time:%Y%m%dT%H%M%S%fZ}",
                )
                cash = canonical_result(cash - cost)
                borrow_total = canonical_result(borrow_total + cost)
            borrow_accrued_at = at_time

        def apply_slice(state: _MutableOrderState, fill_slice: FillSlice) -> None:
            nonlocal cash, realized, borrowed_quantity
            quantity, _, _ = position_at(fill_slice.reference_price)
            direction = Decimal("1") if state.order.side is OrderSide.BUY else Decimal("-1")
            closing = (
                min(abs(quantity), fill_slice.quantity)
                if quantity * direction < 0
                else Decimal("0")
            )
            projected = quantity + direction * fill_slice.quantity
            if is_spot and max(Decimal("0"), -projected) > borrowed_quantity:
                additional = -projected - borrowed_quantity
                cashflow(
                    CashflowType.BORROW,
                    additional,
                    at_time=fill_slice.available_time,
                    identity=f"borrow:{state.order.backtest_order_id}:{state.fill_sequence + 1}",
                    asset=Money(amount=additional, asset_id=instrument.base_asset_id),
                )
                borrowed_quantity += additional
            backtest_fill, ledger_fill = self._backtest_fill(
                state=state,
                fill_slice=fill_slice,
                instrument=instrument,
                settlement_quantity=closing,
            )
            outcome = ledger.process_fill(ledger_fill, instrument)
            if not outcome.inserted:
                raise RuntimeError("AQ-BACKTEST-DUPLICATE-FILL-APPLICATION")
            fills.append(backtest_fill)
            state.filled = canonical_result(state.filled + fill_slice.quantity)
            state.fill_value = canonical_result(
                state.fill_value + fill_slice.quantity * backtest_fill.execution_price.amount
            )
            if self.liquidity_consumption:
                event_capacity[str(fill_slice.source_event_id)] = canonical_result(
                    event_capacity[str(fill_slice.source_event_id)] - fill_slice.quantity
                )
                level_key = (
                    str(fill_slice.source_event_id),
                    state.order.side,
                    fill_slice.reference_price,
                )
                if level_key in level_remaining:
                    level_remaining[level_key] -= fill_slice.quantity
            if is_spot:
                notional = fill_slice.quantity * backtest_fill.execution_price.amount
                cash = canonical_result(cash - direction * notional - backtest_fill.fee.amount)
                repaid = min(borrowed_quantity, closing) if direction > 0 else Decimal("0")
                if repaid > 0:
                    cashflow(
                        CashflowType.REPAY,
                        -repaid,
                        at_time=fill_slice.available_time,
                        identity=f"repay:{backtest_fill.fill_id}",
                        asset=Money(amount=repaid, asset_id=instrument.base_asset_id),
                    )
                    borrowed_quantity = canonical_result(borrowed_quantity - repaid)
            else:
                cash = canonical_result(
                    cash + outcome.applied_fill.realized_pnl.amount - backtest_fill.fee.amount
                )
            realized = canonical_result(realized + outcome.applied_fill.realized_pnl.amount)

        def reject(state: _MutableOrderState, code: str, at_time: datetime) -> None:
            state.status = VenueOrderStatus.REJECTED
            state.rejection_code = code
            state.completed_at = at_time

        def execution_rejection(
            state: _MutableOrderState,
            fill_slice: FillSlice,
        ) -> str | None:
            quantity, _, unrealized_pnl = position_at(fill_slice.reference_price)
            direction = Decimal("1") if state.order.side is OrderSide.BUY else Decimal("-1")
            projected = canonical_result(quantity + direction * fill_slice.quantity)
            closing = (
                min(abs(quantity), fill_slice.quantity)
                if quantity * direction < 0
                else Decimal("0")
            )
            execution, cost = execution_price_and_cost(
                order=state.order,
                fill_slice=fill_slice,
                schedule=self.cost_book.at(state.order, fill_slice.event_time),
                base_asset_id=instrument.base_asset_id,
                quote_asset_id=instrument.quote_asset_id,
                contract_multiplier=instrument.contract_multiplier,
                settlement_quantity=closing,
            )
            if is_spot:
                after_cash = (
                    cash
                    - direction * fill_slice.quantity * execution.amount
                    - cost.fee
                    - cost.settlement_fee
                )
                if direction > 0 and after_cash < 0:
                    return "AQ-BACKTEST-SPOT-INSUFFICIENT-CASH"
                if projected >= 0:
                    return None
                if borrow_policy is None:
                    return "AQ-BACKTEST-SPOT-INSUFFICIENT-INVENTORY"
                if -projected > borrow_policy.maximum_quantity:
                    return "AQ-BACKTEST-SPOT-BORROW-LIMIT-EXCEEDED"
                equity_after = after_cash + projected * fill_slice.reference_price
            else:
                equity_after = cash + unrealized_pnl - cost.total
            # Reducing a losing position stays possible; every increase needs fresh collateral.
            increases = abs(projected) > abs(quantity) or projected * quantity < 0
            if not increases:
                return None
            policy = margin_at(fill_slice.event_time, state.order.venue_id)
            notional = abs(projected) * instrument.contract_multiplier * fill_slice.reference_price
            bracket = select_margin_bracket(policy, notional)
            if equity_after < notional * bracket.initial_margin_rate:
                return "AQ-BACKTEST-INITIAL-MARGIN-INSUFFICIENT"
            if equity_after <= 0 or notional > equity_after * bracket.maximum_leverage:
                return "AQ-BACKTEST-MARGIN-LEVERAGE-EXCEEDED"
            return None

        event_capacity: dict[str, Decimal] = {}
        level_remaining: dict[tuple[str, OrderSide, Decimal], Decimal] = {}
        raw_capacity = Decimal("0")

        def available_slices(
            order: BacktestOrder, slices: tuple[FillSlice, ...]
        ) -> tuple[FillSlice, ...]:
            if not self.liquidity_consumption or not slices:
                return slices
            limited = tuple(
                slice_.model_copy(
                    update={
                        "quantity": min(
                            slice_.quantity,
                            level_remaining.get(
                                (str(slice_.source_event_id), order.side, slice_.reference_price),
                                slice_.quantity,
                            ),
                        )
                    }
                )
                for slice_ in slices
            )
            return self._clip_for_consumption(
                tuple(slice_ for slice_ in limited if slice_.quantity > 0),
                event_capacity[str(slices[0].source_event_id)],
            )

        def market_slices(
            order: BacktestOrder,
            event: MarketEvent,
            remaining: Decimal,
            participation_cap: Decimal,
            *,
            triggered: bool = False,
        ) -> tuple[FillSlice, ...]:
            if isinstance(event, L2BookEvent) and self.liquidity_consumption:
                levels = event.asks if order.side is OrderSide.BUY else event.bids
                remaining_levels = tuple(
                    level.model_copy(
                        update={
                            "quantity": level_remaining[
                                (str(event.event_id), order.side, level.price)
                            ]
                        }
                    )
                    for level in levels
                )
                residual_book = event.model_copy(
                    update={"asks" if order.side is OrderSide.BUY else "bids": remaining_levels}
                )
                slices = decide_fills(
                    order=order,
                    event=residual_book,
                    remaining=remaining,
                    participation_cap=Decimal("1"),
                    triggered=triggered,
                )
                raw_by_price = {
                    level.price: level.quantity * (Decimal("1") - participation_cap)
                    + level_remaining[(str(event.event_id), order.side, level.price)]
                    for level in levels
                }
                return tuple(
                    slice_.model_copy(
                        update={"available_liquidity": raw_by_price[slice_.reference_price]}
                    )
                    for slice_ in slices
                )
            return decide_fills(
                order=order,
                event=event,
                remaining=remaining,
                participation_cap=participation_cap,
                triggered=triggered,
            )

        def liquidate_at(mark: Decimal, at_time: datetime, event: MarketEvent | None) -> None:
            nonlocal liquidation_sequence
            if is_spot and borrow_policy is None:
                return
            quantity, average, _ = position_at(mark)
            if quantity == 0 or (is_spot and quantity > 0):
                return
            if average is None:
                raise RuntimeError("nonzero position lacks an entry basis")
            venue = event.venue_id if event is not None else VenueId(instrument.venue)
            policy = margin_at(at_time, venue)
            evaluation = evaluate_margin(
                policy=policy,
                signed_quantity=quantity,
                entry_price=average,
                mark_price=mark,
                collateral=cash + quantity * average if is_spot else cash,
                contract_multiplier=instrument.contract_multiplier,
            )
            pending = next(
                (
                    candidate
                    for candidate in states.values()
                    if candidate.liquidation_penalty_bps is not None
                    and candidate.status
                    in {VenueOrderStatus.ACCEPTED, VenueOrderStatus.PARTIALLY_FILLED}
                ),
                None,
            )
            if not evaluation.liquidation_required and pending is None:
                return
            if pending is None:
                liquidation_sequence += 1
                instruction = liquidation_instruction(evaluation=evaluation, policy=policy)
                liquidation = create_liquidation_order(
                    instruction=instruction,
                    instrument=instrument,
                    venue_id=venue,
                    decision_time=at_time,
                    identity=f"{spec.run_id}:{liquidation_sequence}",
                )
                # Penalty is a separate ledger fee; do not also use the penalized price.
                pending = _MutableOrderState(
                    order=liquidation,
                    arrival_time=at_time,
                    status=VenueOrderStatus.ACCEPTED,
                    venue_order_id=VenueOrderId(f"simorder:{liquidation.backtest_order_id}"),
                    liquidation_penalty_bps=policy.liquidation_penalty_bps,
                )
                for candidate in states.values():
                    if candidate.status in {
                        VenueOrderStatus.ACCEPTED,
                        VenueOrderStatus.PARTIALLY_FILLED,
                    }:
                        candidate.status = VenueOrderStatus.CANCELED
                        candidate.completed_at = at_time
                        candidate.rejection_code = "AQ-BACKTEST-CANCELED-BY-LIQUIDATION"
                states[liquidation.backtest_order_id] = pending
            if event is None:
                warning = "AQ-BACKTEST-FUNDING-MARGIN-BREACH-AWAITS-NEXT-EXECUTABLE-MARKET"
                if warning not in run_warnings:
                    run_warnings.append(warning)
                return
            remaining = min(abs(quantity), pending.order.quantity.amount - pending.filled)
            if isinstance(event, BarEvent):
                liquidation_slices = (
                    FillSlice(
                        quantity=remaining,
                        reference_price=mark,
                        available_liquidity=raw_capacity,
                        precision=FillPrecision.BAR_CONSERVATIVE,
                        liquidity_role=LiquidityRole.TAKER,
                        source_event_id=event.event_id,
                        event_time=at_time,
                        available_time=at_time,
                    ),
                )
            else:
                liquidation_slices = market_slices(
                    order=pending.order,
                    event=event,
                    remaining=remaining,
                    participation_cap=self.cost_book.at(pending.order, at_time).participation_cap,
                )
            liquidation_slices = available_slices(pending.order, liquidation_slices)
            for slice_ in liquidation_slices:
                apply_slice(pending, slice_)
            executable = sum((slice_.quantity for slice_ in liquidation_slices), Decimal("0"))
            pending.status = (
                VenueOrderStatus.FILLED
                if pending.filled == pending.order.quantity.amount
                else VenueOrderStatus.CANCELED
            )
            pending.completed_at = at_time
            if executable < remaining:
                warning = "AQ-BACKTEST-LIQUIDATION-INCOMPLETE-DUE-TO-LIQUIDITY"
                if warning not in run_warnings:
                    run_warnings.append(warning)

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
        if is_spot and funding_values:
            raise ValueError("AQ-BACKTEST-SPOT-CANNOT-ACCRUE-PERPETUAL-FUNDING")
        unique_funding: dict[str, FundingEvent] = {}
        for funding_event in funding_values:
            key = str(funding_event.event_id)
            if key in unique_funding and unique_funding[key] != funding_event:
                raise ValueError("AQ-BACKTEST-FUNDING-EVENT-ID-CONFLICT")
            if funding_event.instrument_id != instrument.instrument_id:
                raise ValueError("AQ-BACKTEST-FUNDING-INSTRUMENT-MISMATCH")
            unique_funding[key] = funding_event
        funding_values = tuple(unique_funding.values())
        timeline: list[tuple[datetime, int, MarketEvent | FundingEvent]] = []
        timeline.extend((event.available_time, 0, event) for event in events)
        timeline.extend((event.available_time, 1, event) for event in funding_values)
        timeline.sort(key=lambda item: (item[0], item[1]))
        active_states = sorted(
            states.values(),
            key=lambda state: (
                0
                if state.order.exit_trigger is ExitTrigger.STOP_LOSS
                else 2
                if state.order.exit_trigger is ExitTrigger.TAKE_PROFIT
                else 1,
                state.order.submitted_at,
                str(state.order.backtest_order_id),
            ),
        )
        for timeline_index, (at_time, kind, item) in enumerate(timeline):
            accrue_borrow(at_time)
            timestamp_complete = (
                timeline_index + 1 == len(timeline) or timeline[timeline_index + 1][0] != at_time
            )
            if kind == 1:
                funding_event = item
                if not isinstance(funding_event, FundingEvent):
                    raise TypeError("funding timeline item has the wrong type")
                signed_quantity, _, unrealized = position_at(funding_event.mark_price)
                cost = funding_cost(
                    signed_quantity=signed_quantity,
                    mark_price=funding_event.mark_price,
                    funding_rate=funding_event.funding_rate,
                    contract_multiplier=instrument.contract_multiplier,
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
                liquidate_at(funding_event.mark_price, at_time, None)
                if timestamp_complete:
                    record_equity(at_time)
                continue
            event = item
            if not isinstance(event, (BarEvent, TradeQuoteEvent, L2BookEvent)):
                raise TypeError("market timeline item has the wrong type")
            latest_mark = _event_mark(event)
            if is_spot and borrow_policy is None and not active_states and event is not events[-1]:
                if timestamp_complete:
                    record_equity(at_time)
                continue
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
            capacity_schedule = self.cost_book.for_instrument(
                event.venue_id, event.instrument_id, event.event_time
            )
            event_capacity[capacity_key] = raw_capacity * capacity_schedule.participation_cap
            if isinstance(event, L2BookEvent):
                for side, levels in ((OrderSide.BUY, event.asks), (OrderSide.SELL, event.bids)):
                    for level in levels:
                        level_remaining[(capacity_key, side, level.price)] = (
                            level.quantity * capacity_schedule.participation_cap
                        )
            opening_mark = event.open if isinstance(event, BarEvent) else _event_mark(event)
            liquidate_at(opening_mark, at_time, event)
            for state in active_states:
                if state.status not in {
                    VenueOrderStatus.ACCEPTED,
                    VenueOrderStatus.PARTIALLY_FILLED,
                }:
                    continue
                if event.available_time < state.arrival_time:
                    continue
                if state.order.venue_id != event.venue_id:
                    continue
                if (
                    event.event_time <= state.order.decision_time
                    or event.event_time < state.arrival_time
                ):
                    continue
                if isinstance(event, BarEvent) and (
                    state.order.exit_trigger is ExitTrigger.TAKE_PROFIT
                    or state.order.order_type is OrderType.LIMIT
                ):
                    held_now, _, _ = position_at(opening_mark)
                    liquidate_at(event.low if held_now > 0 else event.high, at_time, event)
                    if state.status not in {
                        VenueOrderStatus.ACCEPTED,
                        VenueOrderStatus.PARTIALLY_FILLED,
                    }:
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
                held, _, _ = position_at(opening_mark)
                direction = Decimal("1") if state.order.side is OrderSide.BUY else Decimal("-1")
                if state.order.reduce_only:
                    if held * direction >= 0:
                        reject(state, "AQ-BACKTEST-REDUCE-ONLY-NO-REDUCIBLE-POSITION", at_time)
                        continue
                    remaining = min(remaining, abs(held))
                was_triggered = state.triggered
                if state.order.exit_trigger is not None and not state.triggered:
                    if exit_trigger_reference(state.order, event) is None:
                        continue
                    state.triggered = True
                    if state.order.oco_group_id is not None:
                        for sibling in oco_groups[state.order.oco_group_id]:
                            if sibling.backtest_order_id != state.order.backtest_order_id:
                                other = states[sibling.backtest_order_id]
                                if other.status in {
                                    VenueOrderStatus.ACCEPTED,
                                    VenueOrderStatus.PARTIALLY_FILLED,
                                }:
                                    other.status = VenueOrderStatus.CANCELED
                                    other.completed_at = at_time
                                    other.rejection_code = "AQ-BACKTEST-OCO-SIBLING-TRIGGERED"
                schedule = self.cost_book.at(state.order, event.event_time)
                effective_order = state.order.model_copy(
                    update={
                        "quantity": Quantity(
                            amount=remaining, asset_id=instrument.quantity_asset_id
                        )
                    }
                )
                rule_decision = self.rule_book.validate_order(
                    effective_order,
                    reference_price=_event_reference(event, state.order.side),
                    event_time=event.event_time,
                    contract_multiplier=instrument.contract_multiplier,
                )
                if not rule_decision.valid:
                    reject(
                        state, rule_decision.rejection_code or "AQ-BACKTEST-RULE-INVALID", at_time
                    )
                    continue
                slices = market_slices(
                    order=state.order,
                    event=event,
                    remaining=remaining,
                    participation_cap=schedule.participation_cap,
                    triggered=was_triggered,
                )
                slices = available_slices(state.order, slices)
                if slices:
                    worst_reference = (
                        max(slice_.reference_price for slice_ in slices)
                        if state.order.side is OrderSide.BUY
                        else min(slice_.reference_price for slice_ in slices)
                    )
                    preview = slices[0].model_copy(
                        update={"quantity": remaining, "reference_price": worst_reference}
                    )
                    rejection = execution_rejection(state, preview)
                    if rejection is not None:
                        reject(state, rejection, at_time)
                        continue
                if (
                    state.order.time_in_force is TimeInForce.FILL_OR_KILL
                    and sum((slice_.quantity for slice_ in slices), Decimal("0")) < remaining
                ):
                    slices = ()
                for fill_slice in slices:
                    rejection = execution_rejection(state, fill_slice)
                    if rejection is not None:
                        reject(state, rejection, at_time)
                        break
                    apply_slice(state, fill_slice)
                if state.status is VenueOrderStatus.REJECTED:
                    continue
                if state.filled == state.order.quantity.amount:
                    state.status = VenueOrderStatus.FILLED
                    state.completed_at = event.available_time
                elif state.filled > 0:
                    state.status = VenueOrderStatus.PARTIALLY_FILLED
                if (
                    state.order.reduce_only
                    and position_at(opening_mark)[0] == 0
                    and state.status is not VenueOrderStatus.FILLED
                ):
                    state.status = VenueOrderStatus.CANCELED
                    state.completed_at = at_time
                    state.rejection_code = "AQ-BACKTEST-REDUCE-ONLY-EXCESS-CLIPPED"
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
            held_after, _, _ = position_at(latest_mark)
            if isinstance(event, BarEvent) and held_after != 0:
                adverse_mark = event.low if held_after > 0 else event.high
                liquidate_at(adverse_mark, at_time, event)
            liquidate_at(latest_mark, at_time, event)
            active_states = [
                state
                for state in active_states
                if state.status in {VenueOrderStatus.ACCEPTED, VenueOrderStatus.PARTIALLY_FILLED}
            ]
            if timestamp_complete:
                record_equity(at_time)
        accrue_borrow(spec.end_time)
        liquidate_at(latest_mark, spec.end_time, None)
        signed_quantity, average_entry, unrealized = position_at(latest_mark)
        record_equity(spec.end_time)
        final_mtm = equity_curve[-1].equity
        forced_close_equity = final_mtm
        forced_close_mark_adjustment = Decimal("0")
        exit_cost = None
        close_status = "NO_POSITION"
        if signed_quantity != 0:
            close_order = BacktestOrder(
                backtest_order_id=BacktestOrderId(f"terminal-close:{spec.run_id}"),
                client_order_id=ClientOrderId(f"terminal-close:{spec.run_id}"),
                order_intent_id=OrderIntentId(f"terminal-close:{spec.run_id}"),
                instrument_id=instrument.instrument_id,
                venue_id=events[-1].venue_id,
                side=OrderSide.SELL if signed_quantity > 0 else OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Quantity(
                    amount=abs(signed_quantity), asset_id=instrument.quantity_asset_id
                ),
                time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
                decision_time=spec.end_time,
                submitted_at=spec.end_time,
                reduce_only=True,
            )
            close_slice = FillSlice(
                quantity=abs(signed_quantity),
                reference_price=latest_mark,
                available_liquidity=raw_capacity,
                precision=FillPrecision.BAR_CONSERVATIVE,
                liquidity_role=LiquidityRole.TAKER,
                source_event_id=events[-1].event_id,
                event_time=spec.end_time,
                available_time=spec.end_time,
            )
            schedule = self.cost_book.at(close_order, spec.end_time)
            if isinstance(events[-1], BarEvent):
                close_slices = (close_slice,)
            else:
                close_slices = market_slices(
                    order=close_order,
                    event=events[-1],
                    remaining=abs(signed_quantity),
                    participation_cap=schedule.participation_cap,
                )
            close_slices = available_slices(close_order, close_slices)
            closed_quantity = sum((slice_.quantity for slice_ in close_slices), Decimal("0"))
            if closed_quantity == abs(signed_quantity):
                costs: list[CostBreakdown] = []
                for slice_ in close_slices:
                    _, cost = execution_price_and_cost(
                        order=close_order,
                        fill_slice=slice_,
                        schedule=schedule,
                        base_asset_id=instrument.base_asset_id,
                        quote_asset_id=instrument.quote_asset_id,
                        contract_multiplier=instrument.contract_multiplier,
                        settlement_quantity=slice_.quantity,
                    )
                    costs.append(cost)
                    forced_close_mark_adjustment += (
                        (Decimal("1") if signed_quantity > 0 else Decimal("-1"))
                        * slice_.quantity
                        * instrument.contract_multiplier
                        * (slice_.reference_price - latest_mark)
                    )
                exit_cost = costs[0].model_copy(
                    update={
                        field: sum((getattr(cost, field) for cost in costs), Decimal("0"))
                        for field in (
                            "gross_notional",
                            "fee",
                            "spread",
                            "slippage",
                            "impact",
                            "funding",
                            "borrow_interest",
                            "settlement_fee",
                            "liquidation_penalty",
                        )
                    }
                )
                forced_close_equity = canonical_result(
                    final_mtm + forced_close_mark_adjustment - exit_cost.total
                )
                close_status = "SIMULATED_AT_FINAL_MARK_WITH_FULL_EXIT_COST"
            else:
                forced_close_equity = None
                close_status = "INSUFFICIENT_EXIT_LIQUIDITY"
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
        settlement_fees = sum((fill.cost_breakdown.settlement_fee for fill in fills), Decimal("0"))
        liquidation_penalties = sum(
            (fill.cost_breakdown.liquidation_penalty for fill in fills), Decimal("0")
        )
        net_pnl = canonical_result(equity_curve[-1].equity - spec.initial_cash.amount)
        gross_pnl = canonical_result(
            net_pnl
            + fees
            + spread
            + slippage
            + impact
            + funding_total
            + borrow_total
            + settlement_fees
            + liquidation_penalties
        )
        reference_pnl = sum(
            (
                (Decimal("1") if fill.side is OrderSide.BUY else Decimal("-1"))
                * fill.quantity.amount
                * instrument.contract_multiplier
                * (latest_mark - fill.reference_price.amount)
                for fill in fills
            ),
            Decimal("0"),
        )
        identity_residual = canonical_result(reference_pnl - gross_pnl)
        if abs(identity_residual) > Decimal("1e-12") * max(Decimal("1"), spec.initial_cash.amount):
            raise ValueError("AQ-BACKTEST-COST-IDENTITY-FAILED")
        attribution = (
            PnLAttributionPoint(
                time=spec.end_time,
                gross_trading_pnl=gross_pnl,
                trading_fees=fees,
                spread_cost=spread,
                slippage_cost=slippage,
                impact_cost=impact,
                funding=funding_total,
                borrow_interest=borrow_total,
                settlement_fees=settlement_fees,
                liquidation_penalties=liquidation_penalties,
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
            frequency_seconds=spec.metric_frequency_seconds,
            initial_equity=spec.initial_cash.amount,
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
                "equity_schema": "alpha-v4-every-market-event",
                "equity_sha256": sha256(
                    _EQUITY_ADAPTER.dump_json(
                        tuple(equity_curve), include={"__all__": {"time", "equity"}}
                    )
                ).hexdigest(),
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
            mark_to_market_final_equity=final_mtm,
            forced_close_final_equity=forced_close_equity,
            forced_close_cost=exit_cost,
            forced_close_mark_adjustment=canonical_result(forced_close_mark_adjustment),
            forced_close_status=close_status,
            cost_identity_residual=identity_residual,
            precision_levels=tuple(
                sorted({fill.precision for fill in fills}, key=lambda item: item.value)
            ),
            warnings=(
                *run_warnings,
                *(
                    rule.approximation
                    for rule in self.rule_book.rules
                    if rule.approximation is not None
                ),
            ),
        )
