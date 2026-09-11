"""Decision-time estimates of both execution legs and directional carrying cost."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal


class ExecutionLegCost(DomainModel):
    fee: NonNegativeDecimal
    half_spread: NonNegativeDecimal
    slippage: NonNegativeDecimal
    impact: NonNegativeDecimal
    latency_adverse_selection: NonNegativeDecimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return (
            self.fee
            + self.half_spread
            + self.slippage
            + self.impact
            + self.latency_adverse_selection
        )


class TransitionCostEstimate(DomainModel):
    entry: ExecutionLegCost
    exit: ExecutionLegCost
    expected_funding: FiniteDecimal = Decimal("0")
    expected_borrow_interest: NonNegativeDecimal = Decimal("0")
    settlement_cost: NonNegativeDecimal = Decimal("0")
    available_time: UtcDateTime
    source: str

    @property
    def holding(self) -> Decimal:
        return self.expected_funding + self.expected_borrow_interest + self.settlement_cost

    @property
    def round_trip(self) -> Decimal:
        return self.entry.total + self.exit.total + max(Decimal("0"), self.holding)


def estimate_spot_transition_costs(
    *,
    available_time: UtcDateTime,
    natr: Decimal,
    quote_volume: Decimal,
    order_notional: Decimal,
    fee_bps: Decimal = Decimal("10"),
    half_spread_bps: Decimal = Decimal("1"),
    slippage_floor_bps: Decimal = Decimal("2"),
    impact_coefficient_bps: Decimal = Decimal("25"),
    latency_adverse_bps: Decimal = Decimal("1"),
    exit_order_notional: Decimal | None = None,
    exit_latency_adverse_bps: Decimal = Decimal("0"),
    natr_slippage_coefficient: Decimal = Decimal("0.01"),
) -> TransitionCostEstimate:
    exit_notional = order_notional if exit_order_notional is None else exit_order_notional
    if (
        min(
            natr,
            order_notional,
            fee_bps,
            half_spread_bps,
            slippage_floor_bps,
            impact_coefficient_bps,
            latency_adverse_bps,
            exit_notional,
            exit_latency_adverse_bps,
            natr_slippage_coefficient,
        )
        < 0
        or quote_volume <= 0
    ):
        raise ValueError("cost estimates require nonnegative known inputs and positive liquidity")
    impact = impact_coefficient_bps / 10000 * min(Decimal("1"), order_notional / quote_volume)
    slippage = slippage_floor_bps / 10000 + natr_slippage_coefficient * natr
    entry = ExecutionLegCost(
        fee=fee_bps / 10000,
        half_spread=half_spread_bps / 10000,
        slippage=slippage,
        impact=impact,
        latency_adverse_selection=latency_adverse_bps / 10000,
    )
    exit_leg = entry.model_copy(
        update={
            "latency_adverse_selection": exit_latency_adverse_bps / 10000,
            "impact": impact_coefficient_bps
            / 10000
            * min(Decimal("1"), exit_notional / quote_volume),
        }
    )
    return TransitionCostEstimate(
        entry=entry,
        exit=exit_leg,
        available_time=available_time,
        source="PREDECLARED_PROXY_FROM_CLOSED_BAR_NOT_HISTORICAL_ORDERBOOK_OR_FEE_TIER",
    )
