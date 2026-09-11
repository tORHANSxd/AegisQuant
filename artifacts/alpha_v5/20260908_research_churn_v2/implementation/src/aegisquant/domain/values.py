"""Decimal economic value objects with explicit units and rounding rules."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import AssetId


def validate_decimal(value: object) -> Decimal:
    """Forbid non-finite and signed-zero economic values."""
    if not isinstance(value, Decimal):
        raise TypeError("economic values require Decimal")
    if not value.is_finite():
        raise ValueError("economic values must be finite")
    if value.is_zero() and value.is_signed():
        raise ValueError("negative zero is forbidden")
    return value


def canonical_result(value: Decimal) -> Decimal:
    """Remove a signed zero created by exact Decimal arithmetic."""
    return value.copy_abs() if value.is_zero() else value


def exact_decimal_sum(values: Iterable[Decimal]) -> Decimal:
    """Sum finite posted amounts without losing small terms to context precision."""
    amounts = tuple(validate_decimal(value) for value in values)
    nonzero = tuple(value for value in amounts if value)
    if not nonzero:
        return Decimal("0")
    lowest = min(int(value.as_tuple().exponent) for value in nonzero)
    highest = max(value.adjusted() for value in nonzero)
    with localcontext() as context:
        context.prec = max(context.prec, highest - lowest + len(str(len(amounts))) + 2)
        return canonical_result(sum(amounts, Decimal("0")))


FiniteDecimal = Annotated[Decimal, AfterValidator(validate_decimal)]
NonNegativeDecimal = Annotated[FiniteDecimal, Field(ge=Decimal("0"))]
PositiveDecimal = Annotated[FiniteDecimal, Field(gt=Decimal("0"))]
UnitInterval = Annotated[
    FiniteDecimal,
    Field(ge=Decimal("0"), le=Decimal("1")),
]


class RoundingMode(StrEnum):
    """Explicit rounding modes accepted at market-rule boundaries."""

    DOWN = "DOWN"
    FLOOR = "FLOOR"
    CEILING = "CEILING"
    HALF_EVEN = "HALF_EVEN"


ROUNDING_BY_MODE = {
    RoundingMode.DOWN: ROUND_DOWN,
    RoundingMode.FLOOR: ROUND_FLOOR,
    RoundingMode.CEILING: ROUND_CEILING,
    RoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
}


def quantize_increment(value: Decimal, increment: Decimal, mode: RoundingMode) -> Decimal:
    """Quantize by a positive market-rule increment without using round()."""
    value = validate_decimal(value)
    increment = validate_decimal(increment)
    if increment <= 0:
        raise ValueError("quantization increment must be positive")
    steps = (value / increment).to_integral_value(rounding=ROUNDING_BY_MODE[mode])
    return validate_decimal(canonical_result(steps * increment))


class Money(DomainModel):
    """Signed monetary amount denominated in one explicit asset."""

    amount: FiniteDecimal
    asset_id: AssetId

    def _same_asset(self, other: Money) -> None:
        if self.asset_id != other.asset_id:
            raise ValueError("cannot mix monetary assets")

    def __add__(self, other: object) -> Self:
        if not isinstance(other, Money):
            raise TypeError("Money can only be added to Money")
        self._same_asset(other)
        return type(self)(
            amount=canonical_result(self.amount + other.amount), asset_id=self.asset_id
        )

    def __sub__(self, other: object) -> Self:
        if not isinstance(other, Money):
            raise TypeError("Money can only be subtracted from Money")
        self._same_asset(other)
        return type(self)(
            amount=canonical_result(self.amount - other.amount), asset_id=self.asset_id
        )

    def quantize(self, increment: Decimal, mode: RoundingMode) -> Self:
        return type(self)(
            amount=quantize_increment(self.amount, increment, mode),
            asset_id=self.asset_id,
        )


class Quantity(DomainModel):
    """Signed asset quantity, never an unlabelled scalar."""

    amount: FiniteDecimal
    asset_id: AssetId

    def _same_asset(self, other: Quantity) -> None:
        if self.asset_id != other.asset_id:
            raise ValueError("cannot mix asset quantities")

    def __add__(self, other: object) -> Self:
        if not isinstance(other, Quantity):
            raise TypeError("Quantity can only be added to Quantity")
        self._same_asset(other)
        return type(self)(
            amount=canonical_result(self.amount + other.amount), asset_id=self.asset_id
        )

    def __sub__(self, other: object) -> Self:
        if not isinstance(other, Quantity):
            raise TypeError("Quantity can only be subtracted from Quantity")
        self._same_asset(other)
        return type(self)(
            amount=canonical_result(self.amount - other.amount), asset_id=self.asset_id
        )

    def quantize(self, increment: Decimal, mode: RoundingMode) -> Self:
        return type(self)(
            amount=quantize_increment(self.amount, increment, mode),
            asset_id=self.asset_id,
        )


class Price(DomainModel):
    """Positive quote-asset amount per one base-asset unit."""

    amount: PositiveDecimal
    base_asset_id: AssetId
    quote_asset_id: AssetId

    @model_validator(mode="after")
    def assets_must_differ(self) -> Price:
        if self.base_asset_id == self.quote_asset_id:
            raise ValueError("price base and quote assets must differ")
        return self

    def quantize(self, increment: Decimal, mode: RoundingMode) -> Self:
        return type(self)(
            amount=quantize_increment(self.amount, increment, mode),
            base_asset_id=self.base_asset_id,
            quote_asset_id=self.quote_asset_id,
        )
