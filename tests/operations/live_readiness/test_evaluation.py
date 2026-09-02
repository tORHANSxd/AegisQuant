"""Fail-closed P18 readiness, capital, and manifest tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from aegisquant.operations.live_readiness import (
    CanaryReleaseManifest,
    CanaryScope,
    GateStatus,
    LiveReadinessPolicy,
    ReadinessDecision,
    ReadinessGate,
    ReadinessReview,
    SelectionStatus,
    SignedManifestEnvelope,
    build_readiness_review,
    p18_real_order_capability,
    sign_manifest,
    verify_manifest,
)


def _gate(gate_id: str, status: GateStatus, *, hard: bool = True) -> ReadinessGate:
    return ReadinessGate(
        gate_id=gate_id,
        description=f"Gate {gate_id}",
        hard=hard,
        status=status,
        evidence_paths=("reports/evidence.json",),
        reason_codes=() if status is GateStatus.PASSED else (f"AQ-{gate_id.upper()}",),
    )


def _manifest(*, expires_after: timedelta = timedelta(hours=4)) -> CanaryReleaseManifest:
    created = datetime(2026, 9, 2, tzinfo=UTC)
    return CanaryReleaseManifest(
        schema_version="p18-canary-release-manifest-v1",
        release_id="p18-unit-evidence",
        source_commit="a" * 40,
        created_at_utc=created,
        expires_at_utc=created + expires_after,
        decision=ReadinessDecision.NO_GO,
        scope=CanaryScope(
            selection_status=SelectionStatus.NONE_NO_GO,
            strategy_id=None,
            account_scope_id=None,
            instrument_ids=(),
        ),
        frozen_versions={"model": "NONE", "risk": "p11"},
        frozen_artifact_sha256={"risk-policy": "b" * 64},
        live_trading_locked=True,
        user_approval_received=False,
        manual_unlock_received=False,
        releaseable=False,
    )


def test_all_hard_gates_can_reach_readiness_go_without_order_capability() -> None:
    review = build_readiness_review(
        (_gate("hard-one", GateStatus.PASSED), _gate("soft-one", GateStatus.FAILED, hard=False)),
        live_trading_locked=True,
        manual_unlock_received=False,
    )
    assert review.decision is ReadinessDecision.GO
    assert review.hard_gate_count == review.passed_hard_gate_count == 1
    assert review.failed_hard_gate_count == review.blocked_hard_gate_count == 0
    assert review.blocking_reason_codes == ()
    assert review.weighted_score_used is False
    assert review.live_trading_locked is True
    assert review.real_order_capability is False


def test_one_blocked_hard_gate_forces_no_go_without_weighted_override() -> None:
    review = build_readiness_review(
        (
            _gate("hard-pass", GateStatus.PASSED),
            _gate("hard-block", GateStatus.BLOCKED_EXTERNAL_INPUT),
            _gate("soft-pass", GateStatus.PASSED, hard=False),
        ),
        live_trading_locked=True,
        manual_unlock_received=False,
    )
    assert review.decision is ReadinessDecision.NO_GO
    assert review.passed_hard_gate_count == 1
    assert review.blocked_hard_gate_count == 1
    assert review.blocking_reason_codes == ("AQ-HARD-BLOCK",)
    assert review.weighted_score_used is False


def test_review_contract_rejects_duplicate_gates_false_go_and_consumed_unlock() -> None:
    blocked = _gate("blocked-gate", GateStatus.BLOCKED_EXTERNAL_INPUT)
    valid = build_readiness_review(
        (blocked,), live_trading_locked=True, manual_unlock_received=False
    ).model_dump(mode="json")

    false_go = dict(valid)
    false_go["decision"] = "GO"
    with pytest.raises(ValidationError):
        ReadinessReview.model_validate(false_go)

    consumed_unlock = dict(valid)
    consumed_unlock["manual_unlock_received"] = True
    with pytest.raises(ValidationError):
        ReadinessReview.model_validate(consumed_unlock)

    with pytest.raises(ValueError, match="unique gates"):
        build_readiness_review(
            (blocked, blocked), live_trading_locked=True, manual_unlock_received=False
        )


def test_p18_never_exposes_the_separate_live_unlock_flow() -> None:
    assert (
        p18_real_order_capability(live_trading_locked=True, manual_unlock_received=False) is False
    )
    assert (
        p18_real_order_capability(live_trading_locked=False, manual_unlock_received=False) is False
    )
    assert p18_real_order_capability(live_trading_locked=True, manual_unlock_received=True) is False
    with pytest.raises(PermissionError, match="SEPARATE-LIVE-UNLOCK-NOT-IMPLEMENTED"):
        p18_real_order_capability(live_trading_locked=False, manual_unlock_received=True)


def test_capital_ladder_uses_lower_dual_cap_and_zero_operational_limits(
    project_root: Path,
) -> None:
    policy = LiveReadinessPolicy.model_validate_json(
        (project_root / "configs/live_readiness/policy.json").read_text(encoding="utf-8")
    )
    assert [tier.activated for tier in policy.capital_ladder.tiers] == [True, False, False]
    for tier in policy.capital_ladder.tiers:
        assert tier.effective_capital_usd == min(
            tier.hard_code_capital_usd, tier.user_policy_capital_usd
        )
        assert tier.effective_capital_usd == 0
        assert tier.max_gross_notional_usd == 0
        assert tier.max_single_order_notional_usd == 0
        assert tier.max_daily_loss_usd == 0
        assert tier.max_equity_fraction == 0


def test_scope_and_capital_contracts_reject_expansion_without_approval(
    project_root: Path,
) -> None:
    with pytest.raises(ValidationError):
        CanaryScope(
            selection_status=SelectionStatus.SELECTED,
            strategy_id="strategy-1",
            account_scope_id="account-1",
            instrument_ids=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        )

    validated = LiveReadinessPolicy.model_validate_json(
        (project_root / "configs/live_readiness/policy.json").read_text("utf-8")
    )
    raw = cast("dict[str, object]", validated.model_dump(mode="python"))
    ladder = cast("dict[str, object]", raw["capital_ladder"])
    tiers = cast("list[dict[str, object]]", ladder["tiers"])
    tiers[1]["user_policy_capital_usd"] = Decimal("100")
    tiers[1]["effective_capital_usd"] = Decimal("100")
    tiers[1]["max_gross_notional_usd"] = Decimal("101")
    tiers[1]["activated"] = True
    tiers[1]["approval_reference"] = "approval-test"
    with pytest.raises(ValidationError, match="gross notional"):
        LiveReadinessPolicy.model_validate(raw)


def test_manifest_signature_detects_tampering_and_never_authorizes_live() -> None:
    envelope = sign_manifest(_manifest(), Ed25519PrivateKey.generate())
    assert verify_manifest(envelope) is True
    assert envelope.signature_verified is True
    assert envelope.signature_purpose == "EVIDENCE_INTEGRITY_ONLY"
    assert envelope.private_key_persisted is False
    assert envelope.authorization_capability is False
    assert envelope.manifest.releaseable is False

    tampered = envelope.model_dump(mode="python")
    manifest = cast("dict[str, object]", tampered["manifest"])
    versions = cast("dict[str, str]", manifest["frozen_versions"])
    versions["model"] = "tampered"
    assert verify_manifest(SignedManifestEnvelope.model_validate(tampered)) is False


def test_manifest_rejects_long_expiry_or_live_authorization_flags() -> None:
    with pytest.raises(ValidationError, match="expire within 24 hours"):
        _manifest(expires_after=timedelta(hours=25))

    for field, value in (
        ("releaseable", True),
        ("live_trading_locked", False),
        ("user_approval_received", True),
        ("manual_unlock_received", True),
    ):
        payload = _manifest().model_dump(mode="python")
        payload[field] = value
        with pytest.raises(ValidationError, match="non-authorizing"):
            CanaryReleaseManifest.model_validate(payload)
