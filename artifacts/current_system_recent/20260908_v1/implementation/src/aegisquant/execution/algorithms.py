"""Small deterministic execution policies for maker/taker and slicing."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    PositiveDecimal,
    Price,
    Quantity,
    canonical_result,
)


class ExecutionStyle(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    TIME_BOUNDED_PASSIVE = "TIME_BOUNDED_PASSIVE"
    TWAP = "TWAP"


class MarketExecutionQuote(DomainModel):
    bid: Price
    ask: Price
    maker_fee_bps: FiniteDecimal
    taker_fee_bps: FiniteDecimal
    estimated_taker_impact_bps: FiniteDecimal
    passive_nonfill_cost_bps: FiniteDecimal
    available_at: UtcDateTime

    @model_validator(mode="after")
    def validate_quote(self) -> MarketExecutionQuote:
        if self.bid.base_asset_id != self.ask.base_asset_id:
            raise ValueError("execution quote base asset mismatch")
        if self.bid.quote_asset_id != self.ask.quote_asset_id:
            raise ValueError("execution quote quote asset mismatch")
        if self.bid.amount > self.ask.amount:
            raise ValueError("execution quote is crossed")
        return self


class StyleDecision(DomainModel):
    style: ExecutionStyle
    expected_cost_bps: FiniteDecimal
    passive_cost_bps: FiniteDecimal
    aggressive_cost_bps: FiniteDecimal
    reason_code: str


def choose_maker_or_taker(
    *,
    quote: MarketExecutionQuote,
    maximum_passive_cost_bps: Decimal,
    reduce_only: bool,
) -> StyleDecision:
    """Choose the lower bounded cost; urgent reductions favor certainty on ties."""
    passive = canonical_result(quote.maker_fee_bps + quote.passive_nonfill_cost_bps)
    aggressive = canonical_result(quote.taker_fee_bps + quote.estimated_taker_impact_bps)
    passive_allowed = passive <= maximum_passive_cost_bps
    choose_taker = (
        not passive_allowed or aggressive < passive or (reduce_only and aggressive == passive)
    )
    return StyleDecision(
        style=ExecutionStyle.TAKER if choose_taker else ExecutionStyle.MAKER,
        expected_cost_bps=aggressive if choose_taker else passive,
        passive_cost_bps=passive,
        aggressive_cost_bps=aggressive,
        reason_code=("AQ-EXEC-TAKER-COST-OR-RISK" if choose_taker else "AQ-EXEC-MAKER-LOWER-COST"),
    )


class ExecutionSlice(DomainModel):
    sequence: int = Field(ge=0)
    quantity: Quantity
    release_at: UtcDateTime
    expire_at: UtcDateTime
    style: ExecutionStyle

    @model_validator(mode="after")
    def validate_window(self) -> ExecutionSlice:
        if self.quantity.amount <= 0:
            raise ValueError("execution slice quantity must be positive")
        if self.expire_at <= self.release_at:
            raise ValueError("execution slice requires a positive window")
        return self


def build_twap_slices(
    *,
    total_quantity: Quantity,
    slice_count: int,
    start_at: UtcDateTime,
    interval_seconds: int,
    passive_seconds: int,
) -> tuple[ExecutionSlice, ...]:
    if total_quantity.amount <= 0 or slice_count < 1:
        raise ValueError("TWAP requires positive quantity and slice count")
    if interval_seconds < 1 or passive_seconds < 1 or passive_seconds > interval_seconds:
        raise ValueError("TWAP timing window is invalid")
    base = total_quantity.amount / Decimal(slice_count)
    quantities = [base] * slice_count
    quantities[-1] = total_quantity.amount - sum(quantities[:-1], start=Decimal("0"))
    return tuple(
        ExecutionSlice(
            sequence=index,
            quantity=Quantity(amount=amount, asset_id=total_quantity.asset_id),
            release_at=start_at + timedelta(seconds=index * interval_seconds),
            expire_at=start_at + timedelta(seconds=index * interval_seconds + passive_seconds),
            style=ExecutionStyle.TIME_BOUNDED_PASSIVE,
        )
        for index, amount in enumerate(quantities)
    )


def protected_limit_price(
    *, side: OrderSide, quote: MarketExecutionQuote, protection_bps: PositiveDecimal
) -> Price:
    basis = Decimal("10000")
    reference = quote.ask if side is OrderSide.BUY else quote.bid
    multiplier = (
        Decimal("1") + protection_bps / basis
        if side is OrderSide.BUY
        else Decimal("1") - protection_bps / basis
    )
    if multiplier <= 0:
        raise ValueError("price protection would create a nonpositive limit")
    return reference.model_copy(update={"amount": reference.amount * multiplier})
