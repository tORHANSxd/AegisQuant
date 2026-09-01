"""Deterministic builders shared by P06 tests and evidence generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aegisquant.accounting.models import AccountingInstrument
from aegisquant.backtest.costs import HistoricalCostBook
from aegisquant.backtest.engine import EventBacktestEngine
from aegisquant.backtest.models import (
    BacktestOrder,
    BacktestRunSpec,
    BarEvent,
    BookLevel,
    EngineKind,
    L2BookEvent,
    LatencyPolicy,
    TradeQuoteEvent,
)
from aegisquant.backtest.policy import BacktestPolicy, load_backtest_policy
from aegisquant.backtest.rules import HistoricalRuleBook
from aegisquant.data.market import ContractForm, InstrumentType
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    AssetId,
    BacktestEventId,
    BacktestOrderId,
    ClientOrderId,
    InstrumentId,
    OrderIntentId,
    RunId,
    StrategyId,
    StrategyVersionId,
    VenueId,
)
from aegisquant.domain.values import Money, Quantity

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)
BTC = AssetId("BTC")
USDT = AssetId("USDT")
VENUE = VenueId("SIM")
SPOT_ID = InstrumentId("SIM:SPOT:BTCUSDT")
PERP_ID = InstrumentId("SIM:PERP:BTCUSDT")


def policy() -> BacktestPolicy:
    return load_backtest_policy(ROOT / "configs/backtest/backtest_policy_v1.yaml")


def zero_cost_policy() -> BacktestPolicy:
    value = policy()
    schedules = tuple(
        schedule.model_copy(
            update={
                "maker_fee_bps": Decimal("0"),
                "taker_fee_bps": Decimal("0"),
                "half_spread_bps": Decimal("0"),
                "slippage_bps": Decimal("0"),
                "impact_coefficient_bps": Decimal("0"),
                "maximum_impact_bps": Decimal("0"),
                "funding_rate": Decimal("0"),
                "borrow_rate_annual": Decimal("0"),
                "settlement_fee_bps": Decimal("0"),
                "participation_cap": Decimal("1"),
            }
        )
        for schedule in value.cost_schedules
    )
    return value.model_copy(
        update={
            "cost_schedules": schedules,
            "latency_policy": LatencyPolicy(
                version="latency-zero-v1",
                signal_ns=0,
                risk_ns=0,
                network_ns=0,
                acknowledgement_ns=0,
                cancel_ns=0,
                source="P06 zero-cost consistency fixture",
            ),
        }
    )


def spot_instrument() -> AccountingInstrument:
    return AccountingInstrument(
        instrument_id=SPOT_ID,
        venue="SIM",
        base_asset_id=BTC,
        quote_asset_id=USDT,
        settlement_asset_id=USDT,
        quantity_asset_id=BTC,
        instrument_type=InstrumentType.SPOT,
        contract_form=ContractForm.SPOT,
        contract_multiplier=Decimal("1"),
    )


def perp_instrument() -> AccountingInstrument:
    return AccountingInstrument(
        instrument_id=PERP_ID,
        venue="SIM",
        base_asset_id=BTC,
        quote_asset_id=USDT,
        settlement_asset_id=USDT,
        quantity_asset_id=AssetId("CONTRACT:SIM:PERP:BTCUSDT"),
        instrument_type=InstrumentType.PERPETUAL,
        contract_form=ContractForm.LINEAR,
        contract_multiplier=Decimal("1"),
    )


def engine(value: BacktestPolicy | None = None) -> EventBacktestEngine:
    selected = value or policy()
    return EventBacktestEngine(
        project_root=ROOT,
        cost_book=HistoricalCostBook(selected.cost_schedules),
        rule_book=HistoricalRuleBook(selected.instrument_rules),
        latency_policy=selected.latency_policy,
    )


def run_spec(
    engine_kind: EngineKind = EngineKind.EVENT,
    *,
    run_id: str | None = None,
    initial_cash: str = "10000",
    end_time: datetime | None = None,
) -> BacktestRunSpec:
    return BacktestRunSpec(
        run_id=RunId(run_id or f"p06-{engine_kind.value.lower()}-golden"),
        engine_kind=engine_kind,
        strategy_id=StrategyId("p06-buy-hold"),
        strategy_version_id=StrategyVersionId("p06-buy-hold-v1"),
        dataset_sha256="1" * 64,
        config_sha256="2" * 64,
        code_sha256="3" * 64,
        seed=20260901,
        reporting_asset_id=USDT,
        initial_cash=Money(amount=Decimal(initial_cash), asset_id=USDT),
        start_time=NOW,
        end_time=end_time or NOW + timedelta(seconds=5),
        created_at=NOW,
        accounting_policy_version="accounting-v1",
        cost_policy_version="cost-v1",
        rule_policy_version="rule-v1",
        reproduction_command=(
            ".venv\\Scripts\\python.exe -m scripts.generate_p06_evidence --run-id "
            + (run_id or f"p06-{engine_kind.value.lower()}-golden")
        ),
    )


def bars(count: int = 4, *, volume: str = "10") -> tuple[BarEvent, ...]:
    output: list[BarEvent] = []
    for sequence in range(count):
        price = Decimal("100") + Decimal(sequence)
        event_time = NOW + timedelta(seconds=sequence)
        output.append(
            BarEvent(
                event_id=BacktestEventId(f"bar-{sequence}"),
                instrument_id=SPOT_ID,
                venue_id=VENUE,
                base_asset_id=BTC,
                quote_asset_id=USDT,
                event_time=event_time,
                available_time=event_time,
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal(volume),
            )
        )
    return tuple(output)


def trade_quote(*, sequence: int = 1, quantity: str = "2") -> TradeQuoteEvent:
    event_time = NOW + timedelta(seconds=sequence)
    return TradeQuoteEvent(
        event_id=BacktestEventId(f"trade-quote-{sequence}"),
        instrument_id=SPOT_ID,
        venue_id=VENUE,
        base_asset_id=BTC,
        quote_asset_id=USDT,
        event_time=event_time,
        available_time=event_time,
        trade_price=Decimal("100"),
        trade_quantity=Decimal(quantity),
        bid_price=Decimal("99.99"),
        bid_quantity=Decimal(quantity),
        ask_price=Decimal("100.01"),
        ask_quantity=Decimal(quantity),
        aggressor_side=OrderSide.BUY,
    )


def l2_book(*, sequence: int = 1) -> L2BookEvent:
    event_time = NOW + timedelta(seconds=sequence)
    return L2BookEvent(
        event_id=BacktestEventId(f"l2-{sequence}"),
        instrument_id=SPOT_ID,
        venue_id=VENUE,
        base_asset_id=BTC,
        quote_asset_id=USDT,
        event_time=event_time,
        available_time=event_time,
        bids=(
            BookLevel(price=Decimal("99.99"), quantity=Decimal("1")),
            BookLevel(price=Decimal("99.98"), quantity=Decimal("2")),
        ),
        asks=(
            BookLevel(price=Decimal("100.01"), quantity=Decimal("1")),
            BookLevel(price=Decimal("100.02"), quantity=Decimal("2")),
        ),
    )


def perp_bars() -> tuple[BarEvent, ...]:
    output: list[BarEvent] = []
    for sequence, price_text in enumerate(("100", "100", "80", "80")):
        price = Decimal(price_text)
        event_time = NOW + timedelta(seconds=sequence)
        output.append(
            BarEvent(
                event_id=BacktestEventId(f"perp-bar-{sequence}"),
                instrument_id=PERP_ID,
                venue_id=VENUE,
                base_asset_id=BTC,
                quote_asset_id=USDT,
                event_time=event_time,
                available_time=event_time,
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("100"),
            )
        )
    return tuple(output)


def perp_order(
    *, sequence: int, side: OrderSide, quantity: str, submitted_at: datetime
) -> BacktestOrder:
    instrument = perp_instrument()
    return BacktestOrder(
        backtest_order_id=BacktestOrderId(f"p06-perp-order-{sequence}"),
        client_order_id=ClientOrderId(f"p06-perp-client-{sequence}"),
        order_intent_id=OrderIntentId(f"p06-perp-intent-{sequence}"),
        instrument_id=instrument.instrument_id,
        venue_id=VENUE,
        side=side,
        order_type=OrderType.MARKET,
        quantity=Quantity(
            amount=Decimal(quantity),
            asset_id=instrument.quantity_asset_id,
        ),
        time_in_force=TimeInForce.GOOD_TIL_CANCELED,
        decision_time=submitted_at,
        submitted_at=submitted_at,
    )


def order(
    *,
    sequence: int,
    side: OrderSide,
    quantity: str = "1",
    submitted_at: datetime | None = None,
    order_type: OrderType = OrderType.MARKET,
    time_in_force: TimeInForce = TimeInForce.GOOD_TIL_CANCELED,
) -> BacktestOrder:
    submitted = submitted_at or NOW + timedelta(microseconds=1)
    return BacktestOrder(
        backtest_order_id=BacktestOrderId(f"p06-order-{sequence}"),
        client_order_id=ClientOrderId(f"p06-client-{sequence}"),
        order_intent_id=OrderIntentId(f"p06-intent-{sequence}"),
        instrument_id=SPOT_ID,
        venue_id=VENUE,
        side=side,
        order_type=order_type,
        quantity=Quantity(amount=Decimal(quantity), asset_id=BTC),
        limit_price=None,
        time_in_force=time_in_force,
        decision_time=submitted,
        submitted_at=submitted,
    )
