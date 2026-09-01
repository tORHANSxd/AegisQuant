"""Ed25519 daily ledger snapshot and event-rebuild contracts."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from aegisquant.accounting.snapshots import (
    Ed25519SnapshotSigner,
    create_daily_snapshot,
    verify_daily_snapshot,
    verify_snapshot_rebuild,
)
from aegisquant.domain.execution import OrderSide
from tests.p05.helpers import NOW, engine, fill, linear_instrument


def test_daily_snapshot_is_signed_chained_and_rebuildable(project_root: Path) -> None:
    spec = linear_instrument()
    ledger = engine(project_root)
    ledger.process_fill(fill(spec, sequence=1, side=OrderSide.BUY, quantity="2", price="100"), spec)
    signer = Ed25519SnapshotSigner.generate()
    first = create_daily_snapshot(
        engine=ledger,
        signer=signer,
        snapshot_date=date(2026, 9, 1),
        created_at=NOW,
    )
    repeated = create_daily_snapshot(
        engine=ledger,
        signer=signer,
        snapshot_date=date(2026, 9, 1),
        created_at=NOW,
    )
    second = create_daily_snapshot(
        engine=ledger,
        signer=signer,
        snapshot_date=date(2026, 9, 2),
        created_at=NOW + timedelta(days=1),
        previous_snapshot=first,
    )
    assert first == repeated
    assert verify_daily_snapshot(first) is True
    assert second.previous_snapshot_hash == str(first.ledger_snapshot_id)
    verification = verify_snapshot_rebuild(
        engine=ledger, snapshot=second, verified_at=NOW + timedelta(days=1, seconds=1)
    )
    assert verification.signature_valid is True
    assert verification.rebuild_matches is True
    serialized = second.model_dump(mode="json")
    assert all("private" not in key.lower() for key in serialized)


def test_tampered_snapshot_signature_is_rejected(project_root: Path) -> None:
    ledger = engine(project_root)
    signer = Ed25519SnapshotSigner.generate()
    snapshot = create_daily_snapshot(
        engine=ledger,
        signer=signer,
        snapshot_date=date(2026, 9, 1),
        created_at=NOW,
    )
    replacement = "A" if snapshot.signature_base64[0] != "A" else "B"
    tampered = snapshot.model_copy(
        update={"signature_base64": replacement + snapshot.signature_base64[1:]}
    )
    assert verify_daily_snapshot(tampered) is False
