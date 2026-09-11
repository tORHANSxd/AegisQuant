"""Versioned exact cost, funding and borrow calculations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from aegisquant.backtest.models import (
    BacktestOrder,
    CostBreakdown,
    CostSchedule,
    FillSlice,
    LiquidityRole,
)
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import AssetId, InstrumentId, VenueId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Price, canonical_result

BPS = Decimal("10000")
SECONDS_PER_YEAR = Decimal("31557600")


class HistoricalCostBook:
    """Select exactly one non-overlapping cost schedule at an event time."""

    def __init__(self, schedules: Iterable[CostSchedule]) -> None:
        ordered = tuple(
            sorted(
                schedules,
                key=lambda item: (
                    str(item.venue_id),
                    str(item.instrument_id),
                    item.effective_from,
                ),
            )
        )
        if not ordered:
            raise ValueError("historical cost book cannot be empty")
        by_key: dict[tuple[str, str], list[CostSchedule]] = {}
        for schedule in ordered:
            by_key.setdefault((str(schedule.venue_id), str(schedule.instrument_id)), []).append(
                schedule
            )
        for values in by_key.values():
            for earlier, later in pairwise(values):
                if earlier.effective_to is None or earlier.effective_to > later.effective_from:
                    raise ValueError("AQ-BACKTEST-COST-SCHEDULE-OVERLAP")
                if earlier.effective_to < later.effective_from:
                    raise ValueError("AQ-BACKTEST-COST-SCHEDULE-GAP")
        self._schedules = ordered

    @property
    def schedules(self) -> tuple[CostSchedule, ...]:
        return self._schedules

    def at(self, order: BacktestOrder, event_time: UtcDateTime) -> CostSchedule:
        return self.for_instrument(order.venue_id, order.instrument_id, event_time)

    def for_instrument(
        self, venue_id: VenueId, instrument_id: InstrumentId, event_time: datetime
    ) -> CostSchedule:
        candidates = tuple(
            schedule
            for schedule in self._schedules
            if schedule.venue_id == venue_id
            and schedule.instrument_id == instrument_id
            and schedule.effective_from <= event_time
            and (schedule.effective_to is None or event_time < schedule.effective_to)
        )
        if len(candidates) != 1:
            raise ValueError("AQ-BACKTEST-HISTORICAL-COST-MISSING")
        return candidates[0]

    def borrow_cost_between(
        self,
        *,
        venue_id: VenueId,
        instrument_id: InstrumentId,
        start: datetime,
        end: datetime,
        borrowed_notional: Decimal,
    ) -> Decimal:
        """Accrue a quote-settled loan across each historical rate boundary."""
        total = Decimal("0")
        cursor = start
        while cursor < end:
            schedule = self.for_instrument(venue_id, instrument_id, cursor)
            stop = min(end, schedule.effective_to or end)
            elapsed = stop - cursor
            seconds = Decimal(elapsed.days * 86400 + elapsed.seconds) + Decimal(
                elapsed.microseconds
            ) / Decimal("1000000")
            total += borrowed_notional * schedule.borrow_rate_annual * seconds / SECONDS_PER_YEAR
            cursor = stop
        return canonical_result(total)


def execution_price_and_cost(
    *,
    order: BacktestOrder,
    fill_slice: FillSlice,
    schedule: CostSchedule,
    base_asset_id: AssetId,
    quote_asset_id: AssetId,
    contract_multiplier: Decimal = Decimal("1"),
    settlement_quantity: Decimal = Decimal("0"),
    liquidation_penalty_bps: Decimal = Decimal("0"),
) -> tuple[Price, CostBreakdown]:
    """Apply explicit adverse spread, slippage and size impact to one fill slice."""
    quantity = fill_slice.quantity
    if contract_multiplier <= 0 or not 0 <= settlement_quantity <= quantity:
        raise ValueError("invalid execution multiplier or settlement quantity")
    if liquidation_penalty_bps < 0:
        raise ValueError("liquidation penalty cannot be negative")
    reference = fill_slice.reference_price
    if fill_slice.available_liquidity == 0:
        participation = Decimal("1")
    else:
        participation = min(Decimal("1"), quantity / fill_slice.available_liquidity)
    impact_bps = min(
        schedule.maximum_impact_bps,
        schedule.impact_coefficient_bps * participation,
    )
    is_taker = fill_slice.liquidity_role is LiquidityRole.TAKER
    spread_bps = schedule.half_spread_bps if is_taker else Decimal("0")
    slippage_bps = schedule.slippage_bps if is_taker else Decimal("0")
    adverse_bps = spread_bps + slippage_bps + impact_bps
    direction = Decimal("1") if order.side is OrderSide.BUY else Decimal("-1")
    execution = canonical_result(reference * (Decimal("1") + direction * adverse_bps / BPS))
    gross_notional = canonical_result(quantity * contract_multiplier * reference)
    execution_notional = canonical_result(quantity * contract_multiplier * execution)
    fee_bps = (
        schedule.maker_fee_bps
        if fill_slice.liquidity_role is LiquidityRole.MAKER
        else schedule.taker_fee_bps
    )
    breakdown = CostBreakdown(
        asset_id=quote_asset_id,
        gross_notional=gross_notional,
        fee=canonical_result(execution_notional * fee_bps / BPS),
        spread=canonical_result(gross_notional * spread_bps / BPS),
        slippage=canonical_result(gross_notional * slippage_bps / BPS),
        impact=canonical_result(gross_notional * impact_bps / BPS),
        funding=Decimal("0"),
        borrow_interest=Decimal("0"),
        settlement_fee=canonical_result(
            settlement_quantity
            * contract_multiplier
            * execution
            * schedule.settlement_fee_bps
            / BPS
        ),
        liquidation_penalty=canonical_result(execution_notional * liquidation_penalty_bps / BPS),
    )
    return (
        Price(
            amount=execution,
            base_asset_id=base_asset_id,
            quote_asset_id=quote_asset_id,
        ),
        breakdown,
    )


def funding_cost(
    *,
    signed_quantity: Decimal,
    mark_price: Decimal,
    funding_rate: Decimal,
    contract_multiplier: Decimal = Decimal("1"),
) -> Decimal:
    """Return signed funding expense: positive is paid, negative is received."""
    if contract_multiplier <= 0:
        raise ValueError("funding multiplier must be positive")
    return canonical_result(signed_quantity * contract_multiplier * mark_price * funding_rate)


def borrow_interest_cost(
    *,
    borrowed_notional: Decimal,
    annual_rate: Decimal,
    elapsed_seconds: int,
) -> Decimal:
    if borrowed_notional < 0 or annual_rate < 0 or elapsed_seconds < 0:
        raise ValueError("borrow interest inputs cannot be negative")
    return canonical_result(
        borrowed_notional * annual_rate * Decimal(elapsed_seconds) / SECONDS_PER_YEAR
    )


def settlement_fee(*, notional: Decimal, schedule: CostSchedule) -> Decimal:
    if notional < 0:
        raise ValueError("settlement notional cannot be negative")
    return canonical_result(notional * schedule.settlement_fee_bps / BPS)
