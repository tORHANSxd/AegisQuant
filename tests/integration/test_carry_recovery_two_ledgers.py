from datetime import timedelta
from decimal import Decimal

from aegisquant.domain.execution import OrderSide, TimeInForce
from aegisquant.portfolio.multileg_allocator import CarryLegState, recover_carry_legs
from tests.p06.helpers import (
    NOW,
    VENUE,
    bars,
    engine,
    order,
    perp_bars,
    perp_instrument,
    perp_order,
    run_spec,
    spot_instrument,
    zero_cost_policy,
)


def test_partial_second_leg_recovery_flattens_both_cash_funded_ledgers() -> None:
    policy = zero_cost_policy()
    spot_events = bars(4, volume="100")
    perp_events = tuple(
        b.model_copy(update={"volume": Decimal("4") if i == 1 else Decimal("100")})
        for i, b in enumerate(perp_bars())
    )
    spot = spot_instrument()
    perp = perp_instrument()
    spot_entry = order(sequence=1, side=OrderSide.BUY, quantity="10")
    perp_entry = perp_order(
        sequence=1, side=OrderSide.SELL, quantity="10", submitted_at=NOW + timedelta(microseconds=1)
    ).model_copy(update={"time_in_force": TimeInForce.IMMEDIATE_OR_CANCEL})
    before = run_spec(end_time=NOW + timedelta(seconds=1))
    spot_first = engine(policy).run(
        spec=before, instrument=spot, market_events=spot_events, orders=(spot_entry,)
    )
    perp_first = engine(policy).run(
        spec=before, instrument=perp, market_events=perp_events, orders=(perp_entry,)
    )
    assert spot_first.positions[-1].quantity == 10
    assert perp_first.positions[-1].quantity == -4
    state = CarryLegState(
        group_id="two-ledgers",
        created_at=NOW,
        observed_at=NOW + timedelta(seconds=1, milliseconds=500),
        spot_filled=spot_first.positions[-1].quantity,
        perp_contracts_filled=-perp_first.positions[-1].quantity,
        contract_multiplier=Decimal("1"),
        target_base_quantity=Decimal("10"),
        reference_spot_price=Decimal("100"),
        spot_instrument_id=spot.instrument_id,
        perp_instrument_id=perp.instrument_id,
        spot_venue_id=VENUE,
        perp_venue_id=VENUE,
        base_asset_id=spot.base_asset_id,
        perp_quantity_asset_id=perp.quantity_asset_id,
        failed_leg_observed=True,
    )
    recovery = recover_carry_legs(state)
    assert recovery.cancel_unfilled_legs
    for instrument, events, entry in (
        (spot, spot_events, spot_entry),
        (perp, perp_events, perp_entry),
    ):
        exits = tuple(
            o for o in recovery.reduce_only_orders if o.instrument_id == instrument.instrument_id
        )
        result = engine(policy).run(
            spec=run_spec(), instrument=instrument, market_events=events, orders=(entry, *exits)
        )
        assert result.positions[-1].quantity == 0
        assert result.equity_curve[-1].cash > 0
        assert abs(result.cost_identity_residual) < result.cost_identity_tolerance
        assert result.fills[-1].event_time > state.observed_at
