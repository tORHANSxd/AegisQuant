"""Signed versioned policy and Paper-only boundary tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from aegisquant.domain.entities import DeploymentStage
from aegisquant.risk.policy import RiskPolicy, verify_signed_risk_policy
from tests.p11_helpers import AS_OF, DECISION_TIME, risk_policy, signed_policy, trusted_public_keys


def test_signed_risk_policy_verifies_with_public_key_and_contains_no_private_key() -> None:
    envelope = signed_policy()
    verified = verify_signed_risk_policy(
        envelope,
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
        deployment_stage=DeploymentStage.PAPER,
    )
    serialized = envelope.model_dump_json()
    assert verified.version == "p11-risk-fixture-v1"
    assert "private" not in serialized.casefold()
    assert envelope.policy_sha256 and len(envelope.signature_hex) == 128


def test_policy_hash_signature_expiry_and_signer_fail_closed() -> None:
    envelope = signed_policy()
    changed = envelope.model_copy(
        update={"policy": envelope.policy.model_copy(update={"version": "tampered"})}
    )
    with pytest.raises(ValueError, match="HASH-MISMATCH"):
        verify_signed_risk_policy(
            changed,
            trusted_public_keys=trusted_public_keys(),
            decision_time=DECISION_TIME,
            deployment_stage=DeploymentStage.PAPER,
        )
    with pytest.raises(ValueError, match="UNTRUSTED-SIGNER"):
        verify_signed_risk_policy(
            envelope,
            trusted_public_keys={},
            decision_time=DECISION_TIME,
            deployment_stage=DeploymentStage.PAPER,
        )
    with pytest.raises(ValueError, match="NOT-EFFECTIVE"):
        verify_signed_risk_policy(
            envelope,
            trusted_public_keys=trusted_public_keys(),
            decision_time=AS_OF + timedelta(days=2),
            deployment_stage=DeploymentStage.PAPER,
        )


def test_example_risk_values_are_paper_only_and_have_no_auto_recovery() -> None:
    payload = risk_policy().model_dump(mode="python")
    payload["allowed_stages"] = (DeploymentStage.TESTNET,)
    with pytest.raises(ValueError, match="PAPER-ONLY"):
        RiskPolicy.model_validate(payload)
    payload = risk_policy().model_dump(mode="python")
    payload["automatic_recovery_enabled"] = True
    with pytest.raises(ValueError, match="automatic risk recovery"):
        RiskPolicy.model_validate(payload)
