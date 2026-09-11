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
from aegisquant.research.strategies.buffered_target import (
    BufferPolicy,
    RiskResizePolicy,
    Snapshot,
    TargetSmoother,
    decide_buffered_target,
    rebalance_risk_benefit,
)
from aegisquant.research.strategies.cost_aware_trend import TrendFeatures
from aegisquant.research.validation.cat_contract import CatAuditPolicy

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
    path: Path,
    *,
    hours: int = 4,
    market_spec: CatMarket = DEFAULT_MARKET,
    strict_source: bool = False,
) -> tuple[BarEvent, ...]:
    """Discard incomplete buckets; never invent a missing market observation."""
    if hours not in (1, 4):
        raise ValueError("CAT supports only original hourly and declared four-hour bars")
    width = hours * 3_600_000
    buckets: dict[int, list[dict[str, str]]] = {}
    previous_millis: int | None = None
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            millis = int(row["open_time_ms"])
            if strict_source:
                prices = [Decimal(row[key]) for key in ("open", "high", "low", "close")]
                volume = Decimal(row["base_volume"])
                if (
                    any(not p.is_finite() or p <= 0 for p in prices)
                    or not volume.is_finite()
                    or volume < 0
                    or prices[1] < max(prices[0], prices[3])
                    or prices[2] > min(prices[0], prices[3])
                    or (previous_millis is not None and millis <= previous_millis)
                ):
                    raise ValueError("invalid, duplicate or unordered source OHLCV")
                previous_millis = millis
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
    *,
    holding_intervals: int | None = None,
) -> tuple[tuple[float, ...], tuple[datetime | None, ...]]:
    """v1: exit at t+h. v2: hold explicit intervals after entry at t+1.

    Both use arithmetic executable open-to-open returns. Existing frozen
    h=6 predictions remain five intervals (20h), never relabelled as 24h.
    """
    if horizon < 2 or (holding_intervals is not None and holding_intervals < 1):
        raise ValueError("label horizon/holding intervals must be positive executable spans")
    if holding_intervals is not None:
        horizon = 1 + holding_intervals
    values: list[float] = [float("nan")] * len(bars)
    ends: list[datetime | None] = [None] * len(bars)
    for i in range(len(bars) - horizon):
        if any(
            bars[j + 1].event_time - bars[j].event_time != timedelta(hours=4)
            for j in range(i, i + horizon)
        ):
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
    audit_policy: CatAuditPolicy | None = None,
    risk_weight_caps: Mapping[datetime, Decimal] | None = None,
    buffer_policy: BufferPolicy | None = None,
    resize_policy: RiskResizePolicy | None = None,
    signal_fractions: Mapping[datetime, Decimal] | None = None,
    terminal_exit: bool = True,
    terminal_exit_reason: str = "PREREGISTERED_FOLD_END_NEXT_OPEN_EXIT",
) -> tuple[BacktestResult, list[dict[str, Any]]]:
    if len(bars) < 3 or min(cost_multiplier, spread_multiplier, slippage_multiplier) < 0:
        raise ValueError("CAT replay requires at least three bars and nonnegative costs")
    if not 0 < volume_multiplier <= 1 or latency_multiplier < 1:
        raise ValueError("invalid CAT stress assumptions")
    if (
        buffer_policy is not None or signal_fractions is not None or resize_policy is not None
    ) and (
        audit_policy is None
        or any(
            (
                audit_policy.switches.use_model_entry_filter,
                audit_policy.switches.use_cost_entry_gate,
                audit_policy.switches.use_probability_entry_gate,
                audit_policy.switches.use_uncertainty_entry_gate,
                audit_policy.switches.use_confidence_sizing,
                audit_policy.switches.use_model_economic_exit,
            )
        )
    ):
        raise ValueError("R4 extensions require the independent no-ML risk policy")
    if any(
        bar.instrument_id != market_spec.instrument_id
        or bar.base_asset_id != market_spec.base_asset
        or bar.quote_asset_id != USDT
        for bar in bars
    ):
        raise ValueError("CAT market bars and execution asset units differ")
    schedules: list[CostSchedule] = []
    execution = audit_policy.execution if audit_policy else None
    for n, bar in enumerate(bars):
        i = feature_indices[bar.available_time]
        prior_natr = float(features.values[max(0, i - 1), 9])
        known_natr = decimal(prior_natr) if np.isfinite(prior_natr) else Decimal("0")
        fee = (
            Decimal("0")
            if omit_cost == "fee"
            else execution.fee_bps
            if execution
            else Decimal("10")
        )
        spread = (
            Decimal("0")
            if omit_cost == "spread"
            else spread_multiplier * (execution.half_spread_bps if execution else 1)
        )
        slip = (
            Decimal("0")
            if omit_cost == "slippage"
            else (
                (execution.slippage_floor_bps if execution else Decimal("2"))
                + (execution.natr_slippage_coefficient * 10000 if execution else Decimal("100"))
                * known_natr
            )
            * slippage_multiplier
        )
        latency_adverse = (
            Decimal("0")
            if omit_cost == "latency"
            else Decimal(latency_multiplier) * (execution.latency_adverse_bps if execution else 1)
        )
        impact = (
            Decimal("0")
            if omit_cost == "impact"
            else execution.impact_coefficient_bps
            if execution
            else Decimal("25")
        )
        schedules.append(
            CostSchedule(
                cost_schedule_id=CostScheduleId(f"cat-cost-{n}"),
                version="cat-proxy-v2" if execution else "cat-proxy-v1",
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
                participation_cap=execution.participation_cap if execution else Decimal("0.01"),
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
        minimum_notional=execution.minimum_notional if execution else Decimal("10"),
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
            network_ns=(execution.latency_ns if execution else 100_000) * latency_multiplier,
            acknowledgement_ns=0,
            cancel_ns=100_000,
            source="preregistered proxy; bar execution cannot resolve intrabar latency",
        ),
    )
    decisions: list[dict[str, Any]] = []
    last_resize_day: object = None
    last_resize_time: datetime | None = None
    last_regular_review: datetime | None = None
    smoother = TargetSmoother()
    exit_decision_time = bars[-2].available_time

    def callback(context: BacktestDecisionContext) -> BacktestDecisionUpdate:
        nonlocal last_resize_day, last_resize_time, last_regular_review
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
        details: dict[str, Any] = {}
        if terminal_exit and time >= exit_decision_time:
            target, reason = Decimal("0"), terminal_exit_reason
        elif level == "B0":
            target, reason = Decimal("0"), "CASH"
        elif audit_policy is not None:
            execution = audit_policy.execution
            forecast = forecasts.get(time)
            if forecast is not None and not features.valid[i]:
                # Full ML validity controls model use, not independent trend risk inputs.
                forecast = None
            natr_float = float(features.values[i, 9])
            vol_float = float(features.annualized_volatility[i])
            good = np.isfinite(natr_float) and np.isfinite(vol_float) and event.volume > 0
            natr = decimal(natr_float) if good else Decimal("0")
            vol = max(Decimal("0.000001"), decimal(vol_float)) if good else Decimal("1")
            active_gate = gate_policy
            if risk_weight_caps is not None:
                cap = risk_weight_caps.get(time, Decimal("0"))
                active_gate = gate_policy.model_copy(
                    update={"maximum_weight": min(gate_policy.maximum_weight, cap)}
                )
            risk_weight = (
                min(active_gate.maximum_weight, active_gate.target_volatility / vol)
                if audit_policy.switches.use_risk_sizing
                else active_gate.maximum_weight
            )
            raw_risk_weight = risk_weight
            if resize_policy is not None:
                good = good and vol_float > 0
                if (
                    not good
                    or not trend
                    or (smoother.time is not None and time - smoother.time != timedelta(hours=4))
                ):
                    smoother.time, smoother.weight = None, None
                if good and trend:
                    risk_weight = min(
                        active_gate.maximum_weight,
                        smoother.update(time, risk_weight, resize_policy.smoothing_half_life),
                    )
                    smoother.weight = risk_weight
            signal_fraction = (
                signal_fractions.get(time, Decimal("0"))
                if signal_fractions is not None
                else Decimal("1")
            )
            if not signal_fraction.is_finite() or not 0 <= signal_fraction <= 1:
                raise ValueError("R4 signal fractions must be within the existing risk budget")
            confidence = Decimal("1")
            if audit_policy.switches.use_confidence_sizing and forecast is not None:
                confidence = min(
                    Decimal("1"),
                    max(
                        Decimal("0"),
                        (forecast.p_net_positive - active_gate.p_enter)
                        / (active_gate.p_full_size - active_gate.p_enter),
                    ),
                )

            def estimated(buy: Decimal, sell: Decimal):
                return estimate_spot_transition_costs(
                    available_time=time,
                    natr=natr,
                    quote_volume=max(Decimal("0.000001"), event.volume * price),
                    order_notional=buy,
                    exit_order_notional=sell,
                    fee_bps=execution.fee_bps * cost_multiplier,
                    half_spread_bps=execution.half_spread_bps * spread_multiplier * cost_multiplier,
                    slippage_floor_bps=execution.slippage_floor_bps
                    * slippage_multiplier
                    * cost_multiplier,
                    natr_slippage_coefficient=execution.natr_slippage_coefficient
                    * slippage_multiplier
                    * cost_multiplier,
                    impact_coefficient_bps=execution.impact_coefficient_bps * cost_multiplier,
                    latency_adverse_bps=execution.latency_adverse_bps
                    * latency_multiplier
                    * cost_multiplier,
                    exit_latency_adverse_bps=execution.latency_adverse_bps
                    * latency_multiplier
                    * cost_multiplier,
                )

            held_value = held * price
            candidate = max(
                Decimal("0"),
                context.equity * risk_weight * signal_fraction * confidence - held_value,
            )
            costs = estimated(
                min(candidate, context.cash), held_value or min(candidate, context.cash)
            )
            # Reserve costs plus a declared fraction of observed NATR, never the next open.
            buy_factor = (
                1
                + costs.entry.total
                - costs.entry.fee
                + natr * execution.price_reserve_natr_fraction
            ) * (1 + costs.entry.fee)
            pending_buy = sum(
                (p.remaining_quantity for p in context.pending_orders if p.side is OrderSide.BUY),
                Decimal("0"),
            )
            reserved_cash = pending_buy * price * buy_factor
            affordable = max(Decimal("0"), context.cash - reserved_cash) / buy_factor
            entry_notional = min(candidate, affordable)
            costs = estimated(entry_notional, held_value or entry_notional)
            rebalance_cost = None
            if audit_policy.version == "cat-audit-r2":
                component_good = (
                    forecast is not None
                    and forecast.component_failure(
                        probability_required=audit_policy.switches.use_probability_entry_gate
                        or audit_policy.switches.use_confidence_sizing,
                        decision_time=time,
                        maximum_age_days=audit_policy.maximum_calibration_age_days,
                    )
                    is None
                )
                needs_model = any(
                    (
                        audit_policy.switches.use_model_entry_filter,
                        audit_policy.switches.use_cost_entry_gate,
                        audit_policy.switches.use_probability_entry_gate,
                        audit_policy.switches.use_uncertainty_entry_gate,
                        audit_policy.switches.use_confidence_sizing,
                        audit_policy.switches.use_model_economic_exit,
                    )
                )
                resize_target = (
                    context.equity * risk_weight * signal_fraction * confidence
                    if component_good or not needs_model
                    else min(held_value, context.equity * risk_weight)
                )
                resize_delta = resize_target - held_value
                incremental = estimated(abs(resize_delta), abs(resize_delta))
                rebalance_cost = incremental.entry if resize_delta >= 0 else incremental.exit
            permitted = (
                last_resize_time is None
                or (time - last_resize_time).total_seconds()
                >= audit_policy.rebalance_cooldown_seconds
            )
            if resize_policy is not None:
                permitted = (
                    last_regular_review is None
                    or time - last_regular_review >= resize_policy.review_interval
                )
                if permitted and good and trend and held > 0 and not context.pending_orders:
                    last_regular_review = time
            decision = decide_economic_transition(
                policy=active_gate,
                forecast=forecast,
                costs=costs,
                decision_time=time,
                current_weight=min(Decimal("1"), held_value / context.equity),
                trend_candidate=trend,
                trend_exit_confirmed=not trend,
                data_quality_passed=bool(good),
                risk_allows_entry=True,
                annualized_volatility=vol,
                resize_permitted=permitted,
                audit_policy=audit_policy,
                rebalance_cost=rebalance_cost,
                signal_budget_fraction=signal_fraction,
                risk_target_override=risk_weight if resize_policy is not None else None,
            )
            reason, q_long, hurdle = decision.reason, decision.q_long, decision.entry_hurdle
            if decision.action is not EconomicAction.HOLD_CURRENT:
                target = context.equity * decision.target_weight / price
                if target > held:
                    target = min(target, held + affordable / price)
            reference_qty = context.equity * risk_weight / price
            raw_target_qty = context.equity * decision.risk_target_weight * confidence / price
            buffer_reason = None
            lower = upper = None
            if buffer_policy is not None and reason == "COST_AWARE_RISK_REBALANCE":
                buffered = decide_buffered_target(
                    Snapshot(
                        decision_time=time,
                        available_time=time,
                        current_quantity=held,
                        raw_target_quantity=raw_target_qty,
                        reference_quantity=reference_qty,
                        hard_max_quantity=context.equity * active_gate.maximum_weight / price,
                        trend_active=trend,
                        pending_order_count=len(context.pending_orders),
                        regular_review_due_override=permitted,
                        equity_quantity=context.equity / price,
                    ),
                    buffer_policy,
                )
                buffer_reason, lower, upper = (
                    buffered.reason,
                    buffered.lower_band,
                    buffered.upper_band,
                )
                # A pending reconciliation falls through to the existing order manager,
                # using the original desired target; it is never an unconditional cancel.
                if buffered.target_quantity is not None:
                    target = buffered.target_quantity
                    if target > held:
                        target = min(target, held + affordable / price)
            resize_details: dict[str, Any] = {}
            if resize_policy is not None:
                resize_details = {
                    "unsmoothed_risk_weight": str(raw_risk_weight),
                    "smoothed_risk_weight": str(risk_weight),
                    "smoother_time": smoother.time,
                    "last_regular_review": last_regular_review,
                    "resize_gate_reason": None,
                    "rebalance_risk_benefit": None,
                    "rebalance_cost_equity_fraction": None,
                    "risk_benefit_definition": "HALF_VARIANCE_TRACKING_LOSS_REDUCTION_REVIEW_HORIZON",
                }
                if reason == "COST_AWARE_RISK_REBALANCE" and not context.pending_orders:
                    quantized = target_quantity_adjustment(
                        target_quantity=target,
                        current_quantity=held,
                        signed_pending_quantity=Decimal("0"),
                        price=price,
                        quantity_step=rule.step_size,
                        minimum_notional=rule.minimum_notional,
                        minimum_economic_notional=max(
                            rule.minimum_notional, resize_policy.minimum_notional
                        ),
                    )
                    target = held + quantized.signed_order_quantity
                    delta_notional = abs(target - held) * price
                    leg_costs = estimated(delta_notional, delta_notional)
                    leg = leg_costs.entry if target > held else leg_costs.exit
                    adverse = delta_notional * (leg.total - leg.fee)
                    direction = Decimal("1") if target > held else Decimal("-1")
                    cost_fraction = (
                        adverse + (delta_notional + direction * adverse) * leg.fee
                    ) / context.equity
                    benefit = rebalance_risk_benefit(
                        min(Decimal("1"), held_value / context.equity),
                        min(Decimal("1"), target * price / context.equity),
                        raw_risk_weight * signal_fraction,
                        vol,
                        resize_policy.review_interval,
                    )
                    resize_details.update(
                        rebalance_risk_benefit=str(benefit),
                        rebalance_cost_equity_fraction=str(cost_fraction),
                    )
                    veto = (
                        "MINIMUM_REBALANCE_DELTA"
                        if delta_notional / context.equity < resize_policy.minimum_weight_change
                        or delta_notional < resize_policy.minimum_notional
                        else "REBALANCE_COST_EXCEEDS_RISK_BENEFIT"
                        if benefit <= 0
                        or cost_fraction > resize_policy.cost_benefit_lambda * benefit
                        else "REBALANCE_RISK_BENEFIT_COVERS_COST"
                    )
                    resize_details["resize_gate_reason"] = veto
                    if veto != "REBALANCE_RISK_BENEFIT_COVERS_COST":
                        target = held
            calibration_through = (
                (forecast.residual_calibrated_through or forecast.calibrated_through)
                if forecast
                else None
            )
            details = {
                "forecast_status": "MISSING_FORECAST"
                if forecast is None
                else forecast.calibration_status.value,
                "missing_reason": "MARKET_OR_RISK_INPUT_INVALID"
                if not good
                else "MODEL_NOT_FITTED_OR_NO_VALID_FEATURE_ROW"
                if forecast is None
                else None,
                "feature_quality": "VALID" if features.valid[i] else "FULL_ML_FEATURES_INVALID",
                "raw_prediction": None,
                "mean_bias": None,
                "raw_prediction_missing_reason": "NOT_PERSISTED_IN_ORIGINAL_FROZEN_FORECAST",
                "corrected_prediction": str(forecast.expected_gross_return) if forecast else None,
                "p_net_positive": str(forecast.p_net_positive) if forecast else None,
                "residual_interval_width": str(forecast.q90_return - forecast.q10_return)
                if forecast
                else None,
                "uncertainty_definition": audit_policy.uncertainty_definition,
                "forecast_available_time": forecast.available_time if forecast else None,
                "calibration_end": forecast.calibrated_through if forecast else None,
                "entry_cost_estimate": str(costs.entry.total),
                "exit_cost_estimate": str(costs.exit.total),
                "entry_cost_notional": str(entry_notional),
                "exit_cost_notional": str(held_value or entry_notional),
                "holding_cost": str(costs.holding),
                "cost_lambda": str(active_gate.lambda_cost),
                "execution_buffer": str(active_gate.execution_uncertainty_buffer),
                "exit_hurdle": str(decision.exit_hurdle),
                "risk_only_weight": str(decision.risk_target_weight),
                "risk_vol_estimate": str(vol),
                "risk_target": str(active_gate.target_volatility),
                "raw_risk_weight": str(risk_weight),
                "raw_target_quantity": str(raw_target_qty),
                "reference_quantity": str(reference_qty),
                "hard_max_quantity": str(context.equity * active_gate.maximum_weight / price),
                "signal_budget_fraction": str(signal_fraction),
                "buffer_reason": buffer_reason,
                "buffer_lower": str(lower) if lower is not None else None,
                "buffer_upper": str(upper) if upper is not None else None,
                "last_resize_time_before_decision": last_resize_time,
                "confidence_multiplier": str(decision.alpha_confidence_multiplier),
                "signal_filter_pass": decision.signal_filter_pass,
                "cost_filter_pass": decision.cost_filter_pass,
                "probability_filter_pass": decision.probability_filter_pass,
                "uncertainty_filter_pass": decision.uncertainty_filter_pass,
                "reserved_cash": str(reserved_cash),
                "buy_reserve_factor": str(buy_factor),
                "rebalance_permitted": permitted,
                "enabled_switches": audit_policy.switches.model_dump_json(),
                "decision_value_kind": decision.decision_value_kind,
                "q10": str(forecast.q10_return) if forecast else None,
                "q50": str(forecast.q50_return) if forecast else None,
                "q90": str(forecast.q90_return) if forecast else None,
                "quantile_width": str(forecast.q90_return - forecast.q10_return)
                if forecast
                else None,
                "distribution_penalty": str(decision.distribution_penalty),
                "mean_estimation_uncertainty": None,
                "mean_estimation_uncertainty_status": "NOT_ESTIMATED_NOT_RESIDUAL_WIDTH",
                "point_forecast_status": forecast.point_forecast_status.value
                if forecast
                else "MODEL_MISSING",
                "residual_calibration_status": str(forecast.residual_calibration_status)
                if forecast and forecast.residual_calibration_status
                else "UNSPECIFIED",
                "probability_calibration_status": str(forecast.probability_calibration_status)
                if forecast and forecast.probability_calibration_status
                else "UNSPECIFIED",
                "calibration_age_days": (time - calibration_through).total_seconds() / 86400
                if calibration_through is not None
                else None,
                "calibration_expiry_policy": "NO_AGE_CUTOFF_DIAGNOSE_ONLY"
                if audit_policy.maximum_calibration_age_days is None
                else str(audit_policy.maximum_calibration_age_days),
                "risk_rebalance_cost_rate": str(rebalance_cost.total) if rebalance_cost else None,
                **resize_details,
            }
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
            minimum_economic_notional=rule.minimum_notional,
        )
        if audit_policy is not None and audit_policy.version == "cat-audit-r2":
            execution = audit_policy.execution
            known_natr = float(features.values[i, 9])
            if np.isfinite(known_natr) and event.volume > 0:
                notional = abs(adjustment.signed_order_quantity) * price
                increment = estimate_spot_transition_costs(
                    available_time=time,
                    natr=decimal(known_natr),
                    quote_volume=event.volume * price,
                    order_notional=notional,
                    exit_order_notional=notional,
                    fee_bps=execution.fee_bps * cost_multiplier,
                    half_spread_bps=execution.half_spread_bps * spread_multiplier * cost_multiplier,
                    slippage_floor_bps=execution.slippage_floor_bps
                    * slippage_multiplier
                    * cost_multiplier,
                    natr_slippage_coefficient=execution.natr_slippage_coefficient
                    * slippage_multiplier
                    * cost_multiplier,
                    impact_coefficient_bps=execution.impact_coefficient_bps * cost_multiplier,
                    latency_adverse_bps=execution.latency_adverse_bps
                    * latency_multiplier
                    * cost_multiplier,
                    exit_latency_adverse_bps=execution.latency_adverse_bps
                    * latency_multiplier
                    * cost_multiplier,
                )
                leg = increment.entry if adjustment.signed_order_quantity >= 0 else increment.exit
                adverse = notional * (leg.total - leg.fee)
                direction = Decimal("1") if adjustment.signed_order_quantity >= 0 else Decimal("-1")
                details.update(
                    {
                        "planned_increment_cost_rate": str(leg.total),
                        "planned_increment_cost_usdt": str(
                            adverse + (notional + direction * adverse) * leg.fee
                        ),
                        "planned_increment_fee_currency": "USDT",
                        "cost_estimate_available_time": time,
                        "estimate_uses_future_fill": False,
                    }
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
                "run_id": str(spec.run_id),
                "symbol": f"{market_spec.base_asset}USDT",
                "decision_time": time,
                "available_time": event.available_time,
                "trend_state": "LONG" if trend else "FLAT",
                "current_weight": str(held * price / context.equity),
                "final_weight": str(target * price / context.equity),
                "planned_order_notional": str(abs(adjustment.signed_order_quantity) * price),
                "signed_planned_quantity": str(adjustment.signed_order_quantity),
                "cancel_pending_first": adjustment.cancel_pending_first,
                "quantity_adjustment_reason": adjustment.reason,
                "unexecuted_target_residual": str(
                    target
                    - held
                    - context.signed_pending_quantity
                    - adjustment.signed_order_quantity
                ),
                "risk_escalation": (
                    "UNTRADEABLE_EXIT_RESIDUAL"
                    if target == 0
                    and held > 0
                    and adjustment.signed_order_quantity == 0
                    and not context.pending_orders
                    else None
                ),
                **details,
            }
        )
        if adjustment.cancel_pending_first:
            return BacktestDecisionUpdate(
                cancel_order_ids=tuple(p.backtest_order_id for p in context.pending_orders)
            )
        delta = adjustment.signed_order_quantity
        if delta == 0 or (terminal_exit and time == bars[-1].available_time):
            return BacktestDecisionUpdate()
        if audit_policy is not None:
            last_resize_time = time
        if resize_policy is not None:
            last_regular_review = time
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
    by_order = {str(order.order.backtest_order_id): order for order in result.orders}
    for number, row in enumerate(decisions, 1):
        key = f"{spec.run_id}-{number}"
        order = by_order.get(key)
        fills = [fill for fill in result.fills if str(fill.backtest_order_id) == key]
        row.update(
            {
                "order_id": key if order else None,
                "actual_fill_notional": str(
                    sum((fill.cost_breakdown.gross_notional for fill in fills), Decimal("0"))
                ),
                "realized_execution_cost": str(
                    sum((fill.cost_breakdown.total for fill in fills), Decimal("0"))
                ),
                "rejection_reason": str(order.rejection_code)
                if order and order.rejection_code
                else None,
                "order_status": str(order.status) if order else "NO_ORDER",
                "outcome_fields_available_after_decision": True,
            }
        )
        if row.get("planned_increment_cost_usdt") is not None:
            row["realized_minus_planned_cost_usdt"] = str(
                Decimal(row["realized_execution_cost"])
                - Decimal(row["planned_increment_cost_usdt"])
            )
            row["cost_error_interpretation"] = (
                "estimate_vs_fill_quantity_next_open_liquidity; separate from accounting_identity"
            )
    return result, decisions
