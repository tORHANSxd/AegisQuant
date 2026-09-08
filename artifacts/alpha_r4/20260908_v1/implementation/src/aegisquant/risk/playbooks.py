"""Signed high-impact event playbooks with strict rumor containment."""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import UnitInterval
from aegisquant.risk.models import (
    MajorEventType,
    RiskAction,
    RiskConfirmation,
    RiskEvent,
    RiskState,
)
from aegisquant.risk.policy import RiskPolicy


class RiskPlaybook(DomainModel):
    playbook_id: str = Field(min_length=1, max_length=255)
    event_type: MajorEventType
    action: RiskAction
    target_state: RiskState
    reduction_fraction: UnitInterval
    reason_code: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_action(self) -> RiskPlaybook:
        if self.action is RiskAction.HALT and self.target_state is not RiskState.HALTED:
            raise ValueError("halt playbook must target HALTED")
        if self.action is RiskAction.REDUCE and self.target_state is not RiskState.REDUCE_ONLY:
            raise ValueError("reduce playbook must target REDUCE_ONLY")
        if self.action in {
            RiskAction.MONITOR,
            RiskAction.TIGHTEN_LIMITS,
        } and self.target_state not in {
            RiskState.CAUTION,
            RiskState.NORMAL,
        }:
            raise ValueError("monitoring playbook cannot escalate to execution state")
        return self


class RiskPlaybookRegistry(DomainModel):
    schema_version: str = "p11-risk-playbook-registry-v1"
    version: str = Field(min_length=1, max_length=80)
    playbooks: tuple[RiskPlaybook, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def require_all_playbooks(self) -> RiskPlaybookRegistry:
        if self.schema_version != "p11-risk-playbook-registry-v1":
            raise ValueError("unsupported risk playbook registry schema")
        if {item.event_type for item in self.playbooks} != set(MajorEventType):
            raise ValueError("risk playbook registry must cover all five event types")
        return self


class SignedRiskPlaybookRegistry(DomainModel):
    registry: RiskPlaybookRegistry
    registry_sha256: str
    signer_key_id: str = Field(min_length=1, max_length=255)
    signature_hex: str

    @field_validator("registry_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="risk playbook registry hash")

    @field_validator("signature_hex")
    @classmethod
    def validate_signature(cls, value: str) -> str:
        try:
            raw = bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError("risk playbook signature must be hexadecimal") from exc
        if len(raw) != 64:
            raise ValueError("Ed25519 playbook signature must be 64 bytes")
        return value.lower()


class PlaybookDecision(DomainModel):
    playbook_id: str | None
    event_id: str
    confirmation: RiskConfirmation
    action: RiskAction
    target_state: RiskState
    reduction_fraction: UnitInterval
    reason_codes: tuple[str, ...]
    llm_full_liquidation_allowed: bool = False

    @model_validator(mode="after")
    def prohibit_llm_liquidation(self) -> PlaybookDecision:
        if self.llm_full_liquidation_allowed:
            raise ValueError("LLM full liquidation is prohibited")
        return self


def playbook_registry_payload(registry: RiskPlaybookRegistry) -> bytes:
    return canonical_json_bytes(registry.model_dump(mode="json"))


def playbook_registry_sha256(registry: RiskPlaybookRegistry) -> str:
    return canonical_sha256(registry.model_dump(mode="json"))


def verify_signed_playbooks(
    envelope: SignedRiskPlaybookRegistry, *, trusted_public_keys: dict[str, bytes]
) -> RiskPlaybookRegistry:
    if envelope.registry_sha256 != playbook_registry_sha256(envelope.registry):
        raise ValueError("AQ-RISK-PLAYBOOK-HASH-MISMATCH")
    public_key = trusted_public_keys.get(envelope.signer_key_id)
    if public_key is None:
        raise ValueError("AQ-RISK-PLAYBOOK-UNTRUSTED-SIGNER")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(envelope.signature_hex), playbook_registry_payload(envelope.registry)
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("AQ-RISK-PLAYBOOK-SIGNATURE-INVALID") from exc
    return envelope.registry


def apply_event_playbook(
    *, event: RiskEvent, registry: RiskPlaybookRegistry, policy: RiskPolicy
) -> PlaybookDecision:
    if event.major_event_type is None:
        raise ValueError("risk playbooks require a major event type")
    if event.confirmation is RiskConfirmation.RUMOR:
        if event.action not in {
            RiskAction.MONITOR,
            RiskAction.TIGHTEN_LIMITS,
            RiskAction.REDUCE,
        }:
            raise ValueError("AQ-RISK-RUMOR-ACTION-PROHIBITED")
        if event.requested_reduction_fraction > policy.maximum_rumor_reduction_fraction:
            raise ValueError("AQ-RISK-RUMOR-REDUCTION-LIMIT")
        target = RiskState.REDUCE_ONLY if event.action is RiskAction.REDUCE else RiskState.CAUTION
        return PlaybookDecision(
            playbook_id=None,
            event_id=event.risk_event_id,
            confirmation=event.confirmation,
            action=event.action,
            target_state=target,
            reduction_fraction=event.requested_reduction_fraction,
            reason_codes=("AQ-RISK-RUMOR-CONTAINED",),
        )
    if not event.official_source:
        raise ValueError("AQ-RISK-CONFIRMED-EVENT-REQUIRES-OFFICIAL-SOURCE")
    playbook = next(
        item for item in registry.playbooks if item.event_type is event.major_event_type
    )
    return PlaybookDecision(
        playbook_id=playbook.playbook_id,
        event_id=event.risk_event_id,
        confirmation=event.confirmation,
        action=playbook.action,
        target_state=playbook.target_state,
        reduction_fraction=playbook.reduction_fraction,
        reason_codes=(playbook.reason_code,),
    )
