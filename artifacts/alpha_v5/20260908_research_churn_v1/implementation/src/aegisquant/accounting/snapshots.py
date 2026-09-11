"""In-memory Ed25519 signing and verification for immutable daily ledger snapshots."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from aegisquant.accounting.ledger import ZERO_HASH, LedgerEngine
from aegisquant.accounting.models import DailyLedgerSnapshot, LedgerSnapshotVerification
from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256
from aegisquant.domain.identifiers import LedgerSnapshotId
from aegisquant.domain.time import ensure_utc


def _payload(
    *,
    snapshot_date: date,
    created_at: datetime,
    policy_version: str,
    ledger_entry_count: int,
    last_event_hash: str,
    ledger_state_hash: str,
    previous_snapshot_hash: str,
) -> dict[str, object]:
    return {
        "snapshot_date": snapshot_date.isoformat(),
        "created_at": ensure_utc(created_at).isoformat(),
        "policy_version": policy_version,
        "ledger_entry_count": ledger_entry_count,
        "last_event_hash": last_event_hash,
        "ledger_state_hash": ledger_state_hash,
        "previous_snapshot_hash": previous_snapshot_hash,
        "signature_algorithm": "Ed25519",
    }


@dataclass(frozen=True, slots=True)
class Ed25519SnapshotSigner:
    """Injected ephemeral signer; this type never exports or persists private key bytes."""

    _private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> Ed25519SnapshotSigner:
        return cls(Ed25519PrivateKey.generate())

    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)


def create_daily_snapshot(
    *,
    engine: LedgerEngine,
    signer: Ed25519SnapshotSigner,
    snapshot_date: date,
    created_at: datetime,
    previous_snapshot: DailyLedgerSnapshot | None = None,
) -> DailyLedgerSnapshot:
    created_at = ensure_utc(created_at)
    if created_at.date() != snapshot_date:
        raise ValueError("daily ledger snapshot date must match UTC creation date")
    state = engine.state_digest()
    previous_hash = (
        str(previous_snapshot.ledger_snapshot_id) if previous_snapshot is not None else ZERO_HASH
    )
    payload = _payload(
        snapshot_date=snapshot_date,
        created_at=created_at,
        policy_version=engine.policy.policy_version,
        ledger_entry_count=state.entry_count,
        last_event_hash=state.last_event_hash,
        ledger_state_hash=state.state_hash,
        previous_snapshot_hash=previous_hash,
    )
    payload_bytes = canonical_json_bytes(payload)
    payload_hash = canonical_sha256(payload)
    signature = signer.sign(payload_bytes)
    public_key = signer.public_key_bytes()
    identity = {
        "payload_hash": payload_hash,
        "public_key_base64": base64.b64encode(public_key).decode("ascii"),
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    return DailyLedgerSnapshot(
        ledger_snapshot_id=LedgerSnapshotId(canonical_sha256(identity)),
        snapshot_date=snapshot_date,
        created_at=created_at,
        policy_version=engine.policy.policy_version,
        ledger_entry_count=state.entry_count,
        last_event_hash=state.last_event_hash,
        ledger_state_hash=state.state_hash,
        previous_snapshot_hash=previous_hash,
        payload_hash=payload_hash,
        public_key_base64=identity["public_key_base64"],
        signature_base64=identity["signature_base64"],
    )


def verify_daily_snapshot(snapshot: DailyLedgerSnapshot) -> bool:
    payload = _payload(
        snapshot_date=snapshot.snapshot_date,
        created_at=snapshot.created_at,
        policy_version=snapshot.policy_version,
        ledger_entry_count=snapshot.ledger_entry_count,
        last_event_hash=snapshot.last_event_hash,
        ledger_state_hash=snapshot.ledger_state_hash,
        previous_snapshot_hash=snapshot.previous_snapshot_hash,
    )
    if canonical_sha256(payload) != snapshot.payload_hash:
        return False
    identity = {
        "payload_hash": snapshot.payload_hash,
        "public_key_base64": snapshot.public_key_base64,
        "signature_base64": snapshot.signature_base64,
    }
    if canonical_sha256(identity) != str(snapshot.ledger_snapshot_id):
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(snapshot.public_key_base64, validate=True)
        )
        public_key.verify(
            base64.b64decode(snapshot.signature_base64, validate=True),
            canonical_json_bytes(payload),
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def verify_snapshot_rebuild(
    *, engine: LedgerEngine, snapshot: DailyLedgerSnapshot, verified_at: datetime
) -> LedgerSnapshotVerification:
    rebuilt = engine.rebuild().state_digest()
    return LedgerSnapshotVerification(
        ledger_snapshot_id=snapshot.ledger_snapshot_id,
        verified_at=ensure_utc(verified_at),
        signature_valid=verify_daily_snapshot(snapshot),
        rebuild_matches=(
            rebuilt.entry_count == snapshot.ledger_entry_count
            and rebuilt.last_event_hash == snapshot.last_event_hash
            and rebuilt.state_hash == snapshot.ledger_state_hash
        ),
    )
