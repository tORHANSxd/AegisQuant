from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisquant.operations.release import (
    ReleaseEnvironment,
    ReleaseManifest,
    RuntimePosture,
    approve_release,
    deployment_gate,
    rollback_after_failure,
    sign_release,
)


def manifest(now: datetime) -> ReleaseManifest:
    return ReleaseManifest(
        release_id="p16-paper-001",
        environment=ReleaseEnvironment.PAPER,
        git_commit="a" * 40,
        artifact_sha256="b" * 64,
        dependency_lock_sha256="c" * 64,
        created_at=now,
        expires_at=now + timedelta(hours=4),
    )


def test_independently_signed_healthy_release_can_enter_paper_only() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    release = sign_release(manifest(now), Ed25519PrivateKey.generate())
    approval = approve_release(
        release.manifest,
        approver="operator-1",
        approved_at=now + timedelta(minutes=1),
        private_key=Ed25519PrivateKey.generate(),
    )
    decision = deployment_gate(
        release,
        approval,
        now=now + timedelta(minutes=2),
        migrations_ok=True,
        smoke_tests_ok=True,
        reconciliation_ok=True,
    )
    assert decision.allowed is True
    assert decision.posture is RuntimePosture.PAPER_ACTIVE
    assert decision.manual_resume_required is False


def test_same_key_or_failed_check_keeps_release_halted() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    key = Ed25519PrivateKey.generate()
    release = sign_release(manifest(now), key)
    approval = approve_release(
        release.manifest,
        approver="operator-1",
        approved_at=now,
        private_key=key,
    )
    decision = deployment_gate(
        release,
        approval,
        now=now + timedelta(minutes=1),
        migrations_ok=True,
        smoke_tests_ok=False,
        reconciliation_ok=True,
    )
    assert decision.allowed is False
    assert decision.posture is RuntimePosture.HALTED
    assert set(decision.reasons) == {"approval_not_independent", "smoke_tests_failed"}
    assert decision.manual_resume_required is True


def test_expired_manifest_and_rollback_never_auto_resume() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    release = sign_release(manifest(now), Ed25519PrivateKey.generate())
    approval = approve_release(
        release.manifest,
        approver="operator-2",
        approved_at=now,
        private_key=Ed25519PrivateKey.generate(),
    )
    expired = deployment_gate(
        release,
        approval,
        now=now + timedelta(hours=5),
        migrations_ok=True,
        smoke_tests_ok=True,
        reconciliation_ok=True,
    )
    rollback = rollback_after_failure("p15-paper-verified")
    assert expired.posture is RuntimePosture.HALTED
    assert "manifest_expired" in expired.reasons
    assert rollback.allowed is False
    assert rollback.posture is RuntimePosture.HALTED
    assert rollback.manual_resume_required is True
