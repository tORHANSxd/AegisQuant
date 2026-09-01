"""Valuation, equity, and simulated-venue reconciliation contracts."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from aegisquant.accounting.models import (
    FxRate,
    ReconciliationDifferenceType,
    ReconciliationMode,
    ReconciliationStatus,
    SnapshotAmount,
    ValuationQuote,
    VenueAccountSnapshot,
)
from aegisquant.accounting.reconciliation import (
    reconcile_account_snapshots,
    require_reconciliation_clear,
)
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import AccountSnapshotId
from tests.p05.helpers import BTC, NOW, USDT, engine, fill, linear_instrument


def test_valuation_priority_unrealized_and_equity_are_authoritative(project_root: Path) -> None:
    spec = linear_instrument()
    ledger = engine(project_root)
    ledger.process_fill(fill(spec, sequence=1, side=OrderSide.BUY, quantity="2", price="100"), spec)
    quote = ValuationQuote(
        instrument_id=spec.instrument_id,
        as_of_time=NOW + timedelta(minutes=1),
        available_time=NOW + timedelta(minutes=1, milliseconds=1),
        mark=Decimal("120"),
        mid=Decimal("125"),
        last=Decimal("130"),
        index=Decimal("135"),
    )
    valuation = ledger.valuation_snapshot({spec.instrument_id: quote})
    assert valuation.lots[0].source.value == "MARK"
    assert valuation.lots[0].as_of_time == quote.as_of_time
    assert valuation.lots[0].available_time == quote.available_time
    assert valuation.lots[0].policy_version == quote.policy_version
    assert valuation.lots[0].unrealized_pnl.amount == Decimal("40")
    equity = ledger.equity_snapshot(
        valuation=valuation,
        reporting_asset_id=USDT,
        fx_rates={
            BTC: FxRate(
                asset_id=BTC,
                reporting_asset_id=USDT,
                rate=Decimal("120"),
                as_of_time=quote.as_of_time,
                policy_version="fx-v1",
            )
        },
    )
    assert equity.unrealized_pnl_value == Decimal("40")
    assert equity.equity == equity.balance_value + Decimal("40")


def load_simulated_snapshots(
    project_root: Path,
) -> tuple[VenueAccountSnapshot, VenueAccountSnapshot, VenueAccountSnapshot]:
    payload = cast(
        dict[str, object],
        json.loads(
            (project_root / "tests/fixtures/p05/simulated_exchange.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    encoded = {key: json.dumps(value, separators=(",", ":")) for key, value in payload.items()}
    return (
        VenueAccountSnapshot.model_validate_json(encoded["local"]),
        VenueAccountSnapshot.model_validate_json(encoded["matching_venue"]),
        VenueAccountSnapshot.model_validate_json(encoded["drifted_venue"]),
    )


def test_startup_continuous_and_reconnect_reconciliation_use_simulated_venue(
    project_root: Path,
) -> None:
    local, matching, drifted = load_simulated_snapshots(project_root)
    startup = reconcile_account_snapshots(
        local=local,
        venue=matching,
        mode=ReconciliationMode.STARTUP,
        opened_at=NOW,
    )
    assert startup.status is ReconciliationStatus.CLEAR
    assert startup.new_orders_allowed is True
    require_reconciliation_clear(startup)

    local_before = canonical_sha256(local.model_dump(mode="json"))
    continuous = reconcile_account_snapshots(
        local=local,
        venue=drifted,
        mode=ReconciliationMode.CONTINUOUS,
        opened_at=NOW,
        tolerance=Decimal("0.000001"),
    )
    assert continuous.status is ReconciliationStatus.REVIEW_REQUIRED
    assert continuous.new_orders_allowed is False
    types = {item.difference_type for item in continuous.differences}
    assert ReconciliationDifferenceType.ROUNDING in types
    assert ReconciliationDifferenceType.BALANCE_MISMATCH in types
    assert ReconciliationDifferenceType.POSITION_MISMATCH in types
    assert ReconciliationDifferenceType.UNKNOWN_ORDER in types
    assert ReconciliationDifferenceType.MISSING_LOCAL_EVENT in types
    with pytest.raises(RuntimeError, match="AQ-RECONCILIATION-BLOCKED"):
        require_reconciliation_clear(continuous)
    assert canonical_sha256(local.model_dump(mode="json")) == local_before

    reconnect = reconcile_account_snapshots(
        local=local,
        venue=drifted,
        mode=ReconciliationMode.RECONNECT,
        opened_at=NOW,
    )
    assert reconnect.status is ReconciliationStatus.HALTED
    assert reconnect.new_orders_allowed is False


def test_snapshot_duplicate_keys_and_float_tolerance_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate amount keys"):
        VenueAccountSnapshot(
            account_snapshot_id=AccountSnapshotId("duplicate-snapshot"),
            venue="SIM",
            as_of_time=NOW,
            balances=(
                SnapshotAmount(key="USDT", amount=Decimal("1")),
                SnapshotAmount(key="USDT", amount=Decimal("2")),
            ),
            positions=(),
        )
    snapshot = VenueAccountSnapshot(
        account_snapshot_id=AccountSnapshotId("same-snapshot"),
        venue="SIM",
        as_of_time=NOW,
        balances=(),
        positions=(),
    )
    with pytest.raises(TypeError, match="Decimal"):
        reconcile_account_snapshots(
            local=snapshot,
            venue=snapshot,
            mode=ReconciliationMode.STARTUP,
            opened_at=NOW,
            tolerance=0.1,  # type: ignore[arg-type]
        )


def test_duplicate_venue_events_are_classified_instead_of_discarded() -> None:
    local = VenueAccountSnapshot(
        account_snapshot_id=AccountSnapshotId("duplicate-local"),
        venue="SIM",
        as_of_time=NOW,
        balances=(),
        positions=(),
        fill_ids=("fill-1",),
    )
    venue = VenueAccountSnapshot(
        account_snapshot_id=AccountSnapshotId("duplicate-venue"),
        venue="SIM",
        as_of_time=NOW,
        balances=(),
        positions=(),
        fill_ids=("fill-1", "fill-1"),
    )
    case = reconcile_account_snapshots(
        local=local,
        venue=venue,
        mode=ReconciliationMode.CONTINUOUS,
        opened_at=NOW,
    )
    assert any(
        item.difference_type is ReconciliationDifferenceType.DUPLICATE_EVENT
        for item in case.differences
    )
