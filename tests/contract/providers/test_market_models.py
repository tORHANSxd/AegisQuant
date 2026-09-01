from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from aegisquant.data.market import (
    CanonicalAsset,
    CanonicalExposure,
    CanonicalPair,
    ContractForm,
    ImpliedVolatilitySource,
    InstrumentType,
    UnifiedInstrument,
    Venue,
    contract_base_quantity,
    contract_pnl,
)
from aegisquant.domain.identifiers import ProviderId

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def make_instrument(
    *,
    venue: Venue,
    symbol: str,
    form: ContractForm,
    settlement_symbol: str,
    multiplier: Decimal,
) -> UnifiedInstrument:
    base = CanonicalAsset.create("BTC")
    quote = CanonicalAsset.create("USD")
    settlement = CanonicalAsset.create(settlement_symbol)
    pair = CanonicalPair.create(base, quote)
    exposure = CanonicalExposure.create(
        pair,
        settlement,
        instrument_type=InstrumentType.PERPETUAL,
        contract_form=form,
    )
    return UnifiedInstrument.create(
        provider_id=ProviderId(f"{venue.value.casefold()}_public"),
        venue=venue,
        venue_symbol=symbol,
        exposure=exposure,
        base_asset=base,
        quote_asset=quote,
        settlement_asset=settlement,
        contract_multiplier=multiplier,
        tick_size=Decimal("0.5"),
        lot_size=Decimal("1"),
        active=True,
        observed_time=NOW,
        available_time=NOW,
        iv_source=ImpliedVolatilitySource.NOT_APPLICABLE,
    )


def test_same_symbol_does_not_merge_different_economic_exposure() -> None:
    linear = make_instrument(
        venue=Venue.OKX,
        symbol="BTCUSD",
        form=ContractForm.LINEAR,
        settlement_symbol="USD",
        multiplier=Decimal("1"),
    )
    inverse = make_instrument(
        venue=Venue.DERIBIT,
        symbol="BTCUSD",
        form=ContractForm.INVERSE,
        settlement_symbol="BTC",
        multiplier=Decimal("10"),
    )
    assert linear.venue_symbol == inverse.venue_symbol
    assert linear.exposure.exposure_id != inverse.exposure.exposure_id
    assert linear.instrument_id != inverse.instrument_id


def test_asset_identity_distinguishes_network_and_contract() -> None:
    native = CanonicalAsset.create("USDT", network="ETHEREUM")
    bridged = CanonicalAsset.create(
        "USDT", network="ARBITRUM", contract_address="0x0000000000000000000000000000000000000001"
    )
    assert native.asset_id != bridged.asset_id


@given(
    contracts=st.integers(min_value=-10_000, max_value=10_000).filter(lambda value: value != 0),
    entry=st.integers(min_value=10_000, max_value=100_000),
    move=st.integers(min_value=1, max_value=10_000),
)
def test_inverse_pnl_units_and_direction(contracts: int, entry: int, move: int) -> None:
    instrument = make_instrument(
        venue=Venue.DERIBIT,
        symbol="BTC-PERPETUAL",
        form=ContractForm.INVERSE,
        settlement_symbol="BTC",
        multiplier=Decimal("10"),
    )
    signed = Decimal(contracts)
    entry_price = Decimal(entry)
    exit_price = Decimal(entry + move)
    result = contract_pnl(
        signed_contracts=signed,
        entry_price=entry_price,
        exit_price=exit_price,
        instrument=instrument,
    )
    expected = signed * Decimal("10") * (Decimal(1) / entry_price - Decimal(1) / exit_price)
    assert result.amount == expected
    assert result.settlement_asset_id == instrument.base_asset.asset_id
    assert result.unit == "base_asset"
    assert (result.amount > 0) is (contracts > 0)


def test_contract_quantity_respects_linear_and_inverse_units() -> None:
    assert contract_base_quantity(
        signed_contracts=Decimal("5"),
        price=Decimal("50000"),
        multiplier=Decimal("0.01"),
        form=ContractForm.LINEAR,
    ) == Decimal("0.05")
    assert contract_base_quantity(
        signed_contracts=Decimal("5"),
        price=Decimal("50000"),
        multiplier=Decimal("10"),
        form=ContractForm.INVERSE,
    ) == Decimal("0.001")
