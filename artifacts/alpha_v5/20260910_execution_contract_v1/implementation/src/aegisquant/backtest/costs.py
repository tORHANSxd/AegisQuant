"""Versioned exact cost, funding and borrow calculations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from aegisquant.backtest.models import (
    BacktestOrder,
    CostBreakdown,
    CostSchedule,
    FeeSettlement,
    FeeTerms,
    FillSlice,
    LiquidityRole,
)
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import AssetId, InstrumentId, VenueId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Money, Price, canonical_result
from aegisquant.portfolio.transition_costs import legacy_impact_model

BPS = Decimal("10000")
SECONDS_PER_YEAR = Decimal("31557600")


@dataclass(frozen=True)
class FeeAccountState:
    available_balances: Mapping[AssetId, Decimal]
    quote_fx: Mapping[AssetId, Decimal]
    fx_available_at: UtcDateTime


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

    def decision_at(self, order: BacktestOrder, decision_time: UtcDateTime) -> CostSchedule:
        """Strict decision-known view; execution truth still uses effective-time at()."""
        schedule = self.at(order, decision_time)
        proof = schedule.evidence
        if proof is None or proof.available_at > decision_time:
            raise ValueError("AQ-EXECUTION-FEE-UNKNOWN-AT-DECISION")
        if proof.verified_kind != "HISTORICAL_ACCOUNT_EVIDENCE":
            raise ValueError("AQ-EXECUTION-FEE-PROXY-ONLY")
        return schedule

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
    strict_evidence: bool = False,
    fee_account: FeeAccountState | None = None,
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
    proof = schedule.evidence
    basis = fill_slice.reference
    if (proof is None) != (basis is None):
        raise ValueError("AQ-EXECUTION-MIXED-LEGACY-AND-VERSIONED-COST")
    curve = (
        proof.impact_model
        if proof is not None
        else legacy_impact_model(schedule.impact_coefficient_bps)
    )
    if basis is not None:
        if curve.horizon_seconds != basis.participation_window_seconds:
            raise ValueError("AQ-IMPACT-HORIZON-MISMATCH")
        participation = quantity * contract_multiplier * reference / basis.window_quote_turnover
    if strict_evidence and (
        proof is None
        or basis is None
        or proof.verified_kind != "HISTORICAL_ACCOUNT_EVIDENCE"
        or basis.evidence_kind != "HISTORICAL_MARKET_EVIDENCE"
        or curve.evidence_status != "VERIFIED"
        or proof.fee_terms is None
    ):
        raise ValueError("AQ-EXECUTION-EMPIRICAL-EVIDENCE-MISSING")
    impact_bps = min(schedule.maximum_impact_bps, curve.impact_bps(participation))
    is_taker = fill_slice.liquidity_role is LiquidityRole.TAKER
    spread_bps = schedule.half_spread_bps if is_taker else Decimal("0")
    slippage_bps = schedule.slippage_bps if is_taker else Decimal("0")
    if basis is not None:
        included = set(basis.included_cost_components)
        if "SPREAD" in included:
            spread_bps = Decimal("0")
        if "SLIPPAGE" in included:
            slippage_bps = Decimal("0")
        if "RESIDUAL_IMPACT" in included or (
            "VISIBLE_DEPTH" in included and curve.target == "TOTAL_PRICE_IMPACT"
        ):
            impact_bps = Decimal("0")
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
    native_fee = None
    if proof is not None and proof.fee_terms is not None:
        if fee_account is None:
            raise ValueError("AQ-EXECUTION-NATIVE-FEE-ACCOUNT-STATE-REQUIRED")
        native_fee = settle_execution_fee(
            terms=proof.fee_terms,
            fill_time=fill_slice.event_time,
            role=fill_slice.liquidity_role,
            side=order.side,
            quantity=quantity * contract_multiplier,
            execution_price=execution,
            base_asset_id=base_asset_id,
            quote_asset_id=quote_asset_id,
            available_balances=fee_account.available_balances,
            quote_fx=fee_account.quote_fx,
            fx_available_at=fee_account.fx_available_at,
        )
    breakdown = CostBreakdown(
        asset_id=quote_asset_id,
        gross_notional=gross_notional,
        fee=native_fee.quote_equivalent
        if native_fee is not None
        else canonical_result(execution_notional * fee_bps / BPS),
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
        fee_settlement=native_fee,
    )
    return (
        Price(
            amount=execution,
            base_asset_id=base_asset_id,
            quote_asset_id=quote_asset_id,
        ),
        breakdown,
    )


def settle_execution_fee(
    *,
    terms: FeeTerms,
    fill_time: UtcDateTime,
    role: LiquidityRole,
    side: OrderSide,
    quantity: Decimal,
    execution_price: Decimal,
    base_asset_id: AssetId,
    quote_asset_id: AssetId,
    available_balances: Mapping[AssetId, Decimal],
    quote_fx: Mapping[AssetId, Decimal],
    fx_available_at: UtcDateTime,
) -> FeeSettlement:
    """Settle each partial fill separately; only the standard component is discounted."""
    if (
        not quantity.is_finite()
        or not execution_price.is_finite()
        or quantity <= 0
        or execution_price <= 0
        or fx_available_at > fill_time
    ):
        raise ValueError("AQ-EXECUTION-INVALID-FEE-OR-FUTURE-FX")
    if any(not value.is_finite() or value < 0 for value in available_balances.values()):
        raise ValueError("fee balances must be finite and nonnegative")
    normal_asset = (
        base_asset_id
        if terms.normal_fee_asset == "RECEIVED_ASSET" and side is OrderSide.BUY
        else quote_asset_id
    )
    standard = terms.standard.for_fill(role, side)
    other = terms.special.for_fill(role, side) + terms.tax.for_fill(role, side)
    notional = quantity * execution_price
    ordinary_quote = notional * (standard + other) / BPS
    active = (
        terms.discount_asset_id is not None
        and terms.standard_discount_fraction > 0
        and terms.discount_effective_from is not None
        and terms.discount_effective_from <= fill_time
        and (terms.discount_effective_to is None or fill_time < terms.discount_effective_to)
    )
    reason = (
        "DISCOUNT_NOT_EFFECTIVE" if terms.standard_discount_fraction > 0 and not active else None
    )
    # A rebate must never be reduced by a fee discount.
    discounted_quote = (
        notional
        * (standard - max(Decimal("0"), standard) * terms.standard_discount_fraction + other)
        / BPS
    )
    if active and terms.discount_asset_id is not None:
        fx = quote_fx.get(terms.discount_asset_id)
        if fx is None or not fx.is_finite() or fx <= 0:
            reason = "DISCOUNT_FX_UNAVAILABLE"
        elif discounted_quote <= 0:
            reason = "REBATE_USES_NORMAL_FEE_ASSET"
        elif available_balances.get(terms.discount_asset_id, Decimal("0")) < discounted_quote / fx:
            reason = "DISCOUNT_ASSET_BALANCE_INSUFFICIENT"
        else:
            return FeeSettlement(
                fee=Money(
                    amount=canonical_result(discounted_quote / fx), asset_id=terms.discount_asset_id
                ),
                quote_equivalent=canonical_result(discounted_quote),
                undiscounted_quote_equivalent=canonical_result(ordinary_quote),
                discount_applied=True,
                fallback_reason=None,
            )
    normal_fx = execution_price if normal_asset == base_asset_id else Decimal("1")
    native = canonical_result(ordinary_quote / normal_fx)
    received = (
        quantity
        if side is OrderSide.BUY and normal_asset == base_asset_id
        else notional
        if side is OrderSide.SELL
        else Decimal("0")
    )
    if native > available_balances.get(normal_asset, Decimal("0")) + received:
        raise ValueError("AQ-EXECUTION-NORMAL-FEE-ASSET-BALANCE-INSUFFICIENT")
    return FeeSettlement(
        fee=Money(amount=native, asset_id=normal_asset),
        quote_equivalent=canonical_result(ordinary_quote),
        undiscounted_quote_equivalent=canonical_result(ordinary_quote),
        discount_applied=False,
        fallback_reason=reason,
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
