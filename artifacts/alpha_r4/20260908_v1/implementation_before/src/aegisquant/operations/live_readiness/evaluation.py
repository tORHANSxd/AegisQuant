"""Fail-closed P18 Go/No-Go, manifest integrity, and Live-lock evaluation."""

from __future__ import annotations

import base64
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from aegisquant.operations.live_readiness.models import (
    CanaryReleaseManifest,
    GateStatus,
    ReadinessDecision,
    ReadinessGate,
    ReadinessReview,
    SignedManifestEnvelope,
)


def build_readiness_review(
    gates: tuple[ReadinessGate, ...],
    *,
    live_trading_locked: bool,
    manual_unlock_received: bool,
) -> ReadinessReview:
    """Return GO only when every hard gate passes; never grant order capability."""
    if not gates or len({item.gate_id for item in gates}) != len(gates):
        raise ValueError("readiness review requires unique gates")
    hard = tuple(item for item in gates if item.hard)
    if not hard:
        raise ValueError("readiness review requires hard gates")
    passed = sum(item.status is GateStatus.PASSED for item in hard)
    failed = sum(item.status is GateStatus.FAILED for item in hard)
    blocked = sum(item.status is GateStatus.BLOCKED_EXTERNAL_INPUT for item in hard)
    hard_passed = passed == len(hard) and live_trading_locked
    blocking = tuple(
        sorted(
            {
                code
                for gate in hard
                if gate.status is not GateStatus.PASSED
                for code in gate.reason_codes
            }
            | ({"AQ-P18-LIVE-LOCK-VIOLATION"} if not live_trading_locked else set())
        )
    )
    return ReadinessReview(
        decision=ReadinessDecision.GO if hard_passed else ReadinessDecision.NO_GO,
        gates=gates,
        hard_gate_count=len(hard),
        passed_hard_gate_count=passed,
        failed_hard_gate_count=failed,
        blocked_hard_gate_count=blocked,
        blocking_reason_codes=blocking,
        weighted_score_used=False,
        live_trading_locked=live_trading_locked,
        manual_unlock_received=manual_unlock_received,
        real_order_capability=False,
    )


def p18_real_order_capability(*, live_trading_locked: bool, manual_unlock_received: bool) -> bool:
    """P18 never implements the separate user-authorized Live unlock flow."""
    if live_trading_locked or not manual_unlock_received:
        return False
    raise PermissionError("AQ-P18-SEPARATE-LIVE-UNLOCK-NOT-IMPLEMENTED")


def canonical_manifest_bytes(manifest: CanaryReleaseManifest) -> bytes:
    return json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_manifest(
    manifest: CanaryReleaseManifest, private_key: Ed25519PrivateKey
) -> SignedManifestEnvelope:
    payload = canonical_manifest_bytes(manifest)
    digest = hashlib.sha256(payload).hexdigest()
    signature = private_key.sign(payload)
    public = private_key.public_key().public_bytes_raw()
    envelope = SignedManifestEnvelope(
        manifest=manifest,
        manifest_sha256=digest,
        public_key_base64=base64.b64encode(public).decode("ascii"),
        signature_base64=base64.b64encode(signature).decode("ascii"),
        signature_verified=True,
        signature_purpose="EVIDENCE_INTEGRITY_ONLY",
        private_key_persisted=False,
        authorization_capability=False,
    )
    if not verify_manifest(envelope):
        raise RuntimeError("newly created P18 evidence signature did not verify")
    return envelope


def verify_manifest(envelope: SignedManifestEnvelope) -> bool:
    payload = canonical_manifest_bytes(envelope.manifest)
    if hashlib.sha256(payload).hexdigest() != envelope.manifest_sha256:
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(envelope.public_key_base64, validate=True)
        )
        key.verify(base64.b64decode(envelope.signature_base64, validate=True), payload)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True
