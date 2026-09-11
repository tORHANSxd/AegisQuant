"""Deterministic P06 cost, latency, liquidity and fault stress transformations."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_CEILING, Decimal

from aegisquant.backtest.models import (
    BarEvent,
    BookLevel,
    CostSchedule,
    FaultType,
    FaultWindow,
    FundingEvent,
    L2BookEvent,
    LatencyPolicy,
    MarketEvent,
    StressScenario,
    StressType,
    TradeQuoteEvent,
)
from aegisquant.domain.base import DomainModel


class StressApplication(DomainModel):
    scenario: StressScenario
    market_events: tuple[MarketEvent, ...]
    funding_events: tuple[FundingEvent, ...]
    cost_schedules: tuple[CostSchedule, ...]
    latency_policy: LatencyPolicy
    faults: tuple[FaultWindow, ...]
    model_available: bool
    strategy_enabled: bool
    correlation_target: Decimal | None
    historical_replay_required: bool


def _in_window(scenario: StressScenario, event: object) -> bool:
    available = getattr(event, "available_time", None)
    return available is not None and scenario.starts_at <= available < scenario.ends_at


def _scaled_latency(value: int, multiplier: Decimal) -> int:
    scaled = (Decimal(value) * multiplier / Decimal("1000")).to_integral_value(
        rounding=ROUND_CEILING
    )
    return int(scaled) * 1000


def _scale_prices(event: MarketEvent, multiplier: Decimal) -> MarketEvent:
    if isinstance(event, BarEvent):
        return event.model_copy(
            update={
                "open": event.open * multiplier,
                "high": event.high * multiplier,
                "low": event.low * multiplier,
                "close": event.close * multiplier,
            }
        )
    if isinstance(event, TradeQuoteEvent):
        return event.model_copy(
            update={
                "trade_price": event.trade_price * multiplier,
                "bid_price": event.bid_price * multiplier,
                "ask_price": event.ask_price * multiplier,
            }
        )
    return event.model_copy(
        update={
            "bids": tuple(
                BookLevel(price=level.price * multiplier, quantity=level.quantity)
                for level in event.bids
            ),
            "asks": tuple(
                BookLevel(price=level.price * multiplier, quantity=level.quantity)
                for level in event.asks
            ),
        }
    )


def _scale_liquidity(event: MarketEvent, multiplier: Decimal) -> MarketEvent:
    if isinstance(event, BarEvent):
        return event.model_copy(update={"volume": event.volume * multiplier})
    if isinstance(event, TradeQuoteEvent):
        return event.model_copy(
            update={
                "trade_quantity": event.trade_quantity * multiplier,
                "bid_quantity": event.bid_quantity * multiplier,
                "ask_quantity": event.ask_quantity * multiplier,
            }
        )
    return event.model_copy(
        update={
            "bids": tuple(
                BookLevel(price=level.price, quantity=level.quantity * multiplier)
                for level in event.bids
            ),
            "asks": tuple(
                BookLevel(price=level.price, quantity=level.quantity * multiplier)
                for level in event.asks
            ),
        }
    )


def apply_stress(
    *,
    scenario: StressScenario,
    market_events: tuple[MarketEvent, ...],
    funding_events: tuple[FundingEvent, ...],
    cost_schedules: tuple[CostSchedule, ...],
    latency_policy: LatencyPolicy,
) -> StressApplication:
    events = market_events
    funding = funding_events
    costs = cost_schedules
    latency = latency_policy
    faults: tuple[FaultWindow, ...] = ()
    model_available = True
    strategy_enabled = True
    correlation_target: Decimal | None = None
    historical_replay_required = False
    stress_type = scenario.stress_type
    if stress_type is StressType.COST_MULTIPLIER:
        costs = tuple(
            schedule.model_copy(
                update={
                    "maker_fee_bps": schedule.maker_fee_bps * scenario.multiplier,
                    "taker_fee_bps": schedule.taker_fee_bps * scenario.multiplier,
                    "half_spread_bps": schedule.half_spread_bps * scenario.multiplier,
                    "slippage_bps": schedule.slippage_bps * scenario.multiplier,
                    "impact_coefficient_bps": schedule.impact_coefficient_bps * scenario.multiplier,
                    "maximum_impact_bps": schedule.maximum_impact_bps * scenario.multiplier,
                    "funding_rate": schedule.funding_rate * scenario.multiplier,
                    "borrow_rate_annual": schedule.borrow_rate_annual * scenario.multiplier,
                    "settlement_fee_bps": schedule.settlement_fee_bps * scenario.multiplier,
                }
            )
            for schedule in costs
        )
    elif stress_type is StressType.LATENCY_MULTIPLIER:
        latency = latency.model_copy(
            update={
                "signal_ns": _scaled_latency(latency.signal_ns, scenario.multiplier),
                "risk_ns": _scaled_latency(latency.risk_ns, scenario.multiplier),
                "network_ns": _scaled_latency(latency.network_ns, scenario.multiplier),
                "acknowledgement_ns": _scaled_latency(
                    latency.acknowledgement_ns, scenario.multiplier
                ),
                "cancel_ns": _scaled_latency(latency.cancel_ns, scenario.multiplier),
            }
        )
    elif stress_type is StressType.LIQUIDITY_FACTOR:
        events = tuple(
            _scale_liquidity(event, scenario.multiplier) if _in_window(scenario, event) else event
            for event in events
        )
    elif stress_type in {StressType.STABLECOIN_DEPEG, StressType.PRICE_GAP}:
        events = tuple(
            _scale_prices(event, scenario.multiplier) if _in_window(scenario, event) else event
            for event in events
        )
    elif stress_type is StressType.FUNDING_SHOCK:
        funding = tuple(
            event.model_copy(update={"funding_rate": event.funding_rate * scenario.multiplier})
            if _in_window(scenario, event)
            else event
            for event in funding
        )
    elif stress_type is StressType.ORDER_BOOK_GAP:
        transformed: list[MarketEvent] = []
        for event in events:
            if _in_window(scenario, event) and isinstance(event, L2BookEvent):
                bids = event.bids[1:] or (
                    BookLevel(price=event.bids[0].price, quantity=Decimal("0")),
                )
                asks = event.asks[1:] or (
                    BookLevel(price=event.asks[0].price, quantity=Decimal("0")),
                )
                transformed.append(event.model_copy(update={"bids": bids, "asks": asks}))
            else:
                transformed.append(event)
        events = tuple(transformed)
    elif stress_type in {
        StressType.VENUE_HALT,
        StressType.RATE_LIMIT_DISCONNECT,
    }:
        fault_type = (
            FaultType.VENUE_HALT if stress_type is StressType.VENUE_HALT else FaultType.RATE_LIMIT
        )
        venue_ids = {event.venue_id for event in events if _in_window(scenario, event)}
        faults = tuple(
            FaultWindow(
                fault_type=fault_type,
                venue_id=venue_id,
                starts_at=scenario.starts_at,
                ends_at=scenario.ends_at,
                evidence=f"stress:{scenario.stress_scenario_id}",
            )
            for venue_id in sorted(venue_ids, key=str)
        )
    elif stress_type is StressType.DATA_LAG:
        shifted: list[MarketEvent] = []
        for event in events:
            if _in_window(scenario, event):
                delay = event.available_time - event.event_time
                delay_microseconds = (
                    delay.days * 86_400 + delay.seconds
                ) * 1_000_000 + delay.microseconds
                shifted.append(
                    event.model_copy(
                        update={
                            "available_time": event.event_time
                            + timedelta(
                                microseconds=int(Decimal(delay_microseconds) * scenario.multiplier)
                            )
                        }
                    )
                )
            else:
                shifted.append(event)
        events = tuple(shifted)
    elif stress_type is StressType.MODEL_UNAVAILABLE:
        model_available = False
    elif stress_type is StressType.STRATEGY_FAILURE:
        strategy_enabled = False
    elif stress_type is StressType.CORRELATION_SHOCK:
        if scenario.multiplier > 1:
            raise ValueError("correlation shock target cannot exceed one")
        correlation_target = scenario.multiplier
    elif stress_type is StressType.HISTORICAL_EVENT_REPLAY:
        historical_replay_required = True
    else:
        raise ValueError("unsupported stress scenario")
    return StressApplication(
        scenario=scenario,
        market_events=events,
        funding_events=funding,
        cost_schedules=costs,
        latency_policy=latency,
        faults=faults,
        model_available=model_available,
        strategy_enabled=strategy_enabled,
        correlation_target=correlation_target,
        historical_replay_required=historical_replay_required,
    )
