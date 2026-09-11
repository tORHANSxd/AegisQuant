"""Signed non-Live release manifests and fail-safe rollback decisions."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
COMMIT: Final = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER: Final = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ReleaseEnvironment(StrEnum):
    PAPER = "PAPER"
    TESTNET = "TESTNET"


class RuntimePosture(StrEnum):
    HALTED = "HALTED"
    REDUCE_ONLY = "REDUCE_ONLY"
    PAPER_ACTIVE = "PAPER_ACTIVE"
    TESTNET_ACTIVE = "TESTNET_ACTIVE"


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    release_id: str
    environment: ReleaseEnvironment
    git_commit: str
    artifact_sha256: str
    dependency_lock_sha256: str
    created_at: datetime
    expires_at: datetime
    live_trading: bool = False

    def __post_init__(self) -> None:
        created = _utc(self.created_at, "created_at")
        expires = _utc(self.expires_at, "expires_at")
        if IDENTIFIER.fullmatch(self.release_id) is None:
            raise ValueError("release_id must be a bounded identifier")
        if COMMIT.fullmatch(self.git_commit) is None:
            raise ValueError("git_commit must be a full lowercase SHA-1")
        if (
            SHA256.fullmatch(self.artifact_sha256) is None
            or SHA256.fullmatch(self.dependency_lock_sha256) is None
        ):
            raise ValueError("release hashes must be SHA-256")
        if not created < expires <= created + timedelta(hours=24):
            raise ValueError("release manifest must expire within 24 hours")
        if self.live_trading:
            raise ValueError("AQ-SECURITY-LIVE-LOCKED: release cannot enable Live")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)

    def canonical_bytes(self) -> bytes:
        payload = asdict(self)
        payload["environment"] = self.environment.value
        payload["created_at"] = self.created_at.isoformat().replace("+00:00", "Z")
        payload["expires_at"] = self.expires_at.isoformat().replace("+00:00", "Z")
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SignedRelease:
    manifest: ReleaseManifest
    public_key_base64: str
    signature_base64: str


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    manifest_sha256: str
    approver: str
    approved_at: datetime
    public_key_base64: str
    signature_base64: str

    def approval_bytes(self) -> bytes:
        approved = _utc(self.approved_at, "approved_at")
        return json.dumps(
            {
                "manifest_sha256": self.manifest_sha256,
                "approver": self.approver,
                "approved_at": approved.isoformat().replace("+00:00", "Z"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()


@dataclass(frozen=True, slots=True)
class DeploymentDecision:
    allowed: bool
    posture: RuntimePosture
    reasons: tuple[str, ...]
    manual_resume_required: bool


def _public_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes_raw()


def sign_release(manifest: ReleaseManifest, private_key: Ed25519PrivateKey) -> SignedRelease:
    signature = private_key.sign(manifest.canonical_bytes())
    return SignedRelease(
        manifest=manifest,
        public_key_base64=base64.b64encode(_public_bytes(private_key.public_key())).decode("ascii"),
        signature_base64=base64.b64encode(signature).decode("ascii"),
    )


def approve_release(
    manifest: ReleaseManifest,
    *,
    approver: str,
    approved_at: datetime,
    private_key: Ed25519PrivateKey,
) -> ApprovalRecord:
    if IDENTIFIER.fullmatch(approver) is None:
        raise ValueError("approver must be a bounded identity")
    public = base64.b64encode(_public_bytes(private_key.public_key())).decode("ascii")
    unsigned = ApprovalRecord(
        manifest.sha256, approver, _utc(approved_at, "approved_at"), public, ""
    )
    signature = private_key.sign(unsigned.approval_bytes())
    return ApprovalRecord(
        manifest_sha256=unsigned.manifest_sha256,
        approver=unsigned.approver,
        approved_at=unsigned.approved_at,
        public_key_base64=public,
        signature_base64=base64.b64encode(signature).decode("ascii"),
    )


def _verify_release(signed: SignedRelease) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(signed.public_key_base64, validate=True)
        )
        key.verify(
            base64.b64decode(signed.signature_base64, validate=True),
            signed.manifest.canonical_bytes(),
        )
    except (ValueError, TypeError):
        return False
    return True


def _verify_approval(approval: ApprovalRecord, manifest: ReleaseManifest) -> bool:
    if approval.manifest_sha256 != manifest.sha256:
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(approval.public_key_base64, validate=True)
        )
        key.verify(
            base64.b64decode(approval.signature_base64, validate=True),
            approval.approval_bytes(),
        )
    except (ValueError, TypeError):
        return False
    return True


def deployment_gate(
    signed: SignedRelease,
    approval: ApprovalRecord,
    *,
    now: datetime,
    migrations_ok: bool,
    smoke_tests_ok: bool,
    reconciliation_ok: bool,
) -> DeploymentDecision:
    """Allow only a signed, separately approved, healthy Paper/Testnet release."""
    reasons: list[str] = []
    current = _utc(now, "now")
    if not _verify_release(signed):
        reasons.append("release_signature_invalid")
    if not _verify_approval(approval, signed.manifest):
        reasons.append("approval_invalid")
    if approval.public_key_base64 == signed.public_key_base64:
        reasons.append("approval_not_independent")
    if current >= signed.manifest.expires_at:
        reasons.append("manifest_expired")
    if approval.approved_at < signed.manifest.created_at or approval.approved_at > current:
        reasons.append("approval_time_invalid")
    if not migrations_ok:
        reasons.append("migration_failed")
    if not smoke_tests_ok:
        reasons.append("smoke_tests_failed")
    if not reconciliation_ok:
        reasons.append("reconciliation_failed")
    if reasons:
        return DeploymentDecision(False, RuntimePosture.HALTED, tuple(reasons), True)
    posture = (
        RuntimePosture.PAPER_ACTIVE
        if signed.manifest.environment is ReleaseEnvironment.PAPER
        else RuntimePosture.TESTNET_ACTIVE
    )
    return DeploymentDecision(True, posture, (), False)


def rollback_after_failure(previous_release_id: str | None) -> DeploymentDecision:
    """Select a prior artifact but require manual validation before any resume."""
    reason = (
        "rollback_selected_manual_resume_required"
        if previous_release_id is not None
        else "no_verified_rollback_artifact"
    )
    return DeploymentDecision(False, RuntimePosture.HALTED, (reason,), True)
