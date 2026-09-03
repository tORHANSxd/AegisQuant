"""Deterministic builders for V5-P12 contract tests and evidence."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisquant.canary_readiness import (
    AlertDestinationKind,
    AttestedEvidenceKind,
    BinanceTestnetRunEvidence,
    ExternalAlertDeliveryReceipt,
    P12EvidenceBundle,
    P12ReadinessPolicy,
    TestnetEvidenceOrigin,
    TestnetRiskAuthorizationReceipt,
    create_binance_testnet_run_evidence,
    create_external_alert_delivery_receipt,
    create_p12_evidence_attestation,
    create_p12_evidence_bundle,
    create_p12_readiness_policy,
    create_protected_timestamp_receipt,
    create_testnet_reconciliation_receipt,
    create_testnet_risk_authorization_receipt,
)
from aegisquant.data.hashing import sha256_file
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.forward import (
    ForwardMode,
    ForwardRunKind,
    PaperShadowForwardProof,
    evaluate_forward_mode,
    evaluate_paper_shadow_forward,
)
from tests.v5_p11.helpers import START, digest, make_policy, make_session

TESTNET_START = START + timedelta(days=31)
TESTNET_END = TESTNET_START + timedelta(days=1)
ASSESSMENT_TIME = TESTNET_END + timedelta(minutes=2)
ROOT = Path(__file__).resolve().parents[2]


def fixture_private_key() -> Ed25519PrivateKey:
    seed = hashlib.sha256(b"aegisquant-v5-p12-contract-fixture-key").digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def fixture_timestamp_private_key() -> Ed25519PrivateKey:
    seed = hashlib.sha256(b"aegisquant-v5-p12-timestamp-fixture-key").digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def source_artifact_commitments() -> dict[str, str]:
    paths = (
        "reports/v5/P11/FORWARD_PROOF_EVIDENCE.json",
        "reports/execution/P12_TESTNET_CAPABILITY.json",
        "reports/live_readiness/READINESS_DECISION.json",
    )
    return {path: sha256_file(ROOT / path) for path in paths}


def make_readiness_policy(
    private_key: Ed25519PrivateKey | None = None,
    timestamp_private_key: Ed25519PrivateKey | None = None,
) -> P12ReadinessPolicy:
    key = private_key or fixture_private_key()
    timestamp_key = timestamp_private_key or fixture_timestamp_private_key()
    public_key = base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")
    timestamp_public_key = base64.b64encode(timestamp_key.public_key().public_bytes_raw()).decode(
        "ascii"
    )
    return create_p12_readiness_policy(
        version="v5-p12-policy-1",
        candidate_id="v5-btcusdt-candidate-1",
        strategy_id="v5-truth-causal-strategy-1",
        forward_proof_policy_sha256=make_policy().policy_sha256,
        integrated_decision_sha256=digest("p10-integrated-decision"),
        risk_policy_sha256=digest("signed-risk-policy"),
        approved_at=START - timedelta(days=3),
        effective_from=START - timedelta(days=2),
        minimum_testnet_soak_seconds=86400,
        minimum_accepted_order_count=3,
        minimum_terminal_order_count=3,
        minimum_fill_count=2,
        trusted_attestor_id="development-contract-attestor",
        trusted_attestor_key_id="development-contract-key-1",
        trusted_attestor_public_key_base64=public_key,
        trusted_timestamp_authority_id="development-timestamp-authority",
        trusted_timestamp_key_id="development-timestamp-key-1",
        trusted_timestamp_public_key_base64=timestamp_public_key,
    )


def make_forward_proof(*, real: bool) -> PaperShadowForwardProof:
    run_kind = ForwardRunKind.WALL_CLOCK_FORWARD if real else ForwardRunKind.DEVELOPMENT_FIXTURE
    days = 30 if real else 1
    policy = make_policy()
    return evaluate_paper_shadow_forward(
        paper=evaluate_forward_mode(
            session=make_session(mode=ForwardMode.PAPER, run_kind=run_kind, days=days),
            policy=policy,
        ),
        shadow=evaluate_forward_mode(
            session=make_session(mode=ForwardMode.SHADOW, run_kind=run_kind, days=days),
            policy=policy,
        ),
    )


def make_testnet_evidence(
    *,
    real: bool,
    forward_proof: PaperShadowForwardProof | None = None,
    accepted_order_count: int = 3,
    terminal_order_count: int = 3,
    fill_count: int = 2,
    reconciliation_pass: bool = True,
) -> BinanceTestnetRunEvidence:
    bound_forward_proof = forward_proof or make_forward_proof(real=True)
    difference = 0 if reconciliation_pass else 1
    receipt = create_testnet_reconciliation_receipt(
        run_id="binance-testnet-run-1",
        account_scope_id="testnet-account-scope-1",
        started_at=TESTNET_END - timedelta(minutes=5),
        completed_at=TESTNET_END,
        venue_order_count=accepted_order_count,
        internal_order_count=accepted_order_count,
        venue_fill_count=fill_count,
        ledger_fill_count=fill_count,
        read_model_fill_count=fill_count,
        unmatched_order_count=difference,
    )
    return create_binance_testnet_run_evidence(
        evidence_tier=(EvidenceTier.TESTNET_FORWARD if real else EvidenceTier.DEVELOPMENT),
        origin=(
            TestnetEvidenceOrigin.REAL_BINANCE_TESTNET
            if real
            else TestnetEvidenceOrigin.DEVELOPMENT_SIMULATOR
        ),
        candidate_id="v5-btcusdt-candidate-1",
        strategy_id="v5-truth-causal-strategy-1",
        forward_pair_id=bound_forward_proof.paper.session.pair_id,
        forward_proof_sha256=bound_forward_proof.proof_sha256,
        run_id="binance-testnet-run-1",
        account_scope_id="testnet-account-scope-1",
        credential_reference_id="secret-ref:testnet/binance/1" if real else None,
        started_at=TESTNET_START,
        ended_at=TESTNET_END,
        time_compressed=not real,
        simulator_used=not real,
        network_request_count=80 if real else 0,
        private_api_authenticated=real,
        testnet_account_verified=real,
        accepted_order_count=accepted_order_count,
        terminal_order_count=terminal_order_count,
        fill_count=fill_count,
        unresolved_unknown_order_count=0,
        source_request_sha256=digest("testnet-request-log"),
        source_response_sha256=digest("testnet-response-log"),
        reconciliation=receipt,
    )


def make_alert_receipt(*, external: bool) -> ExternalAlertDeliveryReceipt:
    attempted_at = TESTNET_END - timedelta(hours=1)
    return create_external_alert_delivery_receipt(
        evidence_tier=(EvidenceTier.TESTNET_FORWARD if external else EvidenceTier.DEVELOPMENT),
        destination_kind=(
            AlertDestinationKind.EXTERNAL_NON_LOOPBACK
            if external
            else AlertDestinationKind.LOOPBACK_CONTRACT_RECEIVER
        ),
        candidate_id="v5-btcusdt-candidate-1",
        strategy_id="v5-truth-causal-strategy-1",
        run_id="binance-testnet-run-1",
        account_scope_id="testnet-account-scope-1",
        alert_event_id="testnet-sev0-drill-1",
        correlation_id="testnet-run-correlation-1",
        destination_id="external-on-call-receiver" if external else "loopback-receiver",
        attempted_at=attempted_at,
        acknowledged_at=attempted_at + timedelta(seconds=2),
        attempted_channel_count=1,
        delivered_channel_count=1,
        https_transport=external,
        loopback_destination=not external,
        http_status_code=202,
        payload_sha256=digest("alert-payload"),
        acknowledgment_sha256=digest("external-alert-ack"),
        remote_acknowledged=True,
        durable_receipt_persisted=external,
        immutable_audit_anchor_present=external,
    )


@dataclass(frozen=True, slots=True)
class CompleteP12Fixture:
    policy: P12ReadinessPolicy
    forward_proof: PaperShadowForwardProof
    testnet: BinanceTestnetRunEvidence
    alert: ExternalAlertDeliveryReceipt
    risk: TestnetRiskAuthorizationReceipt
    bundle: P12EvidenceBundle
    private_key: Ed25519PrivateKey


def make_complete_fixture(
    *,
    accepted_order_count: int = 3,
    risk_checks_pass: bool = True,
    signing_key: Ed25519PrivateKey | None = None,
) -> CompleteP12Fixture:
    private_key = signing_key or fixture_private_key()
    timestamp_private_key = fixture_timestamp_private_key()
    policy = make_readiness_policy(private_key, timestamp_private_key)
    forward_proof = make_forward_proof(real=True)
    testnet = make_testnet_evidence(
        real=True,
        forward_proof=forward_proof,
        accepted_order_count=accepted_order_count,
        terminal_order_count=min(accepted_order_count, 3),
    )
    alert = make_alert_receipt(external=True)
    attestation_time = TESTNET_END + timedelta(minutes=1)
    timestamp_time = attestation_time - timedelta(seconds=1)
    testnet_timestamp = create_protected_timestamp_receipt(
        evidence_sha256=testnet.evidence_sha256,
        authority_id=policy.trusted_timestamp_authority_id,
        key_id=policy.trusted_timestamp_key_id,
        timestamped_at=timestamp_time,
        nonce_sha256=digest("testnet-timestamp-nonce"),
        private_key=timestamp_private_key,
    )
    testnet_attestation = create_p12_evidence_attestation(
        evidence_kind=AttestedEvidenceKind.BINANCE_TESTNET_RUN,
        evidence_sha256=testnet.evidence_sha256,
        attestor_id=policy.trusted_attestor_id,
        key_id=policy.trusted_attestor_key_id,
        signed_at=attestation_time,
        protected_timestamp=testnet_timestamp,
        private_key=private_key,
    )
    alert_timestamp = create_protected_timestamp_receipt(
        evidence_sha256=alert.receipt_sha256,
        authority_id=policy.trusted_timestamp_authority_id,
        key_id=policy.trusted_timestamp_key_id,
        timestamped_at=timestamp_time,
        nonce_sha256=digest("alert-timestamp-nonce"),
        private_key=timestamp_private_key,
    )
    alert_attestation = create_p12_evidence_attestation(
        evidence_kind=AttestedEvidenceKind.EXTERNAL_ALERT_DELIVERY,
        evidence_sha256=alert.receipt_sha256,
        attestor_id=policy.trusted_attestor_id,
        key_id=policy.trusted_attestor_key_id,
        signed_at=attestation_time,
        protected_timestamp=alert_timestamp,
        private_key=private_key,
    )
    risk = create_testnet_risk_authorization_receipt(
        evidence_tier=EvidenceTier.TESTNET_FORWARD,
        candidate_id=policy.candidate_id,
        strategy_id=policy.strategy_id,
        run_id=testnet.run_id,
        account_scope_id=testnet.account_scope_id,
        issued_at=TESTNET_START - timedelta(hours=1),
        expires_at=TESTNET_END + timedelta(hours=1),
        readiness_policy_sha256=policy.policy_sha256,
        integrated_decision_sha256=policy.integrated_decision_sha256,
        risk_policy_sha256=policy.risk_policy_sha256,
        risk_snapshot_sha256=digest("risk-snapshot"),
        testnet_evidence_sha256=testnet.evidence_sha256,
        reconciliation_receipt_sha256=testnet.reconciliation.receipt_sha256,
        external_alert_receipt_sha256=alert.receipt_sha256,
        drawdown_pass=risk_checks_pass,
        margin_pass=risk_checks_pass,
        liquidity_pass=risk_checks_pass,
        venue_pass=risk_checks_pass,
        security_pass=risk_checks_pass,
        event_risk_pass=risk_checks_pass,
        reconciliation_pass=risk_checks_pass,
        testnet_order_authorized=risk_checks_pass,
    )
    risk_timestamp = create_protected_timestamp_receipt(
        evidence_sha256=risk.receipt_sha256,
        authority_id=policy.trusted_timestamp_authority_id,
        key_id=policy.trusted_timestamp_key_id,
        timestamped_at=timestamp_time,
        nonce_sha256=digest("risk-timestamp-nonce"),
        private_key=timestamp_private_key,
    )
    risk_attestation = create_p12_evidence_attestation(
        evidence_kind=AttestedEvidenceKind.TESTNET_RISK_AUTHORIZATION,
        evidence_sha256=risk.receipt_sha256,
        attestor_id=policy.trusted_attestor_id,
        key_id=policy.trusted_attestor_key_id,
        signed_at=attestation_time,
        protected_timestamp=risk_timestamp,
        private_key=private_key,
    )
    bundle = create_p12_evidence_bundle(
        forward_proof=forward_proof,
        testnet=testnet,
        testnet_attestation=testnet_attestation,
        external_alert=alert,
        external_alert_attestation=alert_attestation,
        risk_authorization=risk,
        risk_attestation=risk_attestation,
        source_artifact_sha256=source_artifact_commitments(),
    )
    return CompleteP12Fixture(
        policy=policy,
        forward_proof=forward_proof,
        testnet=testnet,
        alert=alert,
        risk=risk,
        bundle=bundle,
        private_key=private_key,
    )


def make_current_blocked_bundle() -> tuple[P12ReadinessPolicy, P12EvidenceBundle]:
    policy = make_readiness_policy()
    bundle = create_p12_evidence_bundle(
        forward_proof=make_forward_proof(real=False),
        source_artifact_sha256=source_artifact_commitments(),
    )
    return policy, bundle
