"""CAT research adapters: completed bars, causal quantities, and the authoritative ledger."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from aegisquant.accounting.models import AccountingInstrument
from aegisquant.backtest.costs import HistoricalCostBook
from aegisquant.backtest.engine import EventBacktestEngine
from aegisquant.backtest.models import (
    BacktestDecisionContext,
    BacktestDecisionUpdate,
    BacktestOrder,
    BacktestResult,
    BacktestRunSpec,
    BarEvent,
    CostSchedule,
    HistoricalInstrumentRule,
    LatencyPolicy,
)
from aegisquant.backtest.rules import HistoricalRuleBook
from aegisquant.data.market import ContractForm, InstrumentType
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    AssetId,
    BacktestEventId,
    BacktestOrderId,
    ClientOrderId,
    CostScheduleId,
    InstrumentId,
    InstrumentRuleId,
    OrderIntentId,
    VenueId,
)
from aegisquant.domain.values import Quantity
from aegisquant.portfolio.economic_gate import (
    EconomicAction,
    EconomicGatePolicy,
    decide_economic_transition,
)
from aegisquant.portfolio.optimizer import target_quantity_adjustment
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.models.economic_gate import EconomicForecast
from aegisquant.research.strategies.cost_aware_trend import TrendFeatures

BTC, USDT = AssetId("BTC"), AssetId("USDT")
VENUE = VenueId("SIM")
INSTRUMENT = InstrumentId("SIM:SPOT:BTCUSDT")
DEFAULT_GATE_POLICY = EconomicGatePolicy()


@dataclass(frozen=True, slots=True)
class CatMarket:
    """Explicit spot asset units and declared research execution precision."""

    base_asset: AssetId = BTC
    tick_size: Decimal = Decimal("0.01")
    quantity_step: Decimal = Decimal("0.000001")

    def __post_init__(self) -> None:
        if self.base_asset == USDT or not str(self.base_asset).isalnum():
            raise ValueError("CAT market requires an explicit non-USDT base asset")
        if any(
            not value.is_finite() or value <= 0 for value in (self.tick_size, self.quantity_step)
        ):
            raise ValueError("market precision must be finite and positive")

    @property
    def instrument_id(self) -> InstrumentId:
        return InstrumentId(f"SIM:SPOT:{self.base_asset}USDT")


DEFAULT_MARKET = CatMarket()


def decimal(value: float) -> Decimal:
    return Decimal(format(value, ".15g"))


def cat_instrument(market_spec: CatMarket = DEFAULT_MARKET) -> AccountingInstrument:
    return AccountingInstrument(
        instrument_id=market_spec.instrument_id,
        venue="SIM",
        base_asset_id=market_spec.base_asset,
        quote_asset_id=USDT,
        settlement_asset_id=USDT,
        quantity_asset_id=market_spec.base_asset,
        instrument_type=InstrumentType.SPOT,
        contract_form=ContractForm.SPOT,
        contract_multiplier=Decimal("1"),
    )


def load_completed_bars(
    path: Path, *, hours: int = 4, market_spec: CatMarket = DEFAULT_MARKET
) -> tuple[BarEvent, ...]:
    """Discard incomplete buckets; never invent a missing market observation."""
    if hours not in (1, 4):
        raise ValueError("CAT supports only original hourly and declared four-hour bars")
    width = hours * 3_600_000
    buckets: dict[int, list[dict[str, str]]] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            millis = int(row["open_time_ms"])
            buckets.setdefault(millis // width * width, []).append(row)
    bars: list[BarEvent] = []
    for start, values in sorted(buckets.items()):
        values.sort(key=lambda row: int(row["open_time_ms"]))
        if [int(row["open_time_ms"]) for row in values] != [
            start + i * 3_600_000 for i in range(hours)
        ]:
            continue
        if any(int(row["close_time_ms"]) != int(row["open_time_ms"]) + 3_599_999 for row in values):
            # A prematurely closed source candle cannot certify a complete hour.
            # Keep the gap explicit so feature warmup and risk veto can see it.
            continue
        bars.append(
            BarEvent(
                event_id=BacktestEventId(f"{str(market_spec.base_asset).lower()}{hours}h-{start}"),
                instrument_id=market_spec.instrument_id,
                venue_id=VENUE,
                base_asset_id=market_spec.base_asset,
                quote_asset_id=USDT,
                event_time=datetime.fromtimestamp(start / 1000, UTC),
                available_time=datetime.fromtimestamp((start + width - 1) / 1000, UTC),
                open=Decimal(values[0]["open"]),
                high=max(Decimal(row["high"]) for row in values),
                low=min(Decimal(row["low"]) for row in values),
                close=Decimal(values[-1]["close"]),
                volume=sum((Decimal(row["base_volume"]) for row in values), Decimal("0")),
            )
        )
    return tuple(bars)


def executable_labels(
    bars: tuple[BarEvent, ...],
    horizon: int = 6,
) -> tuple[tuple[float, ...], tuple[datetime | None, ...]]:
    """Decision t -> entry open t+1 -> exit open t+h, with gap-free horizons."""
    values: list[float] = [float("nan")] * len(bars)
    ends: list[datetime | None] = [None] * len(bars)
    for i in range(len(bars) - horizon):
        if bars[i + horizon].event_time - bars[i].event_time != timedelta(hours=4 * horizon):
            continue
        values[i] = float(bars[i + horizon].open / bars[i + 1].open - 1)
        ends[i] = bars[i + horizon].event_time
    return tuple(values), tuple(ends)


def replay_cat(
    *,
    root: Path,
    spec: BacktestRunSpec,
    bars: tuple[BarEvent, ...],
    features: TrendFeatures,
    feature_indices: Mapping[datetime, int],
    trend_by_time: Mapping[datetime, bool],
    forecasts: Mapping[datetime, EconomicForecast],
    level: str,
    old_targets: Mapping[datetime, bool] | None = None,
    gate_policy: EconomicGatePolicy = DEFAULT_GATE_POLICY,
    cost_multiplier: Decimal = Decimal("1"),
    spread_multiplier: Decimal = Decimal("1"),
    slippage_multiplier: Decimal = Decimal("1"),
    volume_multiplier: Decimal = Decimal("1"),
    latency_multiplier: int = 1,
    omit_cost: str | None = None,
    fixed_orders: tuple[BacktestOrder, ...] | None = None,
    market_spec: CatMarket = DEFAULT_MARKET,
) -> tuple[BacktestResult, list[dict[str, Any]]]:
    if len(bars) < 3 or min(cost_multiplier, spread_multiplier, slippage_multiplier) < 0:
        raise ValueError("CAT replay requires at least three bars and nonnegative costs")
    if not 0 < volume_multiplier <= 1 or latency_multiplier < 1:
        raise ValueError("invalid CAT stress assumptions")
    if any(
        bar.instrument_id != market_spec.instrument_id
        or bar.base_asset_id != market_spec.base_asset
        or bar.quote_asset_id != USDT
        for bar in bars
    ):
        raise ValueError("CAT market bars and execution asset units differ")
    schedules: list[CostSchedule] = []
    for n, bar in enumerate(bars):
        i = feature_indices[bar.available_time]
        prior_natr = float(features.values[max(0, i - 1), 9])
        known_natr = decimal(prior_natr) if np.isfinite(prior_natr) else Decimal("0")
        fee = Decimal("0") if omit_cost == "fee" else Decimal("10")
        spread = Decimal("0") if omit_cost == "spread" else spread_multiplier
        slip = (
            Decimal("0")
            if omit_cost == "slippage"
            else (Decimal("2") + Decimal("100") * known_natr) * slippage_multiplier
        )
        latency_adverse = Decimal("0") if omit_cost == "latency" else Decimal(latency_multiplier)
        impact = Decimal("0") if omit_cost == "impact" else Decimal("25")
        schedules.append(
            CostSchedule(
                cost_schedule_id=CostScheduleId(f"cat-cost-{n}"),
                version="cat-proxy-v1",
                venue_id=VENUE,
                instrument_id=market_spec.instrument_id,
                effective_from=bar.event_time,
                effective_to=bars[n + 1].event_time if n + 1 < len(bars) else None,
                maker_fee_bps=fee * cost_multiplier,
                taker_fee_bps=fee * cost_multiplier,
                half_spread_bps=spread * cost_multiplier,
                slippage_bps=(slip + latency_adverse) * cost_multiplier,
                impact_coefficient_bps=impact * cost_multiplier,
                maximum_impact_bps=impact * cost_multiplier,
                funding_rate=Decimal("0"),
                borrow_rate_annual=Decimal("0"),
                settlement_fee_bps=Decimal("0"),
                participation_cap=Decimal("0.01"),
                source="PREREGISTERED_PROXY: previous completed bar NATR; no historical orderbook",
            )
        )
    rule = HistoricalInstrumentRule(
        instrument_rule_id=InstrumentRuleId("cat-rule-proxy-v1"),
        version="cat-rule-proxy-v1",
        instrument_id=market_spec.instrument_id,
        venue_id=VENUE,
        effective_from=bars[0].event_time,
        tick_size=market_spec.tick_size,
        step_size=market_spec.quantity_step,
        minimum_quantity=market_spec.quantity_step,
        minimum_notional=Decimal("10"),
        trading_enabled=True,
        source="PREREGISTERED_PROXY_NOT_HISTORICAL_EXCHANGE_RULE_PROOF",
        approximation=f"{market_spec.base_asset} step and notional assumptions; venue history unverified",
    )
    engine = EventBacktestEngine(
        project_root=root,
        cost_book=HistoricalCostBook(schedules),
        rule_book=HistoricalRuleBook((rule,)),
        latency_policy=LatencyPolicy(
            version="cat-latency-v1",
            signal_ns=0,
            risk_ns=0,
            network_ns=100_000 * latency_multiplier,
            acknowledgement_ns=0,
            cancel_ns=100_000,
            source="preregistered proxy; bar execution cannot resolve intrabar latency",
        ),
    )
    decisions: list[dict[str, Any]] = []
    last_resize_day: object = None
    exit_decision_time = bars[-2].available_time

    def callback(context: BacktestDecisionContext) -> BacktestDecisionUpdate:
        nonlocal last_resize_day
        if not isinstance(context.event, BarEvent):
            raise TypeError("CAT expects completed bars")
        event = context.event
        time = event.available_time
        i = feature_indices[time]
        price = event.close
        held = context.position_quantity
        if context.equity <= 0 or held < 0 or context.cash < 0:
            raise ValueError("CAT long/flat cash conservation violated")
        trend = trend_by_time.get(time, False)
        target = held
        reason = "HOLD_CURRENT"
        q_long = hurdle = None
        if time >= exit_decision_time:
            target, reason = Decimal("0"), "PREREGISTERED_FOLD_END_NEXT_OPEN_EXIT"
        elif level == "B0":
            target, reason = Decimal("0"), "CASH"
        elif level in {"B1", "B2", "B3"}:
            long = (
                (old_targets or {}).get(time, False) if level == "B2" else (level == "B1" or trend)
            )
            if not long:
                target, reason = Decimal("0"), "PRIMARY_SIGNAL_FLAT"
            elif held == 0:
                target, reason = context.equity * Decimal("0.99") / price, "PRIMARY_SIGNAL_LONG"
        else:
            forecast = forecasts.get(time)
            if forecast is None or not features.valid[i]:
                target, reason = Decimal("0"), "MISSING_CAUSAL_FORECAST_OR_DATA"
            else:
                costs = estimate_spot_transition_costs(
                    available_time=time,
                    natr=decimal(float(features.values[i, 9])),
                    quote_volume=event.volume * price,
                    order_notional=min(context.equity, context.cash),
                )
                day = time.date()
                decision = decide_economic_transition(
                    policy=gate_policy,
                    forecast=forecast,
                    costs=costs,
                    decision_time=time,
                    current_weight=min(Decimal("1"), held * price / context.equity),
                    trend_candidate=trend,
                    trend_exit_confirmed=not trend,
                    data_quality_passed=bool(features.valid[i]),
                    risk_allows_entry=True,
                    annualized_volatility=max(
                        Decimal("0.000001"), decimal(float(features.annualized_volatility[i]))
                    ),
                    probability_filter=level not in {"B4", "B5", "LIGHTGBM", "ELASTIC_NET"},
                    uncertainty_filter=level not in {"B4", "B5", "LIGHTGBM", "ELASTIC_NET"},
                    volatility_sizing=level == "B7",
                    resize_permitted=day != last_resize_day,
                )
                last_resize_day = day
                reason, q_long, hurdle = decision.reason, decision.q_long, decision.entry_hurdle
                if decision.action is not EconomicAction.HOLD_CURRENT:
                    target = context.equity * decision.target_weight * Decimal("0.99") / price
        adjustment = target_quantity_adjustment(
            target_quantity=target,
            current_quantity=held,
            signed_pending_quantity=context.signed_pending_quantity,
            price=price,
            quantity_step=rule.step_size,
            minimum_notional=rule.minimum_notional,
            minimum_economic_notional=Decimal("10"),
        )
        decisions.append(
            {
                "time": time,
                "known_close": str(price),
                "cash": str(context.cash),
                "current_quantity": str(held),
                "target_quantity": str(target),
                "pending_quantity": str(context.signed_pending_quantity),
                "reason": reason,
                "q_long": str(q_long) if q_long is not None else None,
                "entry_hurdle": str(hurdle) if hurdle is not None else None,
            }
        )
        if adjustment.cancel_pending_first:
            return BacktestDecisionUpdate(
                cancel_order_ids=tuple(p.backtest_order_id for p in context.pending_orders)
            )
        delta = adjustment.signed_order_quantity
        if delta == 0 or time == bars[-1].available_time:
            return BacktestDecisionUpdate()
        key = f"{spec.run_id}-{len(decisions)}"
        return BacktestDecisionUpdate(
            orders=(
                BacktestOrder(
                    backtest_order_id=BacktestOrderId(key),
                    client_order_id=ClientOrderId(key),
                    order_intent_id=OrderIntentId(key),
                    instrument_id=market_spec.instrument_id,
                    venue_id=VENUE,
                    side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=Quantity(amount=abs(delta), asset_id=market_spec.base_asset),
                    time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
                    reduce_only=delta < 0,
                    decision_time=time,
                    submitted_at=time,
                ),
            )
        )

    market = tuple(b.model_copy(update={"volume": b.volume * volume_multiplier}) for b in bars)
    result = engine.run(
        spec=spec,
        instrument=cat_instrument(market_spec),
        market_events=market,
        orders=fixed_orders or (),
        decision_callback=callback if fixed_orders is None else None,
    )
    if abs(result.cost_identity_residual) >= Decimal("0.00000001"):
        raise ValueError("CAT cost identity did not close")
    return result, decisions
