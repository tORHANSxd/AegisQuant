"""Deterministic accounting instruments and events for P05 tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aegisquant.accounting.ledger import AccountingPolicy, LedgerEngine
from aegisquant.accounting.models import AccountingInstrument
from aegisquant.data.market import ContractForm, InstrumentType
from aegisquant.domain.execution import Fill, OrderSide
from aegisquant.domain.identifiers import (
    AssetId,
    ClientOrderId,
    FillId,
    IdempotencyKey,
    InstrumentId,
    OrderIntentId,
    VenueOrderId,
)
from aegisquant.domain.values import Money, Price, Quantity

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)
BTC = AssetId("BTC")
USDT = AssetId("USDT")
USD = AssetId("USD")


def accounting_policy(project_root: Path) -> AccountingPolicy:
    return AccountingPolicy.from_yaml(project_root / "configs/accounting/accounting_policy_v1.yaml")


def engine(project_root: Path) -> LedgerEngine:
    return LedgerEngine(policy=accounting_policy(project_root), effective_from=NOW)


def spot_instrument() -> AccountingInstrument:
    return AccountingInstrument(
        instrument_id=InstrumentId("SIM:SPOT:BTCUSDT"),
        venue="SIM",
        base_asset_id=BTC,
        quote_asset_id=USDT,
        settlement_asset_id=USDT,
        quantity_asset_id=BTC,
        instrument_type=InstrumentType.SPOT,
        contract_form=ContractForm.SPOT,
        contract_multiplier=Decimal("1"),
    )


def linear_instrument(*, future: bool = False) -> AccountingInstrument:
    name = "SIM:FUTURE:BTCUSDT" if future else "SIM:PERP:BTCUSDT"
    return AccountingInstrument(
        instrument_id=InstrumentId(name),
        venue="SIM",
        base_asset_id=BTC,
        quote_asset_id=USDT,
        settlement_asset_id=USDT,
        quantity_asset_id=AssetId(f"CONTRACT:{name}"),
        instrument_type=InstrumentType.FUTURE if future else InstrumentType.PERPETUAL,
        contract_form=ContractForm.LINEAR,
        contract_multiplier=Decimal("1"),
    )


def inverse_instrument() -> AccountingInstrument:
    name = "SIM:PERP:BTCUSD-INVERSE"
    return AccountingInstrument(
        instrument_id=InstrumentId(name),
        venue="SIM",
        base_asset_id=BTC,
        quote_asset_id=USD,
        settlement_asset_id=BTC,
        quantity_asset_id=AssetId(f"CONTRACT:{name}"),
        instrument_type=InstrumentType.PERPETUAL,
        contract_form=ContractForm.INVERSE,
        contract_multiplier=Decimal("1"),
    )


def fill(
    instrument: AccountingInstrument,
    *,
    sequence: int,
    side: OrderSide,
    quantity: str,
    price: str,
    fee: str = "0",
    fee_asset: AssetId | None = None,
) -> Fill:
    event_time = NOW + timedelta(seconds=sequence)
    return Fill(
        fill_id=FillId(f"fill-{sequence}"),
        venue_order_id=VenueOrderId(f"venue-order-{sequence}"),
        client_order_id=ClientOrderId(f"client-order-{sequence}"),
        order_intent_id=OrderIntentId(f"intent-{sequence}"),
        instrument_id=instrument.instrument_id,
        side=side,
        quantity=Quantity(amount=Decimal(quantity), asset_id=instrument.quantity_asset_id),
        price=Price(
            amount=Decimal(price),
            base_asset_id=instrument.base_asset_id,
            quote_asset_id=instrument.quote_asset_id,
        ),
        fee=Money(
            amount=Decimal(fee),
            asset_id=fee_asset or instrument.settlement_asset_id,
        ),
        event_time=event_time,
        available_time=event_time + timedelta(milliseconds=1),
        ingest_time=event_time + timedelta(milliseconds=2),
        idempotency_key=IdempotencyKey(f"fill-key-{sequence}"),
    )
