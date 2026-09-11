"""Fail-closed Testnet and Canary-readiness contracts for V5-P12."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.forward import (
    ForwardMode,
    ForwardProofStatus,
    ForwardRunKind,
    PaperShadowForwardProof,
)


class P12GateName(StrEnum):
    TRUTH_CALIBRATION = "TRUTH_CALIBRATION"
    FORECAST_CALIBRATION = "FORECAST_CALIBRATION"
    COST_CALIBRATION = "COST_CALIBRATION"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    TESTNET = "TESTNET"
    RISK = "RISK"


class P12GateStatus(StrEnum):
    PASS = "PASS"  # noqa: S105  # nosec B105 -- status token
    FAIL = "FAIL"
    BLOCKED_EXTERNAL_INPUT = "BLOCKED_EXTERNAL_INPUT"


class CanaryReadinessDecision(StrEnum):
    CANARY_REVIEW_READY = "CANARY_REVIEW_READY"
    NO_PROMOTION = "NO_PROMOTION"


class P12NextAction(StrEnum):
    REQUEST_MANUAL_CANARY_REVIEW = "REQUEST_MANUAL_CANARY_REVIEW"
    EXTEND_PAPER = "EXTEND_PAPER"
    PROVIDE_EXTERNAL_EVIDENCE = "PROVIDE_EXTERNAL_EVIDENCE"
    REMEDIATE_AND_RETEST = "REMEDIATE_AND_RETEST"


class TestnetEvidenceOrigin(StrEnum):
    DEVELOPMENT_SIMULATOR = "DEVELOPMENT_SIMULATOR"
    REAL_BINANCE_TESTNET = "REAL_BINANCE_TESTNET"


class AlertDestinationKind(StrEnum):
    LOOPBACK_CONTRACT_RECEIVER = "LOOPBACK_CONTRACT_RECEIVER"
    EXTERNAL_NON_LOOPBACK = "EXTERNAL_NON_LOOPBACK"


class AttestedEvidenceKind(StrEnum):
    BINANCE_TESTNET_RUN = "BINANCE_TESTNET_RUN"
    EXTERNAL_ALERT_DELIVERY = "EXTERNAL_ALERT_DELIVERY"
    TESTNET_RISK_AUTHORIZATION = "TESTNET_RISK_AUTHORIZATION"


ReasonCode = Annotated[
    str,
    Field(min_length=1, max_length=160, pattern=r"^[A-Z0-9][A-Z0-9_-]*$"),
]


def _hashed_model(
    model_type: type[DomainModel], payload: Mapping[str, object], hash_field: str
) -> DomainModel:
    candidate_payload = {**payload, hash_field: "0" * 64}
    candidate = model_type.model_construct(**cast("dict[str, Any]", candidate_payload))
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={hash_field}))
    return model_type.model_validate({**payload, hash_field: digest})


def _validate_hash(value: str, field_name: str) -> str:
    return ensure_sha256(value, field_name=field_name)


def _validate_base64_bytes(value: str, *, field_name: str, size: int) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{field_name} must be valid base64") from error
    if len(decoded) != size:
        raise ValueError(f"{field_name} must decode to {size} bytes")
    return value


class P12ReadinessPolicy(DomainModel):
    version: str = Field(min_length=1, max_length=80)
    candidate_id: str = Field(min_length=1, max_length=160)
    strategy_id: str = Field(min_length=1, max_length=160)
    forward_proof_policy_sha256: str
    integrated_decision_sha256: str
    risk_policy_sha256: str
    approved_at: UtcDateTime
    effective_from: UtcDateTime
    minimum_testnet_soak_seconds: int = Field(ge=3600, le=604800)
    minimum_accepted_order_count: int = Field(ge=1, le=1_000_000)
    minimum_terminal_order_count: int = Field(ge=1, le=1_000_000)
    minimum_fill_count: int = Field(ge=1, le=10_000_000)
    trusted_attestor_id: str = Field(min_length=1, max_length=160)
    trusted_attestor_key_id: str = Field(min_length=1, max_length=160)
    trusted_attestor_public_key_base64: str
    trusted_timestamp_authority_id: str = Field(min_length=1, max_length=160)
    trusted_timestamp_key_id: str = Field(min_length=1, max_length=160)
    trusted_timestamp_public_key_base64: str
    thresholds_locked_before_run: Literal[True] = True
    weighted_score_allowed: Literal[False] = False
    automatic_live_unlock_allowed: Literal[False] = False
    final_holdout_opened: Literal[False] = False
    policy_sha256: str

    @field_validator(
        "trusted_attestor_public_key_base64",
        "trusted_timestamp_public_key_base64",
    )
    @classmethod
    def validate_public_key(cls, value: str) -> str:
        return _validate_base64_bytes(
            value,
            field_name="trusted attestor public key",
            size=32,
        )

    @field_validator("policy_sha256")
    @classmethod
    def validate_policy_hash(cls, value: str) -> str:
        return _validate_hash(value, "P12 readiness policy hash")

    @field_validator(
        "forward_proof_policy_sha256",
        "integrated_decision_sha256",
        "risk_policy_sha256",
    )
    @classmethod
    def validate_forward_policy_hash(cls, value: str) -> str:
        return _validate_hash(value, "P11 forward proof policy hash")

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.approved_at > self.effective_from:
            raise ValueError("AQ-P12-READINESS-POLICY-NOT-PRECOMMITTED")
        if self.minimum_terminal_order_count > self.minimum_accepted_order_count:
            raise ValueError("terminal-order threshold cannot exceed accepted-order threshold")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        if self.policy_sha256 != expected:
            raise ValueError("AQ-P12-READINESS-POLICY-HASH-MISMATCH")
        return self


def create_p12_readiness_policy(
    *,
    version: str,
    candidate_id: str,
    strategy_id: str,
    forward_proof_policy_sha256: str,
    integrated_decision_sha256: str,
    risk_policy_sha256: str,
    approved_at: UtcDateTime,
    effective_from: UtcDateTime,
    minimum_testnet_soak_seconds: int,
    minimum_accepted_order_count: int,
    minimum_terminal_order_count: int,
    minimum_fill_count: int,
    trusted_attestor_id: str,
    trusted_attestor_key_id: str,
    trusted_attestor_public_key_base64: str,
    trusted_timestamp_authority_id: str,
    trusted_timestamp_key_id: str,
    trusted_timestamp_public_key_base64: str,
) -> P12ReadinessPolicy:
    payload = {
        "version": version,
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "forward_proof_policy_sha256": forward_proof_policy_sha256,
        "integrated_decision_sha256": integrated_decision_sha256,
        "risk_policy_sha256": risk_policy_sha256,
        "approved_at": approved_at,
        "effective_from": effective_from,
        "minimum_testnet_soak_seconds": minimum_testnet_soak_seconds,
        "minimum_accepted_order_count": minimum_accepted_order_count,
        "minimum_terminal_order_count": minimum_terminal_order_count,
        "minimum_fill_count": minimum_fill_count,
        "trusted_attestor_id": trusted_attestor_id,
        "trusted_attestor_key_id": trusted_attestor_key_id,
        "trusted_attestor_public_key_base64": trusted_attestor_public_key_base64,
        "trusted_timestamp_authority_id": trusted_timestamp_authority_id,
        "trusted_timestamp_key_id": trusted_timestamp_key_id,
        "trusted_timestamp_public_key_base64": trusted_timestamp_public_key_base64,
        "thresholds_locked_before_run": True,
        "weighted_score_allowed": False,
        "automatic_live_unlock_allowed": False,
        "final_holdout_opened": False,
    }
    return cast(
        "P12ReadinessPolicy",
        _hashed_model(P12ReadinessPolicy, payload, "policy_sha256"),
    )


class TestnetReconciliationReceipt(DomainModel):
    run_id: str = Field(min_length=1, max_length=160)
    account_scope_id: str = Field(min_length=1, max_length=160)
    started_at: UtcDateTime
    completed_at: UtcDateTime
    venue_order_count: int = Field(ge=0, le=1_000_000)
    internal_order_count: int = Field(ge=0, le=1_000_000)
    venue_fill_count: int = Field(ge=0, le=10_000_000)
    ledger_fill_count: int = Field(ge=0, le=10_000_000)
    read_model_fill_count: int = Field(ge=0, le=10_000_000)
    unmatched_order_count: int = Field(ge=0)
    unmatched_fill_count: int = Field(ge=0)
    balance_difference_count: int = Field(ge=0)
    sequence_gap_count: int = Field(ge=0)
    unresolved_unknown_order_count: int = Field(ge=0)
    authoritative_facts_mutated: Literal[False] = False
    reconciled: bool
    receipt_sha256: str

    @field_validator("receipt_sha256")
    @classmethod
    def validate_receipt_hash(cls, value: str) -> str:
        return _validate_hash(value, "Testnet reconciliation receipt hash")

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("reconciliation cannot complete before it starts")
        expected_reconciled = (
            self.venue_order_count == self.internal_order_count
            and self.venue_fill_count == self.ledger_fill_count == self.read_model_fill_count
            and self.unmatched_order_count == 0
            and self.unmatched_fill_count == 0
            and self.balance_difference_count == 0
            and self.sequence_gap_count == 0
            and self.unresolved_unknown_order_count == 0
        )
        if self.reconciled is not expected_reconciled:
            raise ValueError("AQ-P12-RECONCILIATION-RESULT-MISMATCH")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("AQ-P12-RECONCILIATION-HASH-MISMATCH")
        return self


def create_testnet_reconciliation_receipt(
    *,
    run_id: str,
    account_scope_id: str,
    started_at: UtcDateTime,
    completed_at: UtcDateTime,
    venue_order_count: int,
    internal_order_count: int,
    venue_fill_count: int,
    ledger_fill_count: int,
    read_model_fill_count: int,
    unmatched_order_count: int = 0,
    unmatched_fill_count: int = 0,
    balance_difference_count: int = 0,
    sequence_gap_count: int = 0,
    unresolved_unknown_order_count: int = 0,
) -> TestnetReconciliationReceipt:
    payload = {
        "run_id": run_id,
        "account_scope_id": account_scope_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "venue_order_count": venue_order_count,
        "internal_order_count": internal_order_count,
        "venue_fill_count": venue_fill_count,
        "ledger_fill_count": ledger_fill_count,
        "read_model_fill_count": read_model_fill_count,
        "unmatched_order_count": unmatched_order_count,
        "unmatched_fill_count": unmatched_fill_count,
        "balance_difference_count": balance_difference_count,
        "sequence_gap_count": sequence_gap_count,
        "unresolved_unknown_order_count": unresolved_unknown_order_count,
        "authoritative_facts_mutated": False,
        "reconciled": (
            venue_order_count == internal_order_count
            and venue_fill_count == ledger_fill_count == read_model_fill_count
            and unmatched_order_count == 0
            and unmatched_fill_count == 0
            and balance_difference_count == 0
            and sequence_gap_count == 0
            and unresolved_unknown_order_count == 0
        ),
    }
    return cast(
        "TestnetReconciliationReceipt",
        _hashed_model(TestnetReconciliationReceipt, payload, "receipt_sha256"),
    )


class BinanceTestnetRunEvidence(DomainModel):
    evidence_tier: EvidenceTier
    origin: TestnetEvidenceOrigin
    candidate_id: str = Field(min_length=1, max_length=160)
    strategy_id: str = Field(min_length=1, max_length=160)
    forward_pair_id: str = Field(min_length=1, max_length=160)
    forward_proof_sha256: str
    run_id: str = Field(min_length=1, max_length=160)
    venue_id: Literal["BINANCE-TESTNET"] = "BINANCE-TESTNET"
    environment: Literal["TESTNET"] = "TESTNET"
    account_scope_id: str = Field(min_length=1, max_length=160)
    credential_reference_id: str | None = Field(default=None, max_length=240)
    raw_credential_included: Literal[False] = False
    started_at: UtcDateTime
    ended_at: UtcDateTime
    time_compressed: bool
    simulator_used: bool
    network_request_count: int = Field(ge=0, le=10_000_000)
    private_api_authenticated: bool
    testnet_account_verified: bool
    live_domain_used: Literal[False] = False
    live_account_connected: Literal[False] = False
    withdrawals_enabled: Literal[False] = False
    accepted_order_count: int = Field(ge=0, le=1_000_000)
    terminal_order_count: int = Field(ge=0, le=1_000_000)
    fill_count: int = Field(ge=0, le=10_000_000)
    unresolved_unknown_order_count: int = Field(ge=0)
    source_request_sha256: str
    source_response_sha256: str
    reconciliation: TestnetReconciliationReceipt
    evidence_sha256: str

    @field_validator(
        "forward_proof_sha256",
        "source_request_sha256",
        "source_response_sha256",
        "evidence_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _validate_hash(value, "Binance Testnet evidence hash")

    @model_validator(mode="after")
    def validate_testnet_evidence(self) -> Self:
        if self.ended_at <= self.started_at:
            raise ValueError("Testnet run must have positive wall-clock duration")
        if self.terminal_order_count > self.accepted_order_count:
            raise ValueError("terminal orders cannot exceed accepted orders")
        if (
            self.reconciliation.venue_order_count != self.accepted_order_count
            or self.reconciliation.internal_order_count != self.accepted_order_count
            or self.reconciliation.venue_fill_count != self.fill_count
            or self.reconciliation.ledger_fill_count != self.fill_count
            or self.reconciliation.read_model_fill_count != self.fill_count
            or self.reconciliation.unresolved_unknown_order_count
            != self.unresolved_unknown_order_count
        ):
            raise ValueError("AQ-P12-TESTNET-RECONCILIATION-COUNT-MISMATCH")
        if (
            self.reconciliation.run_id != self.run_id
            or self.reconciliation.account_scope_id != self.account_scope_id
            or self.reconciliation.started_at < self.started_at
            or self.reconciliation.completed_at > self.ended_at
        ):
            raise ValueError("AQ-P12-TESTNET-RECONCILIATION-SPLICE")
        real = self.origin is TestnetEvidenceOrigin.REAL_BINANCE_TESTNET
        if real:
            if (
                self.evidence_tier is not EvidenceTier.TESTNET_FORWARD
                or self.time_compressed
                or self.simulator_used
                or self.network_request_count == 0
                or not self.private_api_authenticated
                or not self.testnet_account_verified
                or not self.credential_reference_id
            ):
                raise ValueError("AQ-P12-REAL-TESTNET-EVIDENCE-INCONSISTENT")
        elif (
            self.evidence_tier is not EvidenceTier.DEVELOPMENT
            or not self.simulator_used
            or self.network_request_count != 0
            or self.private_api_authenticated
            or self.testnet_account_verified
            or self.credential_reference_id is not None
        ):
            raise ValueError("AQ-P12-SIMULATOR-EVIDENCE-INCONSISTENT")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"evidence_sha256"}))
        if self.evidence_sha256 != expected:
            raise ValueError("AQ-P12-TESTNET-EVIDENCE-HASH-MISMATCH")
        return self


def create_binance_testnet_run_evidence(
    *,
    evidence_tier: EvidenceTier,
    origin: TestnetEvidenceOrigin,
    candidate_id: str,
    strategy_id: str,
    forward_pair_id: str,
    forward_proof_sha256: str,
    run_id: str,
    account_scope_id: str,
    credential_reference_id: str | None,
    started_at: UtcDateTime,
    ended_at: UtcDateTime,
    time_compressed: bool,
    simulator_used: bool,
    network_request_count: int,
    private_api_authenticated: bool,
    testnet_account_verified: bool,
    accepted_order_count: int,
    terminal_order_count: int,
    fill_count: int,
    unresolved_unknown_order_count: int,
    source_request_sha256: str,
    source_response_sha256: str,
    reconciliation: TestnetReconciliationReceipt,
) -> BinanceTestnetRunEvidence:
    payload = {
        "evidence_tier": evidence_tier,
        "origin": origin,
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "forward_pair_id": forward_pair_id,
        "forward_proof_sha256": forward_proof_sha256,
        "run_id": run_id,
        "venue_id": "BINANCE-TESTNET",
        "environment": "TESTNET",
        "account_scope_id": account_scope_id,
        "credential_reference_id": credential_reference_id,
        "raw_credential_included": False,
        "started_at": started_at,
        "ended_at": ended_at,
        "time_compressed": time_compressed,
        "simulator_used": simulator_used,
        "network_request_count": network_request_count,
        "private_api_authenticated": private_api_authenticated,
        "testnet_account_verified": testnet_account_verified,
        "live_domain_used": False,
        "live_account_connected": False,
        "withdrawals_enabled": False,
        "accepted_order_count": accepted_order_count,
        "terminal_order_count": terminal_order_count,
        "fill_count": fill_count,
        "unresolved_unknown_order_count": unresolved_unknown_order_count,
        "source_request_sha256": source_request_sha256,
        "source_response_sha256": source_response_sha256,
        "reconciliation": reconciliation,
    }
    return cast(
        "BinanceTestnetRunEvidence",
        _hashed_model(BinanceTestnetRunEvidence, payload, "evidence_sha256"),
    )


class ExternalAlertDeliveryReceipt(DomainModel):
    evidence_tier: EvidenceTier
    destination_kind: AlertDestinationKind
    candidate_id: str = Field(min_length=1, max_length=160)
    strategy_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    account_scope_id: str = Field(min_length=1, max_length=160)
    alert_event_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=160)
    destination_id: str = Field(min_length=1, max_length=240)
    attempted_at: UtcDateTime
    acknowledged_at: UtcDateTime | None
    attempted_channel_count: int = Field(ge=1, le=1000)
    delivered_channel_count: int = Field(ge=0, le=1000)
    https_transport: bool
    loopback_destination: bool
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    payload_sha256: str
    acknowledgment_sha256: str | None
    remote_acknowledged: bool
    durable_receipt_persisted: bool
    immutable_audit_anchor_present: bool
    receipt_sha256: str

    @field_validator("payload_sha256", "acknowledgment_sha256", "receipt_sha256")
    @classmethod
    def validate_hashes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_hash(value, "alert delivery hash")

    @model_validator(mode="after")
    def validate_delivery(self) -> Self:
        if self.delivered_channel_count > self.attempted_channel_count:
            raise ValueError("delivered channels cannot exceed attempted channels")
        external = self.destination_kind is AlertDestinationKind.EXTERNAL_NON_LOOPBACK
        if external != (not self.loopback_destination):
            raise ValueError("AQ-P12-ALERT-DESTINATION-KIND-MISMATCH")
        if external and self.evidence_tier is not EvidenceTier.TESTNET_FORWARD:
            raise ValueError("external alert receipt requires TESTNET_FORWARD evidence tier")
        if not external and self.evidence_tier is not EvidenceTier.DEVELOPMENT:
            raise ValueError("loopback alert receipt is DEVELOPMENT evidence")
        if self.remote_acknowledged:
            if (
                self.acknowledged_at is None
                or self.acknowledged_at < self.attempted_at
                or self.http_status_code is None
                or not 200 <= self.http_status_code < 300
                or self.acknowledgment_sha256 is None
                or self.delivered_channel_count != self.attempted_channel_count
            ):
                raise ValueError("AQ-P12-ALERT-ACKNOWLEDGMENT-INCONSISTENT")
        elif self.acknowledged_at is not None or self.acknowledgment_sha256 is not None:
            raise ValueError("failed alert delivery cannot carry an acknowledgment")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("AQ-P12-ALERT-RECEIPT-HASH-MISMATCH")
        return self


def create_external_alert_delivery_receipt(
    *,
    evidence_tier: EvidenceTier,
    destination_kind: AlertDestinationKind,
    candidate_id: str,
    strategy_id: str,
    run_id: str,
    account_scope_id: str,
    alert_event_id: str,
    correlation_id: str,
    destination_id: str,
    attempted_at: UtcDateTime,
    acknowledged_at: UtcDateTime | None,
    attempted_channel_count: int,
    delivered_channel_count: int,
    https_transport: bool,
    loopback_destination: bool,
    http_status_code: int | None,
    payload_sha256: str,
    acknowledgment_sha256: str | None,
    remote_acknowledged: bool,
    durable_receipt_persisted: bool,
    immutable_audit_anchor_present: bool,
) -> ExternalAlertDeliveryReceipt:
    payload = {
        "evidence_tier": evidence_tier,
        "destination_kind": destination_kind,
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "run_id": run_id,
        "account_scope_id": account_scope_id,
        "alert_event_id": alert_event_id,
        "correlation_id": correlation_id,
        "destination_id": destination_id,
        "attempted_at": attempted_at,
        "acknowledged_at": acknowledged_at,
        "attempted_channel_count": attempted_channel_count,
        "delivered_channel_count": delivered_channel_count,
        "https_transport": https_transport,
        "loopback_destination": loopback_destination,
        "http_status_code": http_status_code,
        "payload_sha256": payload_sha256,
        "acknowledgment_sha256": acknowledgment_sha256,
        "remote_acknowledged": remote_acknowledged,
        "durable_receipt_persisted": durable_receipt_persisted,
        "immutable_audit_anchor_present": immutable_audit_anchor_present,
    }
    return cast(
        "ExternalAlertDeliveryReceipt",
        _hashed_model(ExternalAlertDeliveryReceipt, payload, "receipt_sha256"),
    )


class TestnetRiskAuthorizationReceipt(DomainModel):
    evidence_tier: EvidenceTier
    candidate_id: str = Field(min_length=1, max_length=160)
    strategy_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    account_scope_id: str = Field(min_length=1, max_length=160)
    issued_at: UtcDateTime
    expires_at: UtcDateTime
    readiness_policy_sha256: str
    integrated_decision_sha256: str
    risk_policy_sha256: str
    risk_snapshot_sha256: str
    testnet_evidence_sha256: str
    reconciliation_receipt_sha256: str
    external_alert_receipt_sha256: str
    drawdown_pass: bool
    margin_pass: bool
    liquidity_pass: bool
    venue_pass: bool
    security_pass: bool
    event_risk_pass: bool
    reconciliation_pass: bool
    testnet_order_authorized: bool
    authorization_scope: Literal["TESTNET_ONLY"] = "TESTNET_ONLY"
    live_order_authorized: Literal[False] = False
    manual_live_unlock_received: Literal[False] = False
    receipt_sha256: str

    @field_validator(
        "readiness_policy_sha256",
        "integrated_decision_sha256",
        "risk_policy_sha256",
        "risk_snapshot_sha256",
        "testnet_evidence_sha256",
        "reconciliation_receipt_sha256",
        "external_alert_receipt_sha256",
        "receipt_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _validate_hash(value, "Testnet risk authorization hash")

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("risk authorization must have a positive validity window")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("AQ-P12-RISK-AUTHORIZATION-HASH-MISMATCH")
        return self


def create_testnet_risk_authorization_receipt(
    *,
    evidence_tier: EvidenceTier,
    candidate_id: str,
    strategy_id: str,
    run_id: str,
    account_scope_id: str,
    issued_at: UtcDateTime,
    expires_at: UtcDateTime,
    readiness_policy_sha256: str,
    integrated_decision_sha256: str,
    risk_policy_sha256: str,
    risk_snapshot_sha256: str,
    testnet_evidence_sha256: str,
    reconciliation_receipt_sha256: str,
    external_alert_receipt_sha256: str,
    drawdown_pass: bool,
    margin_pass: bool,
    liquidity_pass: bool,
    venue_pass: bool,
    security_pass: bool,
    event_risk_pass: bool,
    reconciliation_pass: bool,
    testnet_order_authorized: bool,
) -> TestnetRiskAuthorizationReceipt:
    payload = {
        "evidence_tier": evidence_tier,
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "run_id": run_id,
        "account_scope_id": account_scope_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "readiness_policy_sha256": readiness_policy_sha256,
        "integrated_decision_sha256": integrated_decision_sha256,
        "risk_policy_sha256": risk_policy_sha256,
        "risk_snapshot_sha256": risk_snapshot_sha256,
        "testnet_evidence_sha256": testnet_evidence_sha256,
        "reconciliation_receipt_sha256": reconciliation_receipt_sha256,
        "external_alert_receipt_sha256": external_alert_receipt_sha256,
        "drawdown_pass": drawdown_pass,
        "margin_pass": margin_pass,
        "liquidity_pass": liquidity_pass,
        "venue_pass": venue_pass,
        "security_pass": security_pass,
        "event_risk_pass": event_risk_pass,
        "reconciliation_pass": reconciliation_pass,
        "testnet_order_authorized": testnet_order_authorized,
        "authorization_scope": "TESTNET_ONLY",
        "live_order_authorized": False,
        "manual_live_unlock_received": False,
    }
    return cast(
        "TestnetRiskAuthorizationReceipt",
        _hashed_model(TestnetRiskAuthorizationReceipt, payload, "receipt_sha256"),
    )


class ProtectedTimestampReceipt(DomainModel):
    evidence_sha256: str
    authority_id: str = Field(min_length=1, max_length=160)
    key_id: str = Field(min_length=1, max_length=160)
    timestamped_at: UtcDateTime
    nonce_sha256: str
    signature_base64: str
    receipt_sha256: str

    @field_validator("evidence_sha256", "nonce_sha256", "receipt_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _validate_hash(value, "protected timestamp hash")

    @field_validator("signature_base64")
    @classmethod
    def validate_signature(cls, value: str) -> str:
        return _validate_base64_bytes(
            value,
            field_name="timestamp authority Ed25519 signature",
            size=64,
        )

    @model_validator(mode="after")
    def validate_receipt_hash(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("AQ-P12-PROTECTED-TIMESTAMP-HASH-MISMATCH")
        return self


def _timestamp_message(
    *,
    evidence_sha256: str,
    authority_id: str,
    key_id: str,
    timestamped_at: datetime,
    nonce_sha256: str,
) -> bytes:
    return canonical_json_bytes(
        {
            "evidence_sha256": evidence_sha256,
            "authority_id": authority_id,
            "key_id": key_id,
            "timestamped_at": timestamped_at.isoformat().replace("+00:00", "Z"),
            "nonce_sha256": nonce_sha256,
        }
    )


def create_protected_timestamp_receipt(
    *,
    evidence_sha256: str,
    authority_id: str,
    key_id: str,
    timestamped_at: UtcDateTime,
    nonce_sha256: str,
    private_key: Ed25519PrivateKey,
) -> ProtectedTimestampReceipt:
    message = _timestamp_message(
        evidence_sha256=evidence_sha256,
        authority_id=authority_id,
        key_id=key_id,
        timestamped_at=timestamped_at,
        nonce_sha256=nonce_sha256,
    )
    payload = {
        "evidence_sha256": evidence_sha256,
        "authority_id": authority_id,
        "key_id": key_id,
        "timestamped_at": timestamped_at,
        "nonce_sha256": nonce_sha256,
        "signature_base64": base64.b64encode(private_key.sign(message)).decode("ascii"),
    }
    return cast(
        "ProtectedTimestampReceipt",
        _hashed_model(ProtectedTimestampReceipt, payload, "receipt_sha256"),
    )


def verify_protected_timestamp_receipt(
    receipt: ProtectedTimestampReceipt,
    policy: P12ReadinessPolicy,
) -> bool:
    validated = ProtectedTimestampReceipt.model_validate_json(receipt.model_dump_json())
    validated_policy = P12ReadinessPolicy.model_validate_json(policy.model_dump_json())
    if (
        validated.authority_id != validated_policy.trusted_timestamp_authority_id
        or validated.key_id != validated_policy.trusted_timestamp_key_id
    ):
        return False
    message = _timestamp_message(
        evidence_sha256=validated.evidence_sha256,
        authority_id=validated.authority_id,
        key_id=validated.key_id,
        timestamped_at=validated.timestamped_at,
        nonce_sha256=validated.nonce_sha256,
    )
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(
                validated_policy.trusted_timestamp_public_key_base64,
                validate=True,
            )
        )
        public_key.verify(
            base64.b64decode(validated.signature_base64, validate=True),
            message,
        )
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


class P12EvidenceAttestation(DomainModel):
    evidence_kind: AttestedEvidenceKind
    evidence_sha256: str
    attestor_id: str = Field(min_length=1, max_length=160)
    key_id: str = Field(min_length=1, max_length=160)
    signed_at: UtcDateTime
    protected_timestamp: ProtectedTimestampReceipt
    signature_base64: str
    signature_purpose: Literal["EVIDENCE_INTEGRITY_ONLY"] = "EVIDENCE_INTEGRITY_ONLY"
    private_key_persisted: Literal[False] = False
    live_authorization_capability: Literal[False] = False
    attestation_sha256: str

    @field_validator("evidence_sha256", "attestation_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _validate_hash(value, "P12 attestation hash")

    @field_validator("signature_base64")
    @classmethod
    def validate_signature(cls, value: str) -> str:
        return _validate_base64_bytes(value, field_name="P12 Ed25519 signature", size=64)

    @model_validator(mode="after")
    def validate_attestation_hash(self) -> Self:
        if (
            self.protected_timestamp.evidence_sha256 != self.evidence_sha256
            or self.signed_at < self.protected_timestamp.timestamped_at
        ):
            raise ValueError("AQ-P12-ATTESTATION-TIMESTAMP-SPLICE")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"attestation_sha256"}))
        if self.attestation_sha256 != expected:
            raise ValueError("AQ-P12-ATTESTATION-HASH-MISMATCH")
        return self


def _attestation_message(
    *,
    evidence_kind: AttestedEvidenceKind,
    evidence_sha256: str,
    attestor_id: str,
    key_id: str,
    signed_at: datetime,
    protected_timestamp_receipt_sha256: str,
) -> bytes:
    return canonical_json_bytes(
        {
            "evidence_kind": evidence_kind,
            "evidence_sha256": evidence_sha256,
            "attestor_id": attestor_id,
            "key_id": key_id,
            "signed_at": signed_at.isoformat().replace("+00:00", "Z"),
            "protected_timestamp_receipt_sha256": protected_timestamp_receipt_sha256,
            "signature_purpose": "EVIDENCE_INTEGRITY_ONLY",
            "private_key_persisted": False,
            "live_authorization_capability": False,
        }
    )


def create_p12_evidence_attestation(
    *,
    evidence_kind: AttestedEvidenceKind,
    evidence_sha256: str,
    attestor_id: str,
    key_id: str,
    signed_at: UtcDateTime,
    protected_timestamp: ProtectedTimestampReceipt,
    private_key: Ed25519PrivateKey,
) -> P12EvidenceAttestation:
    message = _attestation_message(
        evidence_kind=evidence_kind,
        evidence_sha256=evidence_sha256,
        attestor_id=attestor_id,
        key_id=key_id,
        signed_at=signed_at,
        protected_timestamp_receipt_sha256=protected_timestamp.receipt_sha256,
    )
    payload = {
        "evidence_kind": evidence_kind,
        "evidence_sha256": evidence_sha256,
        "attestor_id": attestor_id,
        "key_id": key_id,
        "signed_at": signed_at,
        "protected_timestamp": protected_timestamp,
        "signature_base64": base64.b64encode(private_key.sign(message)).decode("ascii"),
        "signature_purpose": "EVIDENCE_INTEGRITY_ONLY",
        "private_key_persisted": False,
        "live_authorization_capability": False,
    }
    return cast(
        "P12EvidenceAttestation",
        _hashed_model(P12EvidenceAttestation, payload, "attestation_sha256"),
    )


def verify_p12_evidence_attestation(
    attestation: P12EvidenceAttestation,
    policy: P12ReadinessPolicy,
) -> bool:
    validated = P12EvidenceAttestation.model_validate_json(attestation.model_dump_json())
    validated_policy = P12ReadinessPolicy.model_validate_json(policy.model_dump_json())
    if (
        validated.attestor_id != validated_policy.trusted_attestor_id
        or validated.key_id != validated_policy.trusted_attestor_key_id
        or not verify_protected_timestamp_receipt(
            validated.protected_timestamp,
            validated_policy,
        )
    ):
        return False
    message = _attestation_message(
        evidence_kind=validated.evidence_kind,
        evidence_sha256=validated.evidence_sha256,
        attestor_id=validated.attestor_id,
        key_id=validated.key_id,
        signed_at=validated.signed_at,
        protected_timestamp_receipt_sha256=validated.protected_timestamp.receipt_sha256,
    )
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(
                validated_policy.trusted_attestor_public_key_base64,
                validate=True,
            )
        )
        public_key.verify(
            base64.b64decode(validated.signature_base64, validate=True),
            message,
        )
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


class P12EvidenceBundle(DomainModel):
    forward_proof: PaperShadowForwardProof
    testnet: BinanceTestnetRunEvidence | None = None
    testnet_attestation: P12EvidenceAttestation | None = None
    external_alert: ExternalAlertDeliveryReceipt | None = None
    external_alert_attestation: P12EvidenceAttestation | None = None
    risk_authorization: TestnetRiskAuthorizationReceipt | None = None
    risk_attestation: P12EvidenceAttestation | None = None
    source_artifact_sha256: Annotated[dict[str, str], Field(min_length=1, max_length=64)]
    bundle_sha256: str

    @field_validator("source_artifact_sha256")
    @classmethod
    def validate_paths(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not path
            or len(path) > 512
            or path.startswith(("/", "\\"))
            or "\\" in path
            or ".." in path.split("/")
            or ":" in path.split("/", maxsplit=1)[0]
            for path in value
        ):
            raise ValueError("AQ-P12-UNSAFE-EVIDENCE-PATH")
        for digest in value.values():
            _validate_hash(digest, "P12 source artifact hash")
        return value

    @field_validator("bundle_sha256")
    @classmethod
    def validate_bundle_hash(cls, value: str) -> str:
        return _validate_hash(value, "P12 evidence bundle hash")

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        pairs = (
            (
                self.testnet,
                self.testnet_attestation,
                AttestedEvidenceKind.BINANCE_TESTNET_RUN,
                "evidence_sha256",
            ),
            (
                self.external_alert,
                self.external_alert_attestation,
                AttestedEvidenceKind.EXTERNAL_ALERT_DELIVERY,
                "receipt_sha256",
            ),
            (
                self.risk_authorization,
                self.risk_attestation,
                AttestedEvidenceKind.TESTNET_RISK_AUTHORIZATION,
                "receipt_sha256",
            ),
        )
        for evidence, attestation, kind, hash_field in pairs:
            if attestation is not None and evidence is None:
                raise ValueError("AQ-P12-ORPHAN-EVIDENCE-ATTESTATION")
            if evidence is not None and attestation is not None:
                evidence_hash = cast("str", getattr(evidence, hash_field))
                if (
                    attestation.evidence_kind is not kind
                    or attestation.evidence_sha256 != evidence_hash
                ):
                    raise ValueError("AQ-P12-EVIDENCE-ATTESTATION-SPLICE")
        if self.risk_authorization is not None:
            if self.testnet is None or self.external_alert is None:
                raise ValueError("risk authorization requires Testnet and alert evidence")
            risk = self.risk_authorization
            if (
                risk.candidate_id != self.testnet.candidate_id
                or risk.strategy_id != self.testnet.strategy_id
                or self.external_alert.candidate_id != self.testnet.candidate_id
                or self.external_alert.strategy_id != self.testnet.strategy_id
                or self.external_alert.run_id != self.testnet.run_id
                or self.external_alert.account_scope_id != self.testnet.account_scope_id
                or self.testnet.forward_proof_sha256 != self.forward_proof.proof_sha256
                or self.testnet.forward_pair_id != self.forward_proof.paper.session.pair_id
                or risk.run_id != self.testnet.run_id
                or risk.account_scope_id != self.testnet.account_scope_id
                or risk.testnet_evidence_sha256 != self.testnet.evidence_sha256
                or risk.reconciliation_receipt_sha256 != self.testnet.reconciliation.receipt_sha256
                or risk.external_alert_receipt_sha256 != self.external_alert.receipt_sha256
            ):
                raise ValueError("AQ-P12-RISK-EVIDENCE-SPLICE")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"bundle_sha256"}))
        if self.bundle_sha256 != expected:
            raise ValueError("AQ-P12-EVIDENCE-BUNDLE-HASH-MISMATCH")
        return self


def create_p12_evidence_bundle(
    *,
    forward_proof: PaperShadowForwardProof,
    source_artifact_sha256: dict[str, str],
    testnet: BinanceTestnetRunEvidence | None = None,
    testnet_attestation: P12EvidenceAttestation | None = None,
    external_alert: ExternalAlertDeliveryReceipt | None = None,
    external_alert_attestation: P12EvidenceAttestation | None = None,
    risk_authorization: TestnetRiskAuthorizationReceipt | None = None,
    risk_attestation: P12EvidenceAttestation | None = None,
) -> P12EvidenceBundle:
    payload = {
        "forward_proof": forward_proof,
        "testnet": testnet,
        "testnet_attestation": testnet_attestation,
        "external_alert": external_alert,
        "external_alert_attestation": external_alert_attestation,
        "risk_authorization": risk_authorization,
        "risk_attestation": risk_attestation,
        "source_artifact_sha256": source_artifact_sha256,
    }
    return cast(
        "P12EvidenceBundle",
        _hashed_model(P12EvidenceBundle, payload, "bundle_sha256"),
    )


class P12GateResult(DomainModel):
    gate: P12GateName
    status: P12GateStatus
    evidence_sha256: Annotated[tuple[str, ...], Field(min_length=1, max_length=16)]
    reason_codes: Annotated[tuple[ReasonCode, ...], Field(max_length=32)]

    @field_validator("evidence_sha256")
    @classmethod
    def validate_evidence_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("gate evidence hashes must be unique")
        return tuple(_validate_hash(item, "P12 gate evidence hash") for item in value)

    @model_validator(mode="after")
    def validate_status_reasons(self) -> Self:
        if self.status is P12GateStatus.PASS and self.reason_codes:
            raise ValueError("passed P12 gate cannot carry failure reasons")
        if self.status is not P12GateStatus.PASS and not self.reason_codes:
            raise ValueError("non-passed P12 gate requires reason codes")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("P12 gate reasons must be unique and sorted")
        return self


def _gate(
    gate: P12GateName,
    status: P12GateStatus,
    evidence_sha256: tuple[str, ...],
    *reason_codes: str,
) -> P12GateResult:
    return P12GateResult(
        gate=gate,
        status=status,
        evidence_sha256=tuple(dict.fromkeys(evidence_sha256)),
        reason_codes=tuple(sorted(set(reason_codes))),
    )


def _calibration_gate(
    *,
    gate: P12GateName,
    proof: PaperShadowForwardProof,
    calibration_pass: bool,
) -> P12GateResult:
    evidence = (proof.proof_sha256, proof.paper.report_sha256, proof.shadow.report_sha256)
    real_forward = all(
        report.session.run_kind is ForwardRunKind.WALL_CLOCK_FORWARD
        for report in (proof.paper, proof.shadow)
    )
    if not real_forward:
        return _gate(
            gate,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence,
            f"REAL_{gate.value}_FORWARD_EVIDENCE_ABSENT",
        )
    if not calibration_pass:
        return _gate(
            gate,
            P12GateStatus.FAIL,
            evidence,
            f"{gate.value}_FAILED",
        )
    return _gate(gate, P12GateStatus.PASS, evidence)


def _forward_gate(
    *,
    gate: P12GateName,
    report_mode: ForwardMode,
    proof: PaperShadowForwardProof,
) -> P12GateResult:
    report = proof.paper if report_mode is ForwardMode.PAPER else proof.shadow
    evidence = (proof.proof_sha256, report.report_sha256)
    if report.session.run_kind is not ForwardRunKind.WALL_CLOCK_FORWARD:
        return _gate(
            gate,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence,
            f"REAL_{gate.value}_FORWARD_EVIDENCE_ABSENT",
        )
    if report.status is ForwardProofStatus.FAIL_CLOSED:
        return _gate(
            gate,
            P12GateStatus.FAIL,
            evidence,
            f"{gate.value}_FORWARD_FAILED",
        )
    if report.status is ForwardProofStatus.EXTEND_PAPER:
        return _gate(
            gate,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence,
            f"{gate.value}_FORWARD_INSUFFICIENT",
        )
    return _gate(gate, P12GateStatus.PASS, evidence)


def _testnet_gate(
    *,
    policy: P12ReadinessPolicy,
    bundle: P12EvidenceBundle,
    assessed_at: datetime,
) -> P12GateResult:
    evidence_hashes = (bundle.bundle_sha256, policy.policy_sha256)
    run = bundle.testnet
    attestation = bundle.testnet_attestation
    if run is None:
        return _gate(
            P12GateName.TESTNET,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence_hashes,
            "REAL_BINANCE_TESTNET_EVIDENCE_ABSENT",
        )
    evidence_hashes += (run.evidence_sha256, run.reconciliation.receipt_sha256)
    if run.origin is not TestnetEvidenceOrigin.REAL_BINANCE_TESTNET:
        return _gate(
            P12GateName.TESTNET,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence_hashes,
            "SIMULATOR_IS_NOT_REAL_BINANCE_TESTNET",
        )
    if attestation is None:
        return _gate(
            P12GateName.TESTNET,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence_hashes,
            "TRUSTED_TESTNET_ATTESTATION_ABSENT",
        )
    evidence_hashes += (attestation.attestation_sha256,)
    if not verify_p12_evidence_attestation(attestation, policy):
        return _gate(
            P12GateName.TESTNET,
            P12GateStatus.FAIL,
            evidence_hashes,
            "TESTNET_ATTESTATION_INVALID",
        )
    elapsed = (run.ended_at - run.started_at).total_seconds()
    reasons: list[str] = []
    if policy.approved_at > run.started_at or policy.effective_from > run.started_at:
        reasons.append("READINESS_POLICY_NOT_EFFECTIVE_BEFORE_TESTNET_RUN")
    if (
        run.candidate_id != policy.candidate_id
        or run.strategy_id != policy.strategy_id
        or run.forward_proof_sha256 != bundle.forward_proof.proof_sha256
        or run.forward_pair_id != bundle.forward_proof.paper.session.pair_id
        or policy.forward_proof_policy_sha256 != bundle.forward_proof.paper.policy.policy_sha256
    ):
        reasons.append("TESTNET_FORWARD_CANDIDATE_BINDING_MISMATCH")
    if elapsed < policy.minimum_testnet_soak_seconds:
        reasons.append("TESTNET_SOAK_DURATION_INSUFFICIENT")
    if run.accepted_order_count < policy.minimum_accepted_order_count:
        reasons.append("TESTNET_ACCEPTED_ORDER_COUNT_INSUFFICIENT")
    if run.terminal_order_count < policy.minimum_terminal_order_count:
        reasons.append("TESTNET_TERMINAL_ORDER_COUNT_INSUFFICIENT")
    if run.fill_count < policy.minimum_fill_count:
        reasons.append("TESTNET_FILL_COUNT_INSUFFICIENT")
    if run.unresolved_unknown_order_count or not run.reconciliation.reconciled:
        reasons.append("TESTNET_RECONCILIATION_FAILED")
    if attestation.signed_at < run.ended_at:
        reasons.append("TESTNET_ATTESTATION_PREDATES_RUN_COMPLETION")
    if attestation.protected_timestamp.timestamped_at < run.ended_at:
        reasons.append("TESTNET_TIMESTAMP_PREDATES_RUN_COMPLETION")
    if (
        attestation.signed_at > assessed_at
        or attestation.protected_timestamp.timestamped_at > assessed_at
    ):
        reasons.append("TESTNET_ATTESTATION_IS_FUTURE_DATED")
    if reasons:
        return _gate(
            P12GateName.TESTNET,
            P12GateStatus.FAIL,
            evidence_hashes,
            *reasons,
        )
    return _gate(P12GateName.TESTNET, P12GateStatus.PASS, evidence_hashes)


def _risk_gate(
    *,
    policy: P12ReadinessPolicy,
    bundle: P12EvidenceBundle,
    testnet_gate: P12GateResult,
    assessed_at: datetime,
) -> P12GateResult:
    evidence_hashes = (bundle.bundle_sha256, policy.policy_sha256)
    alert = bundle.external_alert
    risk = bundle.risk_authorization
    if alert is None or risk is None:
        reasons = []
        if alert is None:
            reasons.append("EXTERNAL_ALERT_DELIVERY_EVIDENCE_ABSENT")
        if risk is None:
            reasons.append("SIGNED_TESTNET_RISK_AUTHORIZATION_ABSENT")
        if testnet_gate.status is not P12GateStatus.PASS:
            reasons.append("TESTNET_PREREQUISITE_NOT_MET")
        return _gate(
            P12GateName.RISK,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence_hashes,
            *reasons,
        )
    evidence_hashes += (alert.receipt_sha256, risk.receipt_sha256)
    alert_attestation = bundle.external_alert_attestation
    risk_attestation = bundle.risk_attestation
    if alert_attestation is None or risk_attestation is None:
        missing_attestations = tuple(
            reason
            for missing, reason in (
                (alert_attestation is None, "TRUSTED_ALERT_ATTESTATION_ABSENT"),
                (risk_attestation is None, "TRUSTED_RISK_ATTESTATION_ABSENT"),
            )
            if missing
        )
        return _gate(
            P12GateName.RISK,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence_hashes,
            *missing_attestations,
        )
    evidence_hashes += (
        alert_attestation.attestation_sha256,
        risk_attestation.attestation_sha256,
    )
    if not verify_p12_evidence_attestation(
        alert_attestation, policy
    ) or not verify_p12_evidence_attestation(risk_attestation, policy):
        return _gate(
            P12GateName.RISK,
            P12GateStatus.FAIL,
            evidence_hashes,
            "RISK_OR_ALERT_ATTESTATION_INVALID",
        )
    if (
        alert.destination_kind is not AlertDestinationKind.EXTERNAL_NON_LOOPBACK
        or alert.evidence_tier is not EvidenceTier.TESTNET_FORWARD
    ):
        return _gate(
            P12GateName.RISK,
            P12GateStatus.BLOCKED_EXTERNAL_INPUT,
            evidence_hashes,
            "LOOPBACK_ALERT_IS_NOT_EXTERNAL_DELIVERY",
        )
    reasons: list[str] = []
    if testnet_gate.status is not P12GateStatus.PASS:
        reasons.append("TESTNET_PREREQUISITE_NOT_MET")
    if (
        not alert.remote_acknowledged
        or not alert.https_transport
        or alert.loopback_destination
        or not alert.durable_receipt_persisted
        or not alert.immutable_audit_anchor_present
    ):
        reasons.append("EXTERNAL_ALERT_DELIVERY_FAILED")
    if alert.acknowledged_at is not None and alert_attestation.signed_at < alert.acknowledged_at:
        reasons.append("ALERT_ATTESTATION_PREDATES_ACKNOWLEDGMENT")
    if (
        alert.acknowledged_at is not None
        and alert_attestation.protected_timestamp.timestamped_at < alert.acknowledged_at
    ):
        reasons.append("ALERT_TIMESTAMP_PREDATES_ACKNOWLEDGMENT")
    if risk.evidence_tier is not EvidenceTier.TESTNET_FORWARD:
        reasons.append("RISK_AUTHORIZATION_NOT_TESTNET_FORWARD")
    if risk.readiness_policy_sha256 != policy.policy_sha256:
        reasons.append("RISK_POLICY_BINDING_MISMATCH")
    if (
        risk.integrated_decision_sha256 != policy.integrated_decision_sha256
        or risk.risk_policy_sha256 != policy.risk_policy_sha256
    ):
        reasons.append("RISK_DECISION_OR_POLICY_COMMITMENT_MISMATCH")
    if risk.candidate_id != policy.candidate_id or risk.strategy_id != policy.strategy_id:
        reasons.append("RISK_CANDIDATE_BINDING_MISMATCH")
    if bundle.testnet is None:
        reasons.append("TESTNET_EVIDENCE_ABSENT")
    else:
        if risk.issued_at > bundle.testnet.started_at or risk.expires_at < bundle.testnet.ended_at:
            reasons.append("RISK_AUTHORIZATION_WINDOW_INVALID")
    if risk.issued_at < policy.effective_from:
        reasons.append("RISK_AUTHORIZATION_PREDATES_POLICY")
    if risk_attestation.signed_at < risk.issued_at:
        reasons.append("RISK_ATTESTATION_PREDATES_AUTHORIZATION")
    if risk_attestation.protected_timestamp.timestamped_at < risk.issued_at:
        reasons.append("RISK_TIMESTAMP_PREDATES_AUTHORIZATION")
    if risk_attestation.signed_at > risk.expires_at:
        reasons.append("RISK_ATTESTATION_AFTER_AUTHORIZATION_EXPIRY")
    if (
        alert_attestation.signed_at > assessed_at
        or alert_attestation.protected_timestamp.timestamped_at > assessed_at
        or risk_attestation.signed_at > assessed_at
        or risk_attestation.protected_timestamp.timestamped_at > assessed_at
    ):
        reasons.append("RISK_OR_ALERT_ATTESTATION_IS_FUTURE_DATED")
    risk_checks = (
        risk.drawdown_pass,
        risk.margin_pass,
        risk.liquidity_pass,
        risk.venue_pass,
        risk.security_pass,
        risk.event_risk_pass,
        risk.reconciliation_pass,
        risk.testnet_order_authorized,
    )
    if not all(risk_checks):
        reasons.append("RISK_OR_RECONCILIATION_CHECK_FAILED")
    if reasons:
        return _gate(
            P12GateName.RISK,
            P12GateStatus.FAIL,
            evidence_hashes,
            *reasons,
        )
    return _gate(P12GateName.RISK, P12GateStatus.PASS, evidence_hashes)


def _derive_assessment(
    *,
    policy: P12ReadinessPolicy,
    bundle: P12EvidenceBundle,
    assessed_at: datetime,
) -> dict[str, object]:
    validated_assessed_at = ensure_utc(assessed_at)
    validated_policy = P12ReadinessPolicy.model_validate_json(policy.model_dump_json())
    validated_bundle = P12EvidenceBundle.model_validate_json(bundle.model_dump_json())
    proof = validated_bundle.forward_proof
    truth = _calibration_gate(
        gate=P12GateName.TRUTH_CALIBRATION,
        proof=proof,
        calibration_pass=proof.truth_calibration_pass,
    )
    forecast = _calibration_gate(
        gate=P12GateName.FORECAST_CALIBRATION,
        proof=proof,
        calibration_pass=proof.forecast_calibration_pass,
    )
    cost = _calibration_gate(
        gate=P12GateName.COST_CALIBRATION,
        proof=proof,
        calibration_pass=proof.cost_calibration_pass,
    )
    paper = _forward_gate(
        gate=P12GateName.PAPER,
        report_mode=ForwardMode.PAPER,
        proof=proof,
    )
    shadow = _forward_gate(
        gate=P12GateName.SHADOW,
        report_mode=ForwardMode.SHADOW,
        proof=proof,
    )
    testnet = _testnet_gate(
        policy=validated_policy,
        bundle=validated_bundle,
        assessed_at=validated_assessed_at,
    )
    risk = _risk_gate(
        policy=validated_policy,
        bundle=validated_bundle,
        testnet_gate=testnet,
        assessed_at=validated_assessed_at,
    )
    gates = (truth, forecast, cost, paper, shadow, testnet, risk)
    passed_count = sum(item.status is P12GateStatus.PASS for item in gates)
    failed_count = sum(item.status is P12GateStatus.FAIL for item in gates)
    blocked_count = sum(item.status is P12GateStatus.BLOCKED_EXTERNAL_INPUT for item in gates)
    ready = passed_count == len(P12GateName)
    if ready:
        next_action = P12NextAction.REQUEST_MANUAL_CANARY_REVIEW
    elif failed_count:
        next_action = P12NextAction.REMEDIATE_AND_RETEST
    elif any(
        item.gate in {P12GateName.PAPER, P12GateName.SHADOW}
        and item.status is not P12GateStatus.PASS
        for item in gates
    ):
        next_action = P12NextAction.EXTEND_PAPER
    else:
        next_action = P12NextAction.PROVIDE_EXTERNAL_EVIDENCE
    blocking_reasons = tuple(
        sorted(
            {
                reason
                for gate in gates
                if gate.status is not P12GateStatus.PASS
                for reason in gate.reason_codes
            }
        )
    )
    return {
        "assessed_at": validated_assessed_at,
        "policy": validated_policy,
        "evidence_bundle": validated_bundle,
        "gates": gates,
        "gate_count": len(gates),
        "passed_gate_count": passed_count,
        "failed_gate_count": failed_count,
        "blocked_gate_count": blocked_count,
        "decision": (
            CanaryReadinessDecision.CANARY_REVIEW_READY
            if ready
            else CanaryReadinessDecision.NO_PROMOTION
        ),
        "next_action": next_action,
        "blocking_reason_codes": blocking_reasons,
        "weighted_score_used": False,
        "canary_review_ready": ready,
        "canary_capital_authorized": False,
        "user_approval_received": False,
        "manual_live_unlock_received": False,
        "live_order_submission_enabled": False,
        "live_trading_locked": True,
        "final_holdout_opened": False,
    }


class P12CanaryReadinessAssessment(DomainModel):
    assessed_at: UtcDateTime
    policy: P12ReadinessPolicy
    evidence_bundle: P12EvidenceBundle
    gates: Annotated[tuple[P12GateResult, ...], Field(min_length=7, max_length=7)]
    gate_count: Literal[7] = 7
    passed_gate_count: int = Field(ge=0, le=7)
    failed_gate_count: int = Field(ge=0, le=7)
    blocked_gate_count: int = Field(ge=0, le=7)
    decision: CanaryReadinessDecision
    next_action: P12NextAction
    blocking_reason_codes: Annotated[tuple[ReasonCode, ...], Field(max_length=128)]
    weighted_score_used: Literal[False] = False
    canary_review_ready: bool
    canary_capital_authorized: Literal[False] = False
    user_approval_received: Literal[False] = False
    manual_live_unlock_received: Literal[False] = False
    live_order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    final_holdout_opened: Literal[False] = False
    assessment_sha256: str

    @field_validator("assessment_sha256")
    @classmethod
    def validate_assessment_hash(cls, value: str) -> str:
        return _validate_hash(value, "P12 Canary readiness assessment hash")

    @model_validator(mode="after")
    def validate_assessment(self) -> Self:
        expected = _derive_assessment(
            policy=self.policy,
            bundle=self.evidence_bundle,
            assessed_at=self.assessed_at,
        )
        expected_model = type(self).model_construct(
            **cast("dict[str, Any]", expected), assessment_sha256=self.assessment_sha256
        )
        actual = self.model_dump(mode="json", exclude={"assessment_sha256"})
        expected_dump = expected_model.model_dump(mode="json", exclude={"assessment_sha256"})
        if actual != expected_dump:
            raise ValueError("AQ-P12-CANARY-ASSESSMENT-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(
            self.model_dump(mode="json", exclude={"assessment_sha256"})
        )
        if self.assessment_sha256 != expected_hash:
            raise ValueError("AQ-P12-CANARY-ASSESSMENT-HASH-MISMATCH")
        return self


def evaluate_p12_canary_readiness(
    *,
    policy: P12ReadinessPolicy,
    evidence_bundle: P12EvidenceBundle,
    assessed_at: UtcDateTime,
) -> P12CanaryReadinessAssessment:
    payload = _derive_assessment(
        policy=policy,
        bundle=evidence_bundle,
        assessed_at=assessed_at,
    )
    return cast(
        "P12CanaryReadinessAssessment",
        _hashed_model(P12CanaryReadinessAssessment, payload, "assessment_sha256"),
    )
