"""Strict P18 Canary scope, hard-gate, capital, and manifest contracts."""

from __future__ import annotations

import re
from datetime import timedelta
from enum import StrEnum
from typing import Final

from pydantic import Field, field_validator, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal, UnitInterval

SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
COMMIT: Final = re.compile(r"^[0-9a-f]{40}$")


class GateStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED_EXTERNAL_INPUT = "BLOCKED_EXTERNAL_INPUT"


class ReadinessDecision(StrEnum):
    GO = "GO"
    NO_GO = "NO_GO"


class SelectionStatus(StrEnum):
    SELECTED = "SELECTED"
    NONE_NO_GO = "NONE_NO_GO"


class CapitalLevel(StrEnum):
    LOCKED = "LOCKED"
    CANARY_L1 = "CANARY_L1"
    CANARY_L2 = "CANARY_L2"


class StopComparator(StrEnum):
    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    EQUAL = "EQUAL"
    FALSE = "FALSE"


class StopAction(StrEnum):
    HALT_CANCEL_RECONCILE_MANUAL_RESUME = "HALT_CANCEL_RECONCILE_MANUAL_RESUME"


class OperatingFrequency(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class ReadinessGate(DomainModel):
    gate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,95}$")
    description: str
    hard: bool = True
    status: GateStatus
    evidence_paths: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()

    @field_validator("description")
    @classmethod
    def non_blank_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("gate description cannot be blank")
        return value

    @model_validator(mode="after")
    def evidence_and_failure_are_explicit(self) -> ReadinessGate:
        if not self.evidence_paths or len(self.evidence_paths) != len(set(self.evidence_paths)):
            raise ValueError("readiness gate requires unique evidence paths")
        if self.status is GateStatus.PASSED and self.reason_codes:
            raise ValueError("passed gate cannot carry failure reasons")
        if self.status is not GateStatus.PASSED and not self.reason_codes:
            raise ValueError("non-passed gate requires reason codes")
        return self


class CanaryScope(DomainModel):
    selection_status: SelectionStatus
    strategy_id: str | None
    account_scope_id: str | None
    instrument_ids: tuple[str, ...]

    @field_validator("instrument_ids")
    @classmethod
    def at_most_two_unique_instruments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 2 or len(value) != len(set(value)):
            raise ValueError("Canary scope permits at most two unique instruments")
        return value

    @model_validator(mode="after")
    def selection_is_complete_or_empty(self) -> CanaryScope:
        selected = self.selection_status is SelectionStatus.SELECTED
        complete = (
            self.strategy_id is not None
            and self.account_scope_id is not None
            and bool(self.instrument_ids)
        )
        if selected != complete:
            raise ValueError("Canary scope must be either fully selected or explicitly empty")
        return self


class CapitalTier(DomainModel):
    level: CapitalLevel
    activated: bool
    hard_code_capital_usd: NonNegativeDecimal
    user_policy_capital_usd: NonNegativeDecimal
    effective_capital_usd: NonNegativeDecimal
    max_gross_notional_usd: NonNegativeDecimal
    max_single_order_notional_usd: NonNegativeDecimal
    max_daily_loss_usd: NonNegativeDecimal
    max_equity_fraction: UnitInterval
    max_duration_minutes: int = Field(ge=0, le=1440)
    evaluation_window_minutes: int = Field(ge=0, le=1440)
    user_approval_required: bool
    separate_live_unlock_required: bool
    approval_reference: str | None = None

    @model_validator(mode="after")
    def dual_cap_and_activation_are_fail_closed(self) -> CapitalTier:
        expected = min(self.hard_code_capital_usd, self.user_policy_capital_usd)
        if self.effective_capital_usd != expected:
            raise ValueError("effective capital must equal the lower code and policy cap")
        if self.max_gross_notional_usd > self.effective_capital_usd:
            raise ValueError("gross notional cannot exceed effective capital")
        if self.max_single_order_notional_usd > self.max_gross_notional_usd:
            raise ValueError("single-order notional cannot exceed gross notional")
        if self.max_daily_loss_usd > self.effective_capital_usd:
            raise ValueError("daily loss cannot exceed effective capital")
        if self.level is CapitalLevel.LOCKED:
            numeric = (
                self.hard_code_capital_usd,
                self.user_policy_capital_usd,
                self.effective_capital_usd,
                self.max_gross_notional_usd,
                self.max_single_order_notional_usd,
                self.max_daily_loss_usd,
                self.max_equity_fraction,
            )
            if any(item != 0 for item in numeric) or not self.activated:
                raise ValueError("LOCKED tier must be active with every capital limit at zero")
        elif self.activated:
            if self.approval_reference is None or self.effective_capital_usd <= 0:
                raise ValueError("active Canary tier requires approval and positive effective cap")
        elif (
            self.user_policy_capital_usd != 0
            or self.approval_reference is not None
            or any(
                item != 0
                for item in (
                    self.max_gross_notional_usd,
                    self.max_single_order_notional_usd,
                    self.max_daily_loss_usd,
                    self.max_equity_fraction,
                )
            )
        ):
            raise ValueError("inactive Canary tier must have zero operational caps and no approval")
        if not self.user_approval_required or not self.separate_live_unlock_required:
            raise ValueError("every capital tier requires user approval and separate Live unlock")
        return self


class CapitalLadder(DomainModel):
    schema_version: str
    tiers: tuple[CapitalTier, ...]

    @model_validator(mode="after")
    def unique_ordered_tiers(self) -> CapitalLadder:
        levels = [item.level for item in self.tiers]
        if levels != [CapitalLevel.LOCKED, CapitalLevel.CANARY_L1, CapitalLevel.CANARY_L2]:
            raise ValueError("capital ladder must contain LOCKED, CANARY_L1, CANARY_L2 in order")
        if sum(item.activated for item in self.tiers) != 1:
            raise ValueError("only the zero-capital LOCKED tier may be active")
        return self


class StopCondition(DomainModel):
    condition_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,95}$")
    metric: str
    comparator: StopComparator
    threshold: str
    action: StopAction
    automatic: bool
    manual_resume_required: bool

    @model_validator(mode="after")
    def fail_closed_action(self) -> StopCondition:
        if not self.metric.strip() or not self.threshold.strip():
            raise ValueError("stop condition metric and threshold cannot be blank")
        if not self.automatic or not self.manual_resume_required:
            raise ValueError("stop conditions must halt automatically and resume manually")
        return self


class OperatingCadence(DomainModel):
    frequency: OperatingFrequency
    checks: tuple[str, ...]

    @field_validator("checks")
    @classmethod
    def checks_are_nonempty_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("operating cadence requires unique non-blank checks")
        return value


class LiveReadinessPolicy(DomainModel):
    schema_version: str
    scope: CanaryScope
    capital_ladder: CapitalLadder
    stop_conditions: tuple[StopCondition, ...]
    operating_cadence: tuple[OperatingCadence, ...]

    @model_validator(mode="after")
    def complete_policy(self) -> LiveReadinessPolicy:
        if not self.stop_conditions:
            raise ValueError("readiness policy requires stop conditions")
        frequencies = [item.frequency for item in self.operating_cadence]
        if frequencies != list(OperatingFrequency):
            raise ValueError("operating cadence must cover daily through quarterly in order")
        return self


class ReadinessReview(DomainModel):
    decision: ReadinessDecision
    gates: tuple[ReadinessGate, ...]
    hard_gate_count: int = Field(ge=1)
    passed_hard_gate_count: int = Field(ge=0)
    failed_hard_gate_count: int = Field(ge=0)
    blocked_hard_gate_count: int = Field(ge=0)
    blocking_reason_codes: tuple[str, ...]
    weighted_score_used: bool
    live_trading_locked: bool
    manual_unlock_received: bool
    real_order_capability: bool

    @model_validator(mode="after")
    def counts_and_safety_match(self) -> ReadinessReview:
        if len({item.gate_id for item in self.gates}) != len(self.gates):
            raise ValueError("readiness review requires unique gates")
        hard = [item for item in self.gates if item.hard]
        if not hard:
            raise ValueError("readiness review requires hard gates")
        passed = sum(item.status is GateStatus.PASSED for item in hard)
        failed = sum(item.status is GateStatus.FAILED for item in hard)
        blocked = sum(item.status is GateStatus.BLOCKED_EXTERNAL_INPUT for item in hard)
        if (self.hard_gate_count, self.passed_hard_gate_count) != (len(hard), passed):
            raise ValueError("hard gate counts are inconsistent")
        if (self.failed_hard_gate_count, self.blocked_hard_gate_count) != (failed, blocked):
            raise ValueError("failed or blocked gate counts are inconsistent")
        expected = ReadinessDecision.GO if passed == len(hard) else ReadinessDecision.NO_GO
        if not self.live_trading_locked:
            expected = ReadinessDecision.NO_GO
        if self.decision is not expected:
            raise ValueError("readiness decision does not match hard gates and Live lock")
        expected_reasons = tuple(
            sorted(
                {
                    code
                    for gate in hard
                    if gate.status is not GateStatus.PASSED
                    for code in gate.reason_codes
                }
                | ({"AQ-P18-LIVE-LOCK-VIOLATION"} if not self.live_trading_locked else set())
            )
        )
        if self.blocking_reason_codes != expected_reasons:
            raise ValueError("blocking reasons do not match failed hard gates")
        if self.weighted_score_used or self.real_order_capability:
            raise ValueError("P18 cannot average hard gates or expose real-order capability")
        if self.manual_unlock_received:
            raise ValueError("P18 cannot consume the separate Live unlock")
        if self.decision is ReadinessDecision.GO and self.blocking_reason_codes:
            raise ValueError("GO decision cannot carry blocking reasons")
        if self.decision is ReadinessDecision.NO_GO and not self.blocking_reason_codes:
            raise ValueError("NO_GO decision requires blocking reasons")
        return self


class CanaryReleaseManifest(DomainModel):
    schema_version: str
    release_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,95}$")
    source_commit: str
    created_at_utc: UtcDateTime
    expires_at_utc: UtcDateTime
    decision: ReadinessDecision
    scope: CanaryScope
    frozen_versions: dict[str, str]
    frozen_artifact_sha256: dict[str, str]
    live_trading_locked: bool
    user_approval_received: bool
    manual_unlock_received: bool
    releaseable: bool

    @model_validator(mode="after")
    def non_authorizing_manifest(self) -> CanaryReleaseManifest:
        if COMMIT.fullmatch(self.source_commit) is None:
            raise ValueError("source_commit must be a full lowercase SHA-1")
        if not self.frozen_versions or not self.frozen_artifact_sha256:
            raise ValueError("manifest must freeze versions and artifact hashes")
        if any(SHA256.fullmatch(value) is None for value in self.frozen_artifact_sha256.values()):
            raise ValueError("frozen artifact hashes must be SHA-256")
        if (
            not self.created_at_utc
            < self.expires_at_utc
            <= self.created_at_utc + timedelta(hours=24)
        ):
            raise ValueError("Canary readiness manifest must expire within 24 hours")
        if (
            not self.live_trading_locked
            or self.user_approval_received
            or self.manual_unlock_received
            or self.releaseable
        ):
            raise ValueError("P18 manifest is non-authorizing and must remain Live-locked")
        return self


class SignedManifestEnvelope(DomainModel):
    manifest: CanaryReleaseManifest
    manifest_sha256: str
    public_key_base64: str
    signature_base64: str
    signature_verified: bool
    signature_purpose: str
    private_key_persisted: bool
    authorization_capability: bool

    @model_validator(mode="after")
    def evidence_signature_is_not_authorization(self) -> SignedManifestEnvelope:
        if SHA256.fullmatch(self.manifest_sha256) is None:
            raise ValueError("manifest_sha256 must be SHA-256")
        if self.signature_purpose != "EVIDENCE_INTEGRITY_ONLY":
            raise ValueError("P18 signature cannot authorize Live")
        if (
            not self.signature_verified
            or self.private_key_persisted
            or self.authorization_capability
        ):
            raise ValueError("manifest signature must verify without authorization capability")
        return self
