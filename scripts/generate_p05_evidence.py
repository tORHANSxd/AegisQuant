"""Generate deterministic P05 accounting, reconciliation, snapshot, and replay evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from aegisquant.accounting.ledger import AccountingPolicy, LedgerEngine, calculate_contract_pnl
from aegisquant.accounting.models import (
    AccountingInstrument,
    CashflowDirection,
    CashflowEvent,
    CashflowType,
    LedgerRecord,
    ReconciliationMode,
    SettlementEvent,
    VenueAccountSnapshot,
)
from aegisquant.accounting.reconciliation import reconcile_account_snapshots
from aegisquant.accounting.snapshots import (
    Ed25519SnapshotSigner,
    create_daily_snapshot,
    verify_daily_snapshot,
    verify_snapshot_rebuild,
)
from aegisquant.data.market import ContractForm, InstrumentType
from aegisquant.domain.accounting import LotSide, PostingSide
from aegisquant.domain.execution import Fill, OrderSide
from aegisquant.domain.identifiers import (
    ArtifactId,
    AssetId,
    ClientOrderId,
    FillId,
    IdempotencyKey,
    InstrumentId,
    OrderIntentId,
    VenueOrderId,
)
from aegisquant.domain.values import Money, Price, Quantity

EVIDENCE_TIME: Final = "2026-09-01T08:00:00Z"
NOW: Final = datetime(2026, 9, 1, 8, tzinfo=UTC)
BTC: Final = AssetId("BTC")
USDT: Final = AssetId("USDT")
USD: Final = AssetId("USD")


def engine(root: Path) -> LedgerEngine:
    policy = AccountingPolicy.from_yaml(root / "configs/accounting/accounting_policy_v1.yaml")
    return LedgerEngine(policy=policy, effective_from=NOW)


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
) -> Fill:
    instant = NOW + timedelta(seconds=sequence)
    return Fill(
        fill_id=FillId(f"evidence-fill-{sequence}"),
        venue_order_id=VenueOrderId(f"evidence-venue-order-{sequence}"),
        client_order_id=ClientOrderId(f"evidence-client-order-{sequence}"),
        order_intent_id=OrderIntentId(f"evidence-intent-{sequence}"),
        instrument_id=instrument.instrument_id,
        side=side,
        quantity=Quantity(amount=Decimal(quantity), asset_id=instrument.quantity_asset_id),
        price=Price(
            amount=Decimal(price),
            base_asset_id=instrument.base_asset_id,
            quote_asset_id=instrument.quote_asset_id,
        ),
        fee=Money(amount=Decimal("0"), asset_id=instrument.settlement_asset_id),
        event_time=instant,
        available_time=instant + timedelta(milliseconds=1),
        ingest_time=instant + timedelta(milliseconds=2),
        idempotency_key=IdempotencyKey(f"evidence-fill-key-{sequence}"),
    )


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _balanced(record: LedgerRecord) -> bool:
    journal = record.journal_entry
    totals: dict[str, Decimal] = {}
    for posting in journal.postings:
        sign = Decimal("1") if posting.side is PostingSide.DEBIT else Decimal("-1")
        asset = str(posting.amount.asset_id)
        totals[asset] = totals.get(asset, Decimal("0")) + sign * posting.amount.amount
    return bool(totals) and all(amount == 0 for amount in totals.values())


def _cashflow(
    *, sequence: int, cashflow_type: CashflowType, direction: CashflowDirection, amount: str
) -> CashflowEvent:
    instant = NOW + timedelta(minutes=sequence)
    return CashflowEvent(
        event_id=ArtifactId(f"evidence-cashflow-{sequence}"),
        venue="SIM",
        cashflow_type=cashflow_type,
        direction=direction,
        amount=Money(amount=Decimal(amount), asset_id=USDT),
        event_time=instant,
        recorded_at=instant + timedelta(milliseconds=1),
        idempotency_key=IdempotencyKey(f"evidence-cashflow-key-{sequence}"),
        reference=f"P05 evidence cashflow {sequence}",
    )


def generate(root: Path) -> dict[Path, bytes]:
    spot = spot_instrument()
    ledger = engine(root)
    ledger.process_fill(fill(spot, sequence=1, side=OrderSide.BUY, quantity="1", price="100"), spot)
    ledger.process_fill(fill(spot, sequence=2, side=OrderSide.BUY, quantity="2", price="110"), spot)
    closing_fill = fill(spot, sequence=3, side=OrderSide.SELL, quantity="1.5", price="120")
    closing = ledger.process_fill(closing_fill, spot)
    replay = ledger.process_fill(closing_fill, spot)
    float_rejected = False
    try:
        Money(amount=1.0, asset_id=USDT)  # type: ignore[arg-type]
    except (TypeError, ValidationError):
        float_rejected = True

    accounting = {
        "schema_version": "1.0.0",
        "phase": "P05",
        "generated_at_utc": EVIDENCE_TIME,
        "fixture_only": True,
        "real_account_access_performed": False,
        "credentials_requested_or_stored": False,
        "live_trading_locked": True,
        "policy_version": ledger.policy.policy_version,
        "chart_version": ledger.chart.version,
        "template_version": ledger.policy.template_version,
        "entry_templates": sorted(ledger.templates),
        "entry_count": len(ledger.records),
        "all_entries_balanced_by_asset": all(_balanced(record) for record in ledger.records),
        "fill_replay_inserted": replay.inserted,
        "float_rejected": float_rejected,
        "database_revision": "20260901_0002",
    }

    inverse = inverse_instrument()
    inverse_pnl = calculate_contract_pnl(
        side=LotSide.LONG,
        quantity=Decimal("100"),
        entry_price=Decimal("10000"),
        exit_price=Decimal("11000"),
        instrument=inverse,
    )
    future = linear_instrument(future=True)
    settlement_ledger = engine(root)
    settlement_ledger.process_fill(
        fill(future, sequence=10, side=OrderSide.BUY, quantity="3", price="100"),
        future,
    )
    settlement = settlement_ledger.process_settlement(
        SettlementEvent(
            event_id=ArtifactId("evidence-settlement"),
            instrument=future,
            settlement_price=Decimal("120"),
            event_time=NOW + timedelta(hours=1),
            available_time=NOW + timedelta(hours=1, milliseconds=1),
            recorded_at=NOW + timedelta(hours=1, milliseconds=2),
            idempotency_key=IdempotencyKey("evidence-settlement-key"),
            reference="P05 fixture dated future settlement",
        )
    )
    cash_ledger = engine(root)
    for event in (
        _cashflow(
            sequence=1,
            cashflow_type=CashflowType.EXTERNAL_TRANSFER_IN,
            direction=CashflowDirection.INFLOW,
            amount="1000",
        ),
        _cashflow(
            sequence=2,
            cashflow_type=CashflowType.FUNDING,
            direction=CashflowDirection.OUTFLOW,
            amount="4",
        ),
        _cashflow(
            sequence=3,
            cashflow_type=CashflowType.BORROW,
            direction=CashflowDirection.INFLOW,
            amount="100",
        ),
        _cashflow(
            sequence=4,
            cashflow_type=CashflowType.BORROW_INTEREST,
            direction=CashflowDirection.OUTFLOW,
            amount="2",
        ),
    ):
        cash_ledger.process_cashflow(event)
    golden = {
        "schema_version": "1.0.0",
        "phase": "P05",
        "generated_at_utc": EVIDENCE_TIME,
        "spot_fifo": {
            "realized_pnl": str(closing.applied_fill.realized_pnl.amount),
            "asset_id": str(closing.applied_fill.realized_pnl.asset_id),
            "remaining_lots": [
                {
                    "entry_price": str(lot.entry_price),
                    "remaining_quantity": str(lot.remaining_quantity),
                    "side": lot.side.value,
                }
                for lot in ledger.open_lots()
            ],
        },
        "inverse_contract": {
            "realized_pnl": str(inverse_pnl.amount),
            "settlement_asset_id": str(inverse_pnl.asset_id),
        },
        "dated_future_settlement": {
            "realized_pnl": str(
                sum(change.realized_pnl.amount for change in settlement.record.lot_changes)
            ),
            "remaining_lots": len(settlement_ledger.open_lots()),
        },
        "cashflow_entry_count": len(cash_ledger.records),
        "cashflow_balanced": all(_balanced(record) for record in cash_ledger.records),
    }

    fixture = cast(
        dict[str, object],
        json.loads(
            (root / "tests/fixtures/p05/simulated_exchange.json").read_text(encoding="utf-8")
        ),
    )
    local = VenueAccountSnapshot.model_validate_json(json.dumps(fixture["local"]))
    matching = VenueAccountSnapshot.model_validate_json(json.dumps(fixture["matching_venue"]))
    drifted = VenueAccountSnapshot.model_validate_json(json.dumps(fixture["drifted_venue"]))
    cases = {
        mode.value: reconcile_account_snapshots(
            local=local,
            venue=matching if mode is ReconciliationMode.STARTUP else drifted,
            mode=mode,
            opened_at=NOW,
            tolerance=Decimal("0.000001"),
        )
        for mode in ReconciliationMode
    }
    reconciliation = {
        "schema_version": "1.0.0",
        "phase": "P05",
        "generated_at_utc": EVIDENCE_TIME,
        "fixture_only": True,
        "local_snapshot_unchanged": True,
        "silent_adjustment_performed": False,
        "cases": {
            name: {
                "case_id": str(case.reconciliation_case_id),
                "status": case.status.value,
                "new_orders_allowed": case.new_orders_allowed,
                "difference_types": sorted(
                    {item.difference_type.value for item in case.differences}
                ),
                "difference_count": len(case.differences),
            }
            for name, case in cases.items()
        },
    }

    seed = hashlib.sha256(b"AegisQuant P05 fixture-only snapshot signing key").digest()
    signer = Ed25519SnapshotSigner(Ed25519PrivateKey.from_private_bytes(seed))
    signed = create_daily_snapshot(
        engine=ledger,
        signer=signer,
        snapshot_date=date(2026, 9, 1),
        created_at=NOW,
    )
    verification = verify_snapshot_rebuild(
        engine=ledger, snapshot=signed, verified_at=NOW + timedelta(seconds=1)
    )
    snapshot_evidence = {
        "schema_version": "1.0.0",
        "phase": "P05",
        "generated_at_utc": EVIDENCE_TIME,
        "fixture_only_key": True,
        "private_key_persisted": False,
        "signature_algorithm": signed.signature_algorithm,
        "ledger_snapshot_id": str(signed.ledger_snapshot_id),
        "payload_hash": signed.payload_hash,
        "public_key_base64": signed.public_key_base64,
        "signature_base64": signed.signature_base64,
        "signature_valid": verify_daily_snapshot(signed),
        "rebuild_matches": verification.rebuild_matches,
    }

    state = ledger.state_digest()
    rebuilt = ledger.rebuild().state_digest()
    replay_evidence = {
        "schema_version": "1.0.0",
        "phase": "P05",
        "generated_at_utc": EVIDENCE_TIME,
        "source_entry_count": state.entry_count,
        "rebuilt_entry_count": rebuilt.entry_count,
        "source_last_event_hash": state.last_event_hash,
        "rebuilt_last_event_hash": rebuilt.last_event_hash,
        "source_state_hash": state.state_hash,
        "rebuilt_state_hash": rebuilt.state_hash,
        "hashes_match": state == rebuilt,
    }
    return {
        root / "reports/data/P05_ACCOUNTING_EVIDENCE.json": _json_bytes(accounting),
        root / "reports/data/P05_GOLDEN_RESULTS.json": _json_bytes(golden),
        root / "reports/data/P05_RECONCILIATION_EVIDENCE.json": _json_bytes(reconciliation),
        root / "reports/data/P05_SNAPSHOT_EVIDENCE.json": _json_bytes(snapshot_evidence),
        root / "reports/data/P05_REPLAY_EVIDENCE.json": _json_bytes(replay_evidence),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    outputs = generate(root)
    if args.check:
        stale = [
            path for path, raw in outputs.items() if not path.is_file() or path.read_bytes() != raw
        ]
        if stale:
            raise SystemExit(f"P05 evidence is stale: {[path.as_posix() for path in stale]}")
        print(f"verified {len(outputs)} P05 evidence artifacts")
        return 0
    for path, raw in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    print(f"wrote {len(outputs)} P05 evidence artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
