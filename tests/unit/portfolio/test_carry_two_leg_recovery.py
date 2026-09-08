from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import AssetId, InstrumentId, VenueId
from aegisquant.portfolio.multileg_allocator import (
    CarryLegState,
    allocate_carry,
    recover_carry_legs,
)


def test_two_legs_are_cash_funded_and_contract_delta_neutral() -> None:
    allocation = allocate_carry(
        capital=Decimal("10000"),
        spot_price=Decimal("100"),
        perp_price=Decimal("101"),
        contract_multiplier=Decimal("0.01"),
        spot_capacity=Decimal("1000"),
        perp_capacity_contracts=Decimal("100000"),
        spot_step=Decimal("0.01"),
        perp_step=Decimal("1"),
        minimum_leg_notional=Decimal("10"),
        maximum_base_delta=Decimal("0"),
    )
    assert allocation.spot_quantity == allocation.perp_contracts * Decimal("0.01")
    assert (
        allocation.spot_cash_reserved
        + allocation.perp_collateral_reserved
        + allocation.cost_reserve
        <= 10000
    )


def test_failed_second_leg_generates_only_reduction_and_cancellation() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = CarryLegState(
        group_id="carry-test",
        created_at=now,
        observed_at=now + timedelta(seconds=6),
        spot_filled=Decimal("1"),
        perp_contracts_filled=Decimal("0.4"),
        contract_multiplier=Decimal("1"),
        target_base_quantity=Decimal("1"),
        reference_spot_price=Decimal("100"),
        spot_instrument_id=InstrumentId("SIM:SPOT:BTCUSDT"),
        perp_instrument_id=InstrumentId("SIM:PERP:BTCUSDT"),
        spot_venue_id=VenueId("SIM"),
        perp_venue_id=VenueId("SIM"),
        base_asset_id=AssetId("BTC"),
        perp_quantity_asset_id=AssetId("CONTRACT:SIM:PERP:BTCUSDT"),
        failed_leg_observed=True,
    )
    recovery = recover_carry_legs(state)
    assert recovery.cancel_unfilled_legs
    assert [(o.side, o.quantity.amount) for o in recovery.reduce_only_orders] == [
        (OrderSide.SELL, Decimal("1")),
        (OrderSide.BUY, Decimal("0.4")),
    ]
    assert all(
        o.reduce_only and o.decision_time == state.observed_at for o in recovery.reduce_only_orders
    )
