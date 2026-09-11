"""Fresh dynamic instrument rules and exact local order quantization."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderIntent, OrderType
from aegisquant.domain.identifiers import InstrumentId, VenueId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    PositiveDecimal,
    Price,
    Quantity,
    RoundingMode,
    quantize_increment,
)


class TradingStatus(StrEnum):
    TRADING = "TRADING"
    HALTED = "HALTED"
    CLOSE_ONLY = "CLOSE_ONLY"


class PositionMode(StrEnum):
    ONE_WAY = "ONE_WAY"
    HEDGE = "HEDGE"


class MarginMode(StrEnum):
    CASH = "CASH"
    CROSS = "CROSS"
    ISOLATED = "ISOLATED"


class InstrumentRuleSnapshot(DomainModel):
    rule_version: str = Field(min_length=1)
    venue_id: VenueId
    instrument_id: InstrumentId
    price_tick: PositiveDecimal
    quantity_step: PositiveDecimal
    minimum_quantity: PositiveDecimal
    maximum_quantity: PositiveDecimal
    minimum_notional: PositiveDecimal
    supported_order_types: tuple[OrderType, ...] = Field(min_length=1)
    position_mode: PositionMode
    margin_mode: MarginMode
    trading_status: TradingStatus
    price_protection_bps: PositiveDecimal
    self_trade_prevention_modes: tuple[str, ...] = Field(min_length=1)
    request_weight: int = Field(ge=1)
    available_at: UtcDateTime
    valid_until: UtcDateTime

    @model_validator(mode="after")
    def validate_rule_range(self) -> InstrumentRuleSnapshot:
        if self.maximum_quantity < self.minimum_quantity:
            raise ValueError("instrument maximum quantity is below minimum")
        if self.valid_until <= self.available_at:
            raise ValueError("instrument rule snapshot must have a future expiry")
        if len(set(self.supported_order_types)) != len(self.supported_order_types):
            raise ValueError("instrument order types must be unique")
        return self


class QuantizedOrderValues(DomainModel):
    quantity: Quantity
    limit_price: Price | None
    reference_price: Price
    notional: PositiveDecimal
    rule_version: str


def quantize_order_values(
    *,
    intent: OrderIntent,
    rules: InstrumentRuleSnapshot,
    reference_price: Price,
    decision_time: UtcDateTime,
    reject_precision_change: bool = True,
) -> QuantizedOrderValues:
    """Validate freshness and return exact venue-valid values."""
    if rules.instrument_id != intent.instrument_id:
        raise ValueError("AQ-EXEC-RULE-INSTRUMENT-MISMATCH")
    if rules.available_at > decision_time:
        raise ValueError("AQ-EXEC-RULE-FUTURE")
    if decision_time > rules.valid_until:
        raise ValueError("AQ-EXEC-RULE-STALE")
    if rules.trading_status is TradingStatus.HALTED:
        raise ValueError("AQ-EXEC-INSTRUMENT-HALTED")
    if rules.trading_status is TradingStatus.CLOSE_ONLY and not intent.reduce_only:
        raise ValueError("AQ-EXEC-INSTRUMENT-CLOSE-ONLY")
    if intent.order_type not in rules.supported_order_types:
        raise ValueError("AQ-EXEC-ORDER-TYPE-UNSUPPORTED")
    quantity_amount = quantize_increment(
        intent.quantity.amount, rules.quantity_step, RoundingMode.DOWN
    )
    if reject_precision_change and quantity_amount != intent.quantity.amount:
        raise ValueError("AQ-EXEC-ILLEGAL-QUANTITY-PRECISION")
    if quantity_amount < rules.minimum_quantity or quantity_amount > rules.maximum_quantity:
        raise ValueError("AQ-EXEC-QUANTITY-OUT-OF-RANGE")
    quantity = Quantity(amount=quantity_amount, asset_id=intent.quantity.asset_id)
    selected_price = intent.limit_price
    if selected_price is not None:
        price_amount = quantize_increment(
            selected_price.amount, rules.price_tick, RoundingMode.DOWN
        )
        if reject_precision_change and price_amount != selected_price.amount:
            raise ValueError("AQ-EXEC-ILLEGAL-PRICE-PRECISION")
        selected_price = selected_price.model_copy(update={"amount": price_amount})
    economic_price = selected_price or reference_price
    if (
        economic_price.base_asset_id != reference_price.base_asset_id
        or economic_price.quote_asset_id != reference_price.quote_asset_id
    ):
        raise ValueError("AQ-EXEC-PRICE-UNIT-MISMATCH")
    notional = quantity.amount * economic_price.amount
    if notional < rules.minimum_notional:
        raise ValueError("AQ-EXEC-MINIMUM-NOTIONAL")
    return QuantizedOrderValues(
        quantity=quantity,
        limit_price=selected_price,
        reference_price=reference_price,
        notional=notional,
        rule_version=rules.rule_version,
    )
