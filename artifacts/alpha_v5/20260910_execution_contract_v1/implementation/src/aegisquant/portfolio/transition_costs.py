"""Decision-time estimates of both execution legs and directional carrying cost."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval


class ImpactModel(DomainModel):
    """A curve and its inverse use the same participation unit and time horizon."""

    model_id: Literal["LINEAR_PROXY_V1", "SQRT_PROXY_V1", "LEGACY_SQRT_CAPACITY_V0"]
    coefficient_bps: NonNegativeDecimal
    horizon_seconds: int = Field(gt=0)
    participation_unit: Literal["ORDER_QUOTE_NOTIONAL_OVER_WINDOW_QUOTE_TURNOVER"]
    target: Literal["TOTAL_PRICE_IMPACT", "RESIDUAL_BEYOND_REFERENCE"]
    evidence_status: Literal["PROXY_ONLY", "VERIFIED"]
    maximum_supported_participation: UnitInterval
    calibration_sha256: str | None = None

    @field_validator("calibration_sha256")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        return (
            ensure_sha256(value, field_name="impact calibration hash")
            if value is not None
            else None
        )

    @model_validator(mode="after")
    def validate_evidence(self) -> ImpactModel:
        if self.maximum_supported_participation <= 0:
            raise ValueError("impact requires a positive supported participation range")
        if (self.evidence_status == "VERIFIED") != (self.calibration_sha256 is not None):
            raise ValueError("verified impact requires a calibration evidence hash")
        return self

    def _participation_effect(self, participation: Decimal) -> Decimal:
        if (
            not participation.is_finite()
            or not 0 <= participation <= self.maximum_supported_participation
        ):
            raise ValueError("AQ-IMPACT-OUTSIDE-SUPPORTED-PARTICIPATION")
        return participation if self.model_id == "LINEAR_PROXY_V1" else participation.sqrt()

    def impact_bps(self, participation: Decimal) -> Decimal:
        return self.coefficient_bps * self._participation_effect(participation)

    def impact_fraction(self, participation: Decimal) -> Decimal:
        # Preserve the legacy Decimal evaluation order used by decision-time estimates.
        return self.coefficient_bps / 10000 * self._participation_effect(participation)

    def participation_for_impact(self, maximum_bps: Decimal) -> Decimal:
        if not maximum_bps.is_finite() or maximum_bps < 0:
            raise ValueError("maximum impact must be finite and nonnegative")
        if self.coefficient_bps == 0:
            return self.maximum_supported_participation
        ratio = maximum_bps / self.coefficient_bps
        return min(
            self.maximum_supported_participation,
            ratio if self.model_id == "LINEAR_PROXY_V1" else ratio**2,
        )


def legacy_impact_model(coefficient: Decimal, *, capacity: bool = False) -> ImpactModel:
    """Name the two old proxy conventions; never silently change either formula."""
    return ImpactModel(
        model_id="LEGACY_SQRT_CAPACITY_V0" if capacity else "LINEAR_PROXY_V1",
        coefficient_bps=coefficient,
        horizon_seconds=86400 if capacity else 14400,
        participation_unit="ORDER_QUOTE_NOTIONAL_OVER_WINDOW_QUOTE_TURNOVER",
        target="TOTAL_PRICE_IMPACT",
        evidence_status="PROXY_ONLY",
        maximum_supported_participation=Decimal("1"),
    )


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
    impact_model: ImpactModel | None = None,
    liquidity_horizon_seconds: int | None = None,
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
    curve = impact_model or legacy_impact_model(impact_coefficient_bps)
    if impact_model is not None and (
        curve.coefficient_bps != impact_coefficient_bps
        or curve.horizon_seconds != liquidity_horizon_seconds
    ):
        raise ValueError("AQ-IMPACT-COEFFICIENT-OR-HORIZON-MISMATCH")
    impact = curve.impact_fraction(min(Decimal("1"), order_notional / quote_volume))
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
            "impact": curve.impact_fraction(min(Decimal("1"), exit_notional / quote_volume)),
        }
    )
    return TransitionCostEstimate(
        entry=entry,
        exit=exit_leg,
        available_time=available_time,
        source=(
            "PREDECLARED_PROXY_FROM_CLOSED_BAR_NOT_HISTORICAL_ORDERBOOK_OR_FEE_TIER"
            if impact_model is None
            else f"EXPLICIT_IMPACT:{curve.model_id}:{curve.horizon_seconds}s:{curve.evidence_status}"
        ),
    )
