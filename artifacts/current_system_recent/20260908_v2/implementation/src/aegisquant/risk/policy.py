"""Versioned, signed, example-only P11 risk policy verification."""

from __future__ import annotations

from enum import StrEnum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.entities import DeploymentStage
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal, PositiveDecimal, UnitInterval


class RecoveryCondition(StrEnum):
    DATA_FRESH = "DATA_FRESH"
    MODEL_FRESH = "MODEL_FRESH"
    LEDGER_RECONCILED = "LEDGER_RECONCILED"
    MARGIN_SAFE = "MARGIN_SAFE"
    LIQUIDITY_SAFE = "LIQUIDITY_SAFE"
    VENUE_OPERATIONAL = "VENUE_OPERATIONAL"
    SECURITY_CLEAR = "SECURITY_CLEAR"
    MAJOR_EVENT_CLEAR = "MAJOR_EVENT_CLEAR"


class PreTradeLimits(DomainModel):
    maximum_order_weight: PositiveDecimal
    maximum_asset_gross_weight: PositiveDecimal
    maximum_strategy_gross_weight: PositiveDecimal
    maximum_account_gross_weight: PositiveDecimal


class RiskPolicy(DomainModel):
    schema_version: str = "p11-risk-policy-v1"
    policy_id: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=80)
    effective_at: UtcDateTime
    expires_at: UtcDateTime
    snapshot_max_age_seconds: int = Field(gt=0)
    caution_target_scale: UnitInterval
    maximum_daily_loss_fraction: NonNegativeDecimal
    maximum_drawdown_fraction: NonNegativeDecimal
    maximum_margin_utilization: UnitInterval
    minimum_liquidity_score: UnitInterval
    maximum_rumor_reduction_fraction: UnitInterval
    pre_trade_limits: PreTradeLimits
    recovery_conditions: tuple[RecoveryCondition, ...] = Field(min_length=8, max_length=8)
    allowed_stages: tuple[DeploymentStage, ...] = (DeploymentStage.PAPER,)
    example_values_only: bool = True
    automatic_recovery_enabled: bool = False

    @model_validator(mode="after")
    def validate_policy(self) -> RiskPolicy:
        if self.schema_version != "p11-risk-policy-v1":
            raise ValueError("unsupported P11 risk policy schema")
        if self.expires_at <= self.effective_at:
            raise ValueError("risk policy validity interval must increase")
        if self.caution_target_scale >= 1:
            raise ValueError("caution scale must reduce targets")
        if self.maximum_rumor_reduction_fraction >= 1:
            raise ValueError("rumor reduction cannot authorize full liquidation")
        if set(self.recovery_conditions) != set(RecoveryCondition):
            raise ValueError("risk policy must require every recovery condition")
        if self.allowed_stages != (DeploymentStage.PAPER,) or not self.example_values_only:
            raise ValueError("AQ-RISK-EXAMPLE-POLICY-PAPER-ONLY")
        if self.automatic_recovery_enabled:
            raise ValueError("automatic risk recovery is prohibited")
        return self


class SignedRiskPolicy(DomainModel):
    policy: RiskPolicy
    policy_sha256: str
    signer_key_id: str = Field(min_length=1, max_length=255)
    signature_hex: str

    @field_validator("policy_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="risk policy hash")

    @field_validator("signature_hex")
    @classmethod
    def validate_signature(cls, value: str) -> str:
        try:
            raw = bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError("risk policy signature must be hexadecimal") from exc
        if len(raw) != 64:
            raise ValueError("Ed25519 risk policy signature must be 64 bytes")
        return value.lower()


def risk_policy_payload(policy: RiskPolicy) -> bytes:
    return canonical_json_bytes(policy.model_dump(mode="json"))


def risk_policy_sha256(policy: RiskPolicy) -> str:
    return canonical_sha256(policy.model_dump(mode="json"))


def verify_signed_risk_policy(
    envelope: SignedRiskPolicy,
    *,
    trusted_public_keys: dict[str, bytes],
    decision_time: UtcDateTime,
    deployment_stage: DeploymentStage,
) -> RiskPolicy:
    expected_hash = risk_policy_sha256(envelope.policy)
    if envelope.policy_sha256 != expected_hash:
        raise ValueError("AQ-RISK-POLICY-HASH-MISMATCH")
    public_key = trusted_public_keys.get(envelope.signer_key_id)
    if public_key is None:
        raise ValueError("AQ-RISK-POLICY-UNTRUSTED-SIGNER")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(envelope.signature_hex), risk_policy_payload(envelope.policy)
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("AQ-RISK-POLICY-SIGNATURE-INVALID") from exc
    if not envelope.policy.effective_at <= decision_time < envelope.policy.expires_at:
        raise ValueError("AQ-RISK-POLICY-NOT-EFFECTIVE")
    if deployment_stage not in envelope.policy.allowed_stages:
        raise ValueError("AQ-RISK-UNCONFIRMED-PAPER-ONLY")
    return envelope.policy
