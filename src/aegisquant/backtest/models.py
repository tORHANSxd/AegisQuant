"""Strict P06 backtest contracts shared by vector and event engines."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from aegisquant.accounting.models import LedgerRecord
from aegisquant.data.hashing import ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce, VenueOrderStatus
from aegisquant.domain.identifiers import (
    AssetId,
    BacktestEventId,
    BacktestOrderId,
    ClientOrderId,
    CostScheduleId,
    FillId,
    InstrumentId,
    InstrumentRuleId,
    MarginPolicyId,
    MultiLegPlanId,
    OrderIntentId,
    RunId,
    StrategyId,
    StrategyVersionId,
    StressScenarioId,
    VenueId,
    VenueOrderId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    Money,
    NonNegativeDecimal,
    PositiveDecimal,
    Price,
    Quantity,
    UnitInterval,
    canonical_result,
)

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class EngineKind(StrEnum):
    VECTOR = "VECTOR"
    EVENT = "EVENT"


class FillPrecision(StrEnum):
    BAR_CONSERVATIVE = "BAR_CONSERVATIVE"
    TRADE_QUOTE = "TRADE_QUOTE"
    L2_DEPTH = "L2_DEPTH"


class LiquidityRole(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"


class MarginMode(StrEnum):
    CROSS = "CROSS"
    ISOLATED = "ISOLATED"


class ExitTrigger(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


class SpotBorrowPolicy(DomainModel):
    """Explicit quote-settled borrowing assumptions; absent means no spot borrowing."""

    maximum_quantity: PositiveDecimal
    initial_margin_rate: UnitInterval = Decimal("1")
    maintenance_margin_rate: UnitInterval = Decimal("0.30")
    liquidation_penalty_bps: NonNegativeDecimal = Decimal("50")
    source: str

    @model_validator(mode="after")
    def validate_borrow(self) -> SpotBorrowPolicy:
        if not 0 < self.maintenance_margin_rate <= self.initial_margin_rate:
            raise ValueError("borrow margin rates must satisfy 0 < maintenance <= initial")
        if not self.source.strip():
            raise ValueError("borrow policy requires a source")
        return self


class FaultType(StrEnum):
    DISCONNECT = "DISCONNECT"
    VENUE_HALT = "VENUE_HALT"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"


class StressType(StrEnum):
    COST_MULTIPLIER = "COST_MULTIPLIER"
    LATENCY_MULTIPLIER = "LATENCY_MULTIPLIER"
    LIQUIDITY_FACTOR = "LIQUIDITY_FACTOR"
    CORRELATION_SHOCK = "CORRELATION_SHOCK"
    STABLECOIN_DEPEG = "STABLECOIN_DEPEG"
    VENUE_HALT = "VENUE_HALT"
    PRICE_GAP = "PRICE_GAP"
    FUNDING_SHOCK = "FUNDING_SHOCK"
    ORDER_BOOK_GAP = "ORDER_BOOK_GAP"
    RATE_LIMIT_DISCONNECT = "RATE_LIMIT_DISCONNECT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    DATA_LAG = "DATA_LAG"
    STRATEGY_FAILURE = "STRATEGY_FAILURE"
    HISTORICAL_EVENT_REPLAY = "HISTORICAL_EVENT_REPLAY"


class BacktestRunSpec(DomainModel):
    """Content-addressed deterministic run declaration."""

    run_id: RunId
    engine_kind: EngineKind
    strategy_id: StrategyId
    strategy_version_id: StrategyVersionId
    dataset_sha256: str
    config_sha256: str
    code_sha256: str
    seed: NonNegativeInt
    reporting_asset_id: AssetId
    initial_cash: Money
    start_time: UtcDateTime
    end_time: UtcDateTime
    created_at: UtcDateTime
    accounting_policy_version: str
    cost_policy_version: str
    rule_policy_version: str
    reproduction_command: str
    live_trading_locked: Literal[True] = True
    metric_frequency_seconds: PositiveInt = 3600
    spot_borrow_policy: SpotBorrowPolicy | None = None

    @field_validator("dataset_sha256", "config_sha256", "code_sha256")
    @classmethod
    def validate_hash(cls, value: str, info: object) -> str:
        return ensure_sha256(value, field_name=str(getattr(info, "field_name", "hash")))

    @model_validator(mode="after")
    def validate_run(self) -> BacktestRunSpec:
        if self.start_time >= self.end_time:
            raise ValueError("backtest interval must have positive duration")
        if self.initial_cash.asset_id != self.reporting_asset_id or self.initial_cash.amount < 0:
            raise ValueError("initial cash must be non-negative and use the reporting asset")
        if not self.reproduction_command.strip():
            raise ValueError("reproduction command is required")
        return self


class MarketEventBase(DomainModel):
    event_id: BacktestEventId
    instrument_id: InstrumentId
    venue_id: VenueId
    base_asset_id: AssetId
    quote_asset_id: AssetId
    event_time: UtcDateTime
    available_time: UtcDateTime

    @model_validator(mode="after")
    def validate_time_and_assets(self) -> MarketEventBase:
        if self.event_time > self.available_time:
            raise ValueError("market event cannot be available before event time")
        if self.base_asset_id == self.quote_asset_id:
            raise ValueError("market event base and quote assets must differ")
        return self


class BarEvent(MarketEventBase):
    kind: Literal["BAR"] = "BAR"
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_ohlc(self) -> BarEvent:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("bar OHLC bounds are invalid")
        if self.low > self.high:
            raise ValueError("bar low exceeds high")
        return self


class TradeQuoteEvent(MarketEventBase):
    kind: Literal["TRADE_QUOTE"] = "TRADE_QUOTE"
    trade_price: PositiveDecimal
    trade_quantity: PositiveDecimal
    bid_price: PositiveDecimal
    bid_quantity: NonNegativeDecimal
    ask_price: PositiveDecimal
    ask_quantity: NonNegativeDecimal
    aggressor_side: OrderSide | None = None

    @model_validator(mode="after")
    def validate_quote(self) -> TradeQuoteEvent:
        if self.bid_price > self.ask_price:
            raise ValueError("trade quote is crossed")
        return self


class BookLevel(DomainModel):
    price: PositiveDecimal
    quantity: NonNegativeDecimal


class L2BookEvent(MarketEventBase):
    kind: Literal["L2"] = "L2"
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]

    @model_validator(mode="after")
    def validate_book(self) -> L2BookEvent:
        if not self.bids or not self.asks:
            raise ValueError("L2 event requires both sides")
        if any(a.price < b.price for a, b in zip(self.bids, self.bids[1:], strict=False)):
            raise ValueError("L2 bids must be descending")
        if any(a.price > b.price for a, b in zip(self.asks, self.asks[1:], strict=False)):
            raise ValueError("L2 asks must be ascending")
        if self.bids[0].price > self.asks[0].price:
            raise ValueError("L2 book is crossed")
        return self


MarketEvent = BarEvent | TradeQuoteEvent | L2BookEvent


class FundingEvent(MarketEventBase):
    kind: Literal["FUNDING"] = "FUNDING"
    funding_rate: FiniteDecimal
    mark_price: PositiveDecimal


class BacktestOrder(DomainModel):
    backtest_order_id: BacktestOrderId
    client_order_id: ClientOrderId
    order_intent_id: OrderIntentId
    instrument_id: InstrumentId
    venue_id: VenueId
    side: OrderSide
    order_type: OrderType
    quantity: Quantity
    limit_price: Price | None = None
    time_in_force: TimeInForce
    decision_time: UtcDateTime
    submitted_at: UtcDateTime
    reduce_only: bool = False
    multi_leg_plan_id: MultiLegPlanId | None = None
    leg_index: NonNegativeInt | None = None
    exit_trigger: ExitTrigger | None = None
    trigger_price: Price | None = None
    oco_group_id: str | None = None

    @model_validator(mode="after")
    def validate_order(self) -> BacktestOrder:
        if self.quantity.amount <= 0:
            raise ValueError("backtest order quantity must be positive")
        if self.decision_time > self.submitted_at:
            raise ValueError("order decision cannot follow submission")
        needs_limit = self.order_type is OrderType.LIMIT
        if needs_limit != (self.limit_price is not None):
            raise ValueError("limit price must appear exactly on limit orders")
        if (self.multi_leg_plan_id is None) != (self.leg_index is None):
            raise ValueError("multi-leg plan id and leg index must appear together")
        if (self.exit_trigger is None) != (self.trigger_price is None):
            raise ValueError("exit trigger and price must appear together")
        if self.exit_trigger is not None and (
            not self.reduce_only or self.order_type is not OrderType.MARKET
        ):
            raise ValueError("triggered exits must be reduce-only market orders")
        if self.oco_group_id is not None and (
            not self.oco_group_id.strip() or self.exit_trigger is None
        ):
            raise ValueError("OCO groups require a named triggered exit")
        return self


class CancelRequest(DomainModel):
    backtest_order_id: BacktestOrderId
    requested_at: UtcDateTime


class FaultWindow(DomainModel):
    fault_type: FaultType
    venue_id: VenueId
    starts_at: UtcDateTime
    ends_at: UtcDateTime
    evidence: str

    @model_validator(mode="after")
    def valid_window(self) -> FaultWindow:
        if self.starts_at >= self.ends_at:
            raise ValueError("fault window must have positive duration")
        if not self.evidence.strip():
            raise ValueError("fault window evidence is required")
        return self


class LatencyPolicy(DomainModel):
    version: str
    signal_ns: NonNegativeInt
    risk_ns: NonNegativeInt
    network_ns: NonNegativeInt
    acknowledgement_ns: NonNegativeInt
    cancel_ns: NonNegativeInt
    source: str

    @property
    def order_arrival_ns(self) -> int:
        return self.signal_ns + self.risk_ns + self.network_ns


class CostSchedule(DomainModel):
    cost_schedule_id: CostScheduleId
    version: str
    venue_id: VenueId
    instrument_id: InstrumentId
    effective_from: UtcDateTime
    effective_to: UtcDateTime | None = None
    maker_fee_bps: FiniteDecimal
    taker_fee_bps: FiniteDecimal
    half_spread_bps: NonNegativeDecimal
    slippage_bps: NonNegativeDecimal
    impact_coefficient_bps: NonNegativeDecimal
    maximum_impact_bps: NonNegativeDecimal
    funding_rate: FiniteDecimal
    borrow_rate_annual: NonNegativeDecimal
    settlement_fee_bps: NonNegativeDecimal
    participation_cap: UnitInterval
    source: str

    @model_validator(mode="after")
    def validate_schedule(self) -> CostSchedule:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("cost schedule interval is reversed")
        if min(self.maker_fee_bps, self.taker_fee_bps) < Decimal("-100"):
            raise ValueError("fee rebate exceeds supported bound")
        if self.maximum_impact_bps < self.impact_coefficient_bps:
            raise ValueError("maximum impact must cover the base coefficient")
        if not self.source.strip():
            raise ValueError("cost schedule source is required")
        return self


class CostBreakdown(DomainModel):
    asset_id: AssetId
    gross_notional: NonNegativeDecimal
    fee: FiniteDecimal
    spread: NonNegativeDecimal
    slippage: NonNegativeDecimal
    impact: NonNegativeDecimal
    funding: FiniteDecimal
    borrow_interest: NonNegativeDecimal
    settlement_fee: NonNegativeDecimal
    liquidation_penalty: NonNegativeDecimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return canonical_result(
            self.fee
            + self.spread
            + self.slippage
            + self.impact
            + self.funding
            + self.borrow_interest
            + self.settlement_fee
            + self.liquidation_penalty
        )


class FillSlice(DomainModel):
    quantity: PositiveDecimal
    reference_price: PositiveDecimal
    available_liquidity: NonNegativeDecimal
    precision: FillPrecision
    liquidity_role: LiquidityRole
    source_event_id: BacktestEventId
    event_time: UtcDateTime
    available_time: UtcDateTime


class BacktestFill(DomainModel):
    fill_id: FillId
    venue_order_id: VenueOrderId
    backtest_order_id: BacktestOrderId
    client_order_id: ClientOrderId
    order_intent_id: OrderIntentId
    instrument_id: InstrumentId
    side: OrderSide
    quantity: Quantity
    reference_price: Price
    execution_price: Price
    fee: Money
    cost_breakdown: CostBreakdown
    precision: FillPrecision
    liquidity_role: LiquidityRole
    source_event_id: BacktestEventId
    available_liquidity: NonNegativeDecimal
    event_time: UtcDateTime
    available_time: UtcDateTime
    ingest_time: UtcDateTime
    latency_ns: NonNegativeInt

    @model_validator(mode="after")
    def validate_fill(self) -> BacktestFill:
        if self.quantity.amount <= 0:
            raise ValueError("backtest fill quantity must be positive")
        if not self.event_time <= self.available_time <= self.ingest_time:
            raise ValueError("fill times must be monotonic")
        return self


class BacktestOrderResult(DomainModel):
    order: BacktestOrder
    status: VenueOrderStatus
    venue_order_id: VenueOrderId | None
    arrival_time: UtcDateTime
    cumulative_filled_quantity: NonNegativeDecimal
    average_fill_price: PositiveDecimal | None = None
    completed_at: UtcDateTime | None = None
    rejection_code: str | None = None
    unknown_reason: str | None = None
    recovery_evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> BacktestOrderResult:
        if self.cumulative_filled_quantity > self.order.quantity.amount:
            raise ValueError("order overfilled")
        if self.status is VenueOrderStatus.FILLED and (
            self.cumulative_filled_quantity != self.order.quantity.amount
        ):
            raise ValueError("filled status requires full quantity")
        if self.status is VenueOrderStatus.PARTIALLY_FILLED and not (
            Decimal("0") < self.cumulative_filled_quantity < self.order.quantity.amount
        ):
            raise ValueError("partial status requires a partial quantity")
        if self.status is VenueOrderStatus.REJECTED and self.rejection_code is None:
            raise ValueError("rejected order requires a code")
        if self.status is VenueOrderStatus.UNKNOWN and self.unknown_reason is None:
            raise ValueError("unknown order requires a reason")
        return self


class HistoricalInstrumentRule(DomainModel):
    instrument_rule_id: InstrumentRuleId
    version: str
    instrument_id: InstrumentId
    venue_id: VenueId
    effective_from: UtcDateTime
    effective_to: UtcDateTime | None = None
    tick_size: PositiveDecimal
    step_size: PositiveDecimal
    minimum_quantity: NonNegativeDecimal
    maximum_quantity: PositiveDecimal | None = None
    minimum_notional: NonNegativeDecimal
    trading_enabled: bool
    source: str
    approximation: str | None = None

    @model_validator(mode="after")
    def validate_rule(self) -> HistoricalInstrumentRule:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("instrument rule interval is reversed")
        if self.maximum_quantity is not None and self.maximum_quantity < self.minimum_quantity:
            raise ValueError("maximum quantity is below minimum")
        if not self.source.strip():
            raise ValueError("instrument rule source is required")
        return self


class MarginBracket(DomainModel):
    notional_floor: NonNegativeDecimal
    notional_cap: PositiveDecimal | None = None
    maximum_leverage: PositiveDecimal
    initial_margin_rate: UnitInterval
    maintenance_margin_rate: UnitInterval

    @model_validator(mode="after")
    def validate_bracket(self) -> MarginBracket:
        if self.notional_cap is not None and self.notional_cap <= self.notional_floor:
            raise ValueError("margin bracket cap must exceed floor")
        if self.maintenance_margin_rate > self.initial_margin_rate:
            raise ValueError("maintenance margin cannot exceed initial margin")
        return self


class MarginPolicy(DomainModel):
    margin_policy_id: MarginPolicyId
    version: str
    venue_id: VenueId
    instrument_id: InstrumentId
    mode: MarginMode
    effective_from: UtcDateTime
    effective_to: UtcDateTime | None = None
    brackets: tuple[MarginBracket, ...]
    liquidation_penalty_bps: NonNegativeDecimal
    conservative_buffer_rate: UnitInterval
    collateral_asset_id: AssetId
    source: str

    @model_validator(mode="after")
    def validate_policy(self) -> MarginPolicy:
        if not self.brackets:
            raise ValueError("margin policy requires brackets")
        ordered = sorted(self.brackets, key=lambda item: item.notional_floor)
        if tuple(ordered) != self.brackets or self.brackets[0].notional_floor != 0:
            raise ValueError("margin brackets must be ordered and start at zero")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("margin policy interval is reversed")
        return self


class MarginEvaluation(DomainModel):
    policy_version: str
    mode: MarginMode
    mark_price: PositiveDecimal
    position_quantity: FiniteDecimal
    notional: NonNegativeDecimal
    equity: FiniteDecimal
    initial_margin: NonNegativeDecimal
    maintenance_margin: NonNegativeDecimal
    buffered_maintenance_margin: NonNegativeDecimal
    margin_ratio: FiniteDecimal | None
    liquidation_required: bool
    precision: str


class MultiLegPlan(DomainModel):
    multi_leg_plan_id: MultiLegPlanId
    orders: tuple[BacktestOrder, ...]
    maximum_exposure_ns: NonNegativeInt

    @model_validator(mode="after")
    def validate_plan(self) -> MultiLegPlan:
        if len(self.orders) < 2:
            raise ValueError("multi-leg plan requires at least two orders")
        for index, order in enumerate(self.orders):
            if order.multi_leg_plan_id != self.multi_leg_plan_id or order.leg_index != index:
                raise ValueError("multi-leg order sequence is inconsistent")
        return self


class MultiLegExposure(DomainModel):
    multi_leg_plan_id: MultiLegPlanId
    filled_legs: NonNegativeInt
    failed_leg_index: NonNegativeInt | None
    exposed_notional: NonNegativeDecimal
    exposure_duration_ns: NonNegativeInt
    failure_reason: str | None


class PositionPoint(DomainModel):
    time: UtcDateTime
    instrument_id: InstrumentId
    quantity: FiniteDecimal
    average_entry_price: PositiveDecimal | None
    mark_price: PositiveDecimal
    unrealized_pnl: FiniteDecimal


class EquityPoint(DomainModel):
    time: UtcDateTime
    cash: FiniteDecimal
    position_value: FiniteDecimal
    realized_pnl: FiniteDecimal
    unrealized_pnl: FiniteDecimal
    equity: FiniteDecimal
    reporting_asset_id: AssetId

    @model_validator(mode="after")
    def equity_conserves(self) -> EquityPoint:
        if self.equity != canonical_result(self.cash + self.position_value):
            raise ValueError("backtest equity does not conserve cash plus position value")
        return self


class PnLAttributionPoint(DomainModel):
    time: UtcDateTime
    gross_trading_pnl: FiniteDecimal
    trading_fees: FiniteDecimal
    spread_cost: NonNegativeDecimal
    slippage_cost: NonNegativeDecimal
    impact_cost: NonNegativeDecimal
    funding: FiniteDecimal
    borrow_interest: NonNegativeDecimal
    settlement_fees: NonNegativeDecimal = Decimal("0")
    liquidation_penalties: NonNegativeDecimal = Decimal("0")
    net_pnl: FiniteDecimal

    @model_validator(mode="after")
    def attribution_conserves(self) -> PnLAttributionPoint:
        expected = canonical_result(
            self.gross_trading_pnl
            - self.trading_fees
            - self.spread_cost
            - self.slippage_cost
            - self.impact_cost
            - self.funding
            - self.borrow_interest
            - self.settlement_fees
            - self.liquidation_penalties
        )
        if expected != self.net_pnl:
            raise ValueError("backtest PnL attribution does not conserve")
        return self


class BacktestMetrics(DomainModel):
    total_return: FiniteDecimal
    annualized_return: FiniteDecimal | None
    annualized_volatility: NonNegativeDecimal
    sharpe: FiniteDecimal | None
    sortino: FiniteDecimal | None
    calmar: FiniteDecimal | None
    maximum_drawdown: UnitInterval
    expected_shortfall: FiniteDecimal
    skewness: FiniteDecimal | None
    excess_kurtosis: FiniteDecimal | None
    underwater_seconds: NonNegativeInt
    hit_rate: UnitInterval
    payoff_ratio: NonNegativeDecimal | None
    turnover: NonNegativeDecimal
    maker_ratio: UnitInterval
    fill_rate: UnitInterval
    average_slippage_bps: NonNegativeDecimal
    participation_rate: UnitInterval
    cancel_rate: UnitInterval
    average_latency_ns: NonNegativeDecimal
    maximum_multi_leg_exposure: NonNegativeDecimal


class BacktestResult(DomainModel):
    spec: BacktestRunSpec
    engine_kind: EngineKind
    orders: tuple[BacktestOrderResult, ...]
    fills: tuple[BacktestFill, ...]
    ledger_records: tuple[LedgerRecord, ...]
    positions: tuple[PositionPoint, ...]
    equity_curve: tuple[EquityPoint, ...]
    pnl_attribution: tuple[PnLAttributionPoint, ...]
    metrics: BacktestMetrics
    multi_leg_exposures: tuple[MultiLegExposure, ...] = ()
    events_processed: NonNegativeInt
    economic_event_hash: str
    precision_levels: tuple[FillPrecision, ...]
    warnings: tuple[str, ...] = ()
    mark_to_market_final_equity: FiniteDecimal | None = None
    forced_close_final_equity: FiniteDecimal | None = None
    forced_close_cost: CostBreakdown | None = None
    forced_close_mark_adjustment: FiniteDecimal = Decimal("0")
    forced_close_status: str = "LEGACY_NOT_EVALUATED"
    cost_identity_residual: FiniteDecimal = Decimal("0")

    @field_validator("economic_event_hash")
    @classmethod
    def validate_economic_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="economic_event_hash")

    @model_validator(mode="after")
    def validate_result(self) -> BacktestResult:
        if self.spec.engine_kind is not self.engine_kind:
            raise ValueError("result engine differs from run spec")
        if not self.equity_curve:
            raise ValueError("backtest result requires an equity curve")
        return self


class StressScenario(DomainModel):
    stress_scenario_id: StressScenarioId
    stress_type: StressType
    multiplier: PositiveDecimal
    starts_at: UtcDateTime
    ends_at: UtcDateTime
    source: str

    @model_validator(mode="after")
    def validate_scenario(self) -> StressScenario:
        if self.starts_at >= self.ends_at:
            raise ValueError("stress scenario interval is reversed")
        if not self.source.strip():
            raise ValueError("stress scenario source is required")
        return self


class StressOutcome(DomainModel):
    scenario: StressScenario
    baseline_equity: FiniteDecimal
    stressed_equity: FiniteDecimal
    equity_change: FiniteDecimal
    orders_rejected: NonNegativeInt
    events_dropped: NonNegativeInt
    ledger_balanced: bool
    economic_event_hash: str

    @field_validator("economic_event_hash")
    @classmethod
    def validate_stress_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="economic_event_hash")


def nanoseconds_after(value: datetime, nanoseconds: int) -> datetime:
    """Add deterministic latency at Python's microsecond resolution."""
    if nanoseconds < 0:
        raise ValueError("latency cannot be negative")
    if nanoseconds % 1_000:
        raise ValueError("latency must be representable in whole microseconds")
    from datetime import timedelta

    return value + timedelta(microseconds=nanoseconds // 1_000)
