"""V5-P12 signed Testnet, alert, risk, and reconciliation evidence tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from aegisquant.canary_readiness import (
    AttestedEvidenceKind,
    BinanceTestnetRunEvidence,
    P12EvidenceBundle,
    P12GateName,
    P12GateStatus,
    P12ReadinessPolicy,
    create_binance_testnet_run_evidence,
    create_external_alert_delivery_receipt,
    create_p12_evidence_attestation,
    create_p12_evidence_bundle,
    create_p12_readiness_policy,
    create_protected_timestamp_receipt,
    create_testnet_reconciliation_receipt,
    create_testnet_risk_authorization_receipt,
    evaluate_p12_canary_readiness,
    verify_p12_evidence_attestation,
)
from aegisquant.canary_readiness import TestnetEvidenceOrigin as EvidenceOrigin
from aegisquant.domain.evidence import EvidenceTier
from tests.v5_p11.helpers import START, digest
from tests.v5_p12.helpers import (
    ASSESSMENT_TIME,
    TESTNET_END,
    TESTNET_START,
    fixture_private_key,
    fixture_timestamp_private_key,
    make_complete_fixture,
    make_readiness_policy,
    make_testnet_evidence,
)


def make_timestamp(
    evidence_sha256: str,
    signed_at: datetime,
    policy: P12ReadinessPolicy,
):
    return create_protected_timestamp_receipt(
        evidence_sha256=evidence_sha256,
        authority_id=policy.trusted_timestamp_authority_id,
        key_id=policy.trusted_timestamp_key_id,
        timestamped_at=signed_at - timedelta(microseconds=1),
        nonce_sha256=digest(f"timestamp:{evidence_sha256}"),
        private_key=fixture_timestamp_private_key(),
    )


def test_reconciliation_result_is_recomputed_and_authoritative_facts_stay_immutable() -> None:
    receipt = create_testnet_reconciliation_receipt(
        run_id="run-1",
        account_scope_id="scope-1",
        started_at=START,
        completed_at=START + timedelta(minutes=1),
        venue_order_count=2,
        internal_order_count=2,
        venue_fill_count=1,
        ledger_fill_count=1,
        read_model_fill_count=1,
    )
    assert receipt.reconciled is True
    assert receipt.authoritative_facts_mutated is False
    with pytest.raises(ValidationError, match="RECONCILIATION-RESULT-MISMATCH"):
        type(receipt).model_validate(
            {**receipt.model_dump(mode="python"), "unmatched_fill_count": 1}
        )


def test_simulator_cannot_claim_testnet_forward_tier() -> None:
    simulator = make_testnet_evidence(real=False)
    with pytest.raises(ValidationError, match="SIMULATOR-EVIDENCE-INCONSISTENT"):
        BinanceTestnetRunEvidence.model_validate(
            {
                **simulator.model_dump(mode="python"),
                "evidence_tier": EvidenceTier.TESTNET_FORWARD,
            }
        )


def test_real_testnet_shape_requires_private_network_and_credential_reference() -> None:
    reconciliation = create_testnet_reconciliation_receipt(
        run_id="run-1",
        account_scope_id="scope-1",
        started_at=TESTNET_END - timedelta(minutes=1),
        completed_at=TESTNET_END,
        venue_order_count=1,
        internal_order_count=1,
        venue_fill_count=1,
        ledger_fill_count=1,
        read_model_fill_count=1,
    )
    with pytest.raises(ValidationError, match="REAL-TESTNET-EVIDENCE-INCONSISTENT"):
        create_binance_testnet_run_evidence(
            evidence_tier=EvidenceTier.TESTNET_FORWARD,
            origin=EvidenceOrigin.REAL_BINANCE_TESTNET,
            candidate_id="candidate-1",
            strategy_id="strategy-1",
            forward_pair_id="forward-pair-1",
            forward_proof_sha256=digest("forward-proof"),
            run_id="run-1",
            account_scope_id="scope-1",
            credential_reference_id=None,
            started_at=TESTNET_START,
            ended_at=TESTNET_END,
            time_compressed=False,
            simulator_used=False,
            network_request_count=0,
            private_api_authenticated=False,
            testnet_account_verified=False,
            accepted_order_count=1,
            terminal_order_count=1,
            fill_count=1,
            unresolved_unknown_order_count=0,
            source_request_sha256=digest("request"),
            source_response_sha256=digest("response"),
            reconciliation=reconciliation,
        )


def test_testnet_counts_must_match_reconciliation_receipt() -> None:
    evidence = make_testnet_evidence(real=True)
    with pytest.raises(ValidationError, match="TESTNET-RECONCILIATION-COUNT-MISMATCH"):
        BinanceTestnetRunEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "accepted_order_count": evidence.accepted_order_count + 1,
            }
        )


def test_attestation_uses_precommitted_trusted_key_and_detects_wrong_signer() -> None:
    trusted = fixture_private_key()
    policy = make_readiness_policy(trusted)
    evidence = make_testnet_evidence(real=True)
    signed_at = evidence.ended_at + timedelta(seconds=1)
    timestamp = make_timestamp(evidence.evidence_sha256, signed_at, policy)
    attestation = create_p12_evidence_attestation(
        evidence_kind=AttestedEvidenceKind.BINANCE_TESTNET_RUN,
        evidence_sha256=evidence.evidence_sha256,
        attestor_id=policy.trusted_attestor_id,
        key_id=policy.trusted_attestor_key_id,
        signed_at=signed_at,
        protected_timestamp=timestamp,
        private_key=trusted,
    )
    assert verify_p12_evidence_attestation(attestation, policy) is True

    wrong_key = Ed25519PrivateKey.generate()
    forged = create_p12_evidence_attestation(
        evidence_kind=AttestedEvidenceKind.BINANCE_TESTNET_RUN,
        evidence_sha256=evidence.evidence_sha256,
        attestor_id=policy.trusted_attestor_id,
        key_id=policy.trusted_attestor_key_id,
        signed_at=signed_at,
        protected_timestamp=timestamp,
        private_key=wrong_key,
    )
    assert verify_p12_evidence_attestation(forged, policy) is False


def test_attestation_rejects_timestamp_signed_by_untrusted_authority_key() -> None:
    trusted = fixture_private_key()
    policy = make_readiness_policy(trusted)
    evidence = make_testnet_evidence(real=True)
    signed_at = evidence.ended_at + timedelta(seconds=1)
    timestamp = create_protected_timestamp_receipt(
        evidence_sha256=evidence.evidence_sha256,
        authority_id=policy.trusted_timestamp_authority_id,
        key_id=policy.trusted_timestamp_key_id,
        timestamped_at=signed_at - timedelta(microseconds=1),
        nonce_sha256=digest("wrong-timestamp-key"),
        private_key=Ed25519PrivateKey.generate(),
    )
    attestation = create_p12_evidence_attestation(
        evidence_kind=AttestedEvidenceKind.BINANCE_TESTNET_RUN,
        evidence_sha256=evidence.evidence_sha256,
        attestor_id=policy.trusted_attestor_id,
        key_id=policy.trusted_attestor_key_id,
        signed_at=signed_at,
        protected_timestamp=timestamp,
        private_key=trusted,
    )
    assert verify_p12_evidence_attestation(attestation, policy) is False


def test_wrong_testnet_attestation_fails_closed() -> None:
    fixture = make_complete_fixture(signing_key=fixture_private_key())
    wrong_key = Ed25519PrivateKey.generate()
    timestamp = make_timestamp(
        fixture.testnet.evidence_sha256,
        TESTNET_END + timedelta(minutes=1),
        fixture.policy,
    )
    forged = create_p12_evidence_attestation(
        evidence_kind=AttestedEvidenceKind.BINANCE_TESTNET_RUN,
        evidence_sha256=fixture.testnet.evidence_sha256,
        attestor_id=fixture.policy.trusted_attestor_id,
        key_id=fixture.policy.trusted_attestor_key_id,
        signed_at=TESTNET_END + timedelta(minutes=1),
        protected_timestamp=timestamp,
        private_key=wrong_key,
    )
    bundle = create_p12_evidence_bundle(
        forward_proof=fixture.bundle.forward_proof,
        testnet=fixture.testnet,
        testnet_attestation=forged,
        external_alert=fixture.bundle.external_alert,
        external_alert_attestation=fixture.bundle.external_alert_attestation,
        risk_authorization=fixture.bundle.risk_authorization,
        risk_attestation=fixture.bundle.risk_attestation,
        source_artifact_sha256=fixture.bundle.source_artifact_sha256,
    )
    assessment = evaluate_p12_canary_readiness(
        policy=fixture.policy,
        evidence_bundle=bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    testnet = next(item for item in assessment.gates if item.gate is P12GateName.TESTNET)
    assert testnet.status is P12GateStatus.FAIL
    assert testnet.reason_codes == ("TESTNET_ATTESTATION_INVALID",)


def test_risk_receipt_cannot_be_spliced_to_another_testnet_run() -> None:
    fixture = make_complete_fixture()
    risk = fixture.risk
    spliced = create_testnet_risk_authorization_receipt(
        evidence_tier=risk.evidence_tier,
        candidate_id=risk.candidate_id,
        strategy_id=risk.strategy_id,
        run_id=risk.run_id,
        account_scope_id=risk.account_scope_id,
        issued_at=risk.issued_at,
        expires_at=risk.expires_at,
        readiness_policy_sha256=risk.readiness_policy_sha256,
        integrated_decision_sha256=risk.integrated_decision_sha256,
        risk_policy_sha256=risk.risk_policy_sha256,
        risk_snapshot_sha256=risk.risk_snapshot_sha256,
        testnet_evidence_sha256=digest("different-testnet-evidence"),
        reconciliation_receipt_sha256=risk.reconciliation_receipt_sha256,
        external_alert_receipt_sha256=risk.external_alert_receipt_sha256,
        drawdown_pass=risk.drawdown_pass,
        margin_pass=risk.margin_pass,
        liquidity_pass=risk.liquidity_pass,
        venue_pass=risk.venue_pass,
        security_pass=risk.security_pass,
        event_risk_pass=risk.event_risk_pass,
        reconciliation_pass=risk.reconciliation_pass,
        testnet_order_authorized=risk.testnet_order_authorized,
    )
    with pytest.raises(ValidationError, match="RISK-EVIDENCE-SPLICE"):
        P12EvidenceBundle.model_validate(
            {
                "forward_proof": fixture.forward_proof,
                "testnet": fixture.testnet,
                "external_alert": fixture.alert,
                "risk_authorization": spliced,
                "source_artifact_sha256": {"reports/v5/P11/FORWARD_PROOF_EVIDENCE.json": "c" * 64},
                "bundle_sha256": "0" * 64,
            }
        )


def test_external_alert_cannot_be_spliced_to_another_testnet_run() -> None:
    fixture = make_complete_fixture()
    alert = fixture.alert
    spliced = create_external_alert_delivery_receipt(
        evidence_tier=alert.evidence_tier,
        destination_kind=alert.destination_kind,
        candidate_id=alert.candidate_id,
        strategy_id=alert.strategy_id,
        run_id="different-testnet-run",
        account_scope_id=alert.account_scope_id,
        alert_event_id=alert.alert_event_id,
        correlation_id=alert.correlation_id,
        destination_id=alert.destination_id,
        attempted_at=alert.attempted_at,
        acknowledged_at=alert.acknowledged_at,
        attempted_channel_count=alert.attempted_channel_count,
        delivered_channel_count=alert.delivered_channel_count,
        https_transport=alert.https_transport,
        loopback_destination=alert.loopback_destination,
        http_status_code=alert.http_status_code,
        payload_sha256=alert.payload_sha256,
        acknowledgment_sha256=alert.acknowledgment_sha256,
        remote_acknowledged=alert.remote_acknowledged,
        durable_receipt_persisted=alert.durable_receipt_persisted,
        immutable_audit_anchor_present=alert.immutable_audit_anchor_present,
    )
    with pytest.raises(ValidationError, match="RISK-EVIDENCE-SPLICE"):
        create_p12_evidence_bundle(
            forward_proof=fixture.forward_proof,
            testnet=fixture.testnet,
            external_alert=spliced,
            risk_authorization=fixture.risk,
            source_artifact_sha256=fixture.bundle.source_artifact_sha256,
        )


def test_risk_gate_rejects_uncommitted_integrated_decision_hash() -> None:
    fixture = make_complete_fixture()
    risk = fixture.risk
    forged_risk = create_testnet_risk_authorization_receipt(
        evidence_tier=risk.evidence_tier,
        candidate_id=risk.candidate_id,
        strategy_id=risk.strategy_id,
        run_id=risk.run_id,
        account_scope_id=risk.account_scope_id,
        issued_at=risk.issued_at,
        expires_at=risk.expires_at,
        readiness_policy_sha256=risk.readiness_policy_sha256,
        integrated_decision_sha256=digest("uncommitted-integrated-decision"),
        risk_policy_sha256=risk.risk_policy_sha256,
        risk_snapshot_sha256=risk.risk_snapshot_sha256,
        testnet_evidence_sha256=risk.testnet_evidence_sha256,
        reconciliation_receipt_sha256=risk.reconciliation_receipt_sha256,
        external_alert_receipt_sha256=risk.external_alert_receipt_sha256,
        drawdown_pass=risk.drawdown_pass,
        margin_pass=risk.margin_pass,
        liquidity_pass=risk.liquidity_pass,
        venue_pass=risk.venue_pass,
        security_pass=risk.security_pass,
        event_risk_pass=risk.event_risk_pass,
        reconciliation_pass=risk.reconciliation_pass,
        testnet_order_authorized=risk.testnet_order_authorized,
    )
    signed_at = TESTNET_END + timedelta(minutes=1)
    timestamp = make_timestamp(forged_risk.receipt_sha256, signed_at, fixture.policy)
    attestation = create_p12_evidence_attestation(
        evidence_kind=AttestedEvidenceKind.TESTNET_RISK_AUTHORIZATION,
        evidence_sha256=forged_risk.receipt_sha256,
        attestor_id=fixture.policy.trusted_attestor_id,
        key_id=fixture.policy.trusted_attestor_key_id,
        signed_at=signed_at,
        protected_timestamp=timestamp,
        private_key=fixture.private_key,
    )
    bundle = create_p12_evidence_bundle(
        forward_proof=fixture.forward_proof,
        testnet=fixture.testnet,
        testnet_attestation=fixture.bundle.testnet_attestation,
        external_alert=fixture.alert,
        external_alert_attestation=fixture.bundle.external_alert_attestation,
        risk_authorization=forged_risk,
        risk_attestation=attestation,
        source_artifact_sha256=fixture.bundle.source_artifact_sha256,
    )
    assessment = evaluate_p12_canary_readiness(
        policy=fixture.policy,
        evidence_bundle=bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    gate = next(item for item in assessment.gates if item.gate is P12GateName.RISK)
    assert gate.status is P12GateStatus.FAIL
    assert "RISK_DECISION_OR_POLICY_COMMITMENT_MISMATCH" in gate.reason_codes


def test_readiness_policy_thresholds_and_hash_cannot_be_lowered_or_tampered() -> None:
    key = fixture_private_key()
    public_key = key.public_key().public_bytes_raw()
    with pytest.raises(ValidationError):
        create_p12_readiness_policy(
            version="bad-policy",
            candidate_id="candidate-1",
            strategy_id="strategy-1",
            forward_proof_policy_sha256=digest("forward-policy"),
            integrated_decision_sha256=digest("integrated-decision"),
            risk_policy_sha256=digest("risk-policy"),
            approved_at=START,
            effective_from=START - timedelta(seconds=1),
            minimum_testnet_soak_seconds=3599,
            minimum_accepted_order_count=1,
            minimum_terminal_order_count=1,
            minimum_fill_count=1,
            trusted_attestor_id="attestor",
            trusted_attestor_key_id="key",
            trusted_attestor_public_key_base64=__import__("base64").b64encode(public_key).decode(),
            trusted_timestamp_authority_id="timestamp-authority",
            trusted_timestamp_key_id="timestamp-key",
            trusted_timestamp_public_key_base64=__import__("base64")
            .b64encode(fixture_timestamp_private_key().public_key().public_bytes_raw())
            .decode(),
        )
    policy = make_readiness_policy(key)
    with pytest.raises(ValidationError, match="POLICY-HASH-MISMATCH"):
        type(policy).model_validate({**policy.model_dump(mode="python"), "minimum_fill_count": 1})


def test_model_construct_cannot_bypass_nested_revalidation() -> None:
    fixture = make_complete_fixture()
    forged_testnet = fixture.testnet.model_copy(update={"simulator_used": True})
    forged_bundle = fixture.bundle.model_copy(update={"testnet": forged_testnet})
    with pytest.raises(ValidationError, match="REAL-TESTNET-EVIDENCE-INCONSISTENT"):
        evaluate_p12_canary_readiness(
            policy=fixture.policy,
            evidence_bundle=forged_bundle,
            assessed_at=ASSESSMENT_TIME,
        )
