"""Fail-closed Paper/Shadow forward-proof contracts for V5-P11."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, field_validator, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.time import UtcDateTime, assert_point_in_time
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    UnitInterval,
    canonical_result,
)


class ForwardMode(StrEnum):
    PAPER = "PAPER"
    SHADOW = "SHADOW"


class ForwardRunKind(StrEnum):
    WALL_CLOCK_FORWARD = "WALL_CLOCK_FORWARD"
    DEVELOPMENT_FIXTURE = "DEVELOPMENT_FIXTURE"


class ForwardProofStatus(StrEnum):
    PASS = "PASS"  # noqa: S105  # nosec B105 -- status token
    EXTEND_PAPER = "EXTEND_PAPER"
    FAIL_CLOSED = "FAIL_CLOSED"


class ForwardProofDecision(StrEnum):
    P11_FORWARD_PASS = "P11_FORWARD_PASS"  # noqa: S105  # nosec B105 -- status token
    NO_PROMOTION = "NO_PROMOTION"


class ForwardNextAction(StrEnum):
    PROCEED_TO_TESTNET_READINESS = "PROCEED_TO_TESTNET_READINESS"
    EXTEND_PAPER = "EXTEND_PAPER"


class ForwardIncidentSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def _hashed_model(
    model_type: type[DomainModel], payload: Mapping[str, object], hash_field: str
) -> DomainModel:
    candidate_payload = {**payload, hash_field: "0" * 64}
    candidate = model_type.model_construct(**cast("dict[str, Any]", candidate_payload))
    digest = canonical_sha256(candidate.model_dump(mode="json", exclude={hash_field}))
    return model_type.model_validate({**payload, hash_field: digest})


def _elapsed_seconds(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    microseconds = (
        Decimal(delta.days) * Decimal("86400000000")
        + Decimal(delta.seconds) * Decimal("1000000")
        + Decimal(delta.microseconds)
    )
    return canonical_result(microseconds / Decimal("1000000"))


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("cannot calculate the mean of an empty sequence")
    return canonical_result(sum(values, start=Decimal("0")) / Decimal(len(values)))


def _same_direction(left: Decimal, right: Decimal) -> bool:
    return (left > 0 and right > 0) or (left < 0 and right < 0) or (left == right == 0)


class ForwardHeartbeat(DomainModel):
    run_id: str = Field(min_length=1, max_length=160)
    mode: ForwardMode
    sequence: int = Field(ge=0)
    observed_at: UtcDateTime
    source_available_at: UtcDateTime
    previous_heartbeat_sha256: str | None = None
    heartbeat_sha256: str

    @field_validator("previous_heartbeat_sha256", "heartbeat_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ensure_sha256(value, field_name="forward heartbeat hash")

    @model_validator(mode="after")
    def validate_heartbeat(self) -> Self:
        assert_point_in_time(
            available_time=self.source_available_at,
            decision_time=self.observed_at,
        )
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"heartbeat_sha256"}))
        if self.heartbeat_sha256 != expected:
            raise ValueError("AQ-P11-HEARTBEAT-HASH-MISMATCH")
        return self


def create_forward_heartbeat(
    *,
    run_id: str,
    mode: ForwardMode,
    sequence: int,
    observed_at: UtcDateTime,
    source_available_at: UtcDateTime,
    previous_heartbeat_sha256: str | None,
) -> ForwardHeartbeat:
    payload = {
        "run_id": run_id,
        "mode": mode,
        "sequence": sequence,
        "observed_at": observed_at,
        "source_available_at": source_available_at,
        "previous_heartbeat_sha256": previous_heartbeat_sha256,
    }
    return cast(
        "ForwardHeartbeat",
        _hashed_model(ForwardHeartbeat, payload, "heartbeat_sha256"),
    )


class ForwardSample(DomainModel):
    run_id: str = Field(min_length=1, max_length=160)
    mode: ForwardMode
    sample_id: str = Field(min_length=1, max_length=200)
    event_independence_key: str = Field(min_length=1, max_length=200)
    decision_report_sha256: str
    prediction_input_sha256: str
    source_available_at: UtcDateTime
    decision_time: UtcDateTime
    prediction_recorded_at: UtcDateTime
    outcome_available_at: UtcDateTime
    realization_recorded_at: UtcDateTime
    predicted_truth_probability: UnitInterval
    realized_truth: bool
    predicted_return: FiniteDecimal
    realized_return: FiniteDecimal
    predicted_cost: NonNegativeDecimal
    realized_cost: NonNegativeDecimal
    predicted_event_increment: FiniteDecimal
    realized_event_increment: FiniteDecimal
    prediction_revision: Literal[0] = 0
    correction_of_sha256: None = None
    prediction_sha256: str
    sample_sha256: str

    @field_validator(
        "decision_report_sha256",
        "prediction_input_sha256",
        "prediction_sha256",
        "sample_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forward sample hash")

    def prediction_payload(self) -> dict[str, object]:
        fields = {
            "run_id",
            "mode",
            "sample_id",
            "event_independence_key",
            "decision_report_sha256",
            "prediction_input_sha256",
            "source_available_at",
            "decision_time",
            "prediction_recorded_at",
            "predicted_truth_probability",
            "predicted_return",
            "predicted_cost",
            "predicted_event_increment",
            "prediction_revision",
            "correction_of_sha256",
        }
        return cast(
            "dict[str, object]",
            self.model_dump(mode="json", include=fields),
        )

    @model_validator(mode="after")
    def validate_sample(self) -> Self:
        assert_point_in_time(
            available_time=self.source_available_at,
            decision_time=self.decision_time,
        )
        if not (
            self.decision_time
            <= self.prediction_recorded_at
            < self.outcome_available_at
            <= self.realization_recorded_at
        ):
            raise ValueError("AQ-P11-FORWARD-SAMPLE-TIME-ORDER-VIOLATION")
        expected_prediction = canonical_sha256(self.prediction_payload())
        if self.prediction_sha256 != expected_prediction:
            raise ValueError("AQ-P11-PREDICTION-HASH-MISMATCH")
        expected_sample = canonical_sha256(self.model_dump(mode="json", exclude={"sample_sha256"}))
        if self.sample_sha256 != expected_sample:
            raise ValueError("AQ-P11-SAMPLE-HASH-MISMATCH")
        return self


def create_forward_sample(
    *,
    run_id: str,
    mode: ForwardMode,
    sample_id: str,
    event_independence_key: str,
    decision_report_sha256: str,
    prediction_input_sha256: str,
    source_available_at: UtcDateTime,
    decision_time: UtcDateTime,
    prediction_recorded_at: UtcDateTime,
    outcome_available_at: UtcDateTime,
    realization_recorded_at: UtcDateTime,
    predicted_truth_probability: Decimal,
    realized_truth: bool,
    predicted_return: Decimal,
    realized_return: Decimal,
    predicted_cost: Decimal,
    realized_cost: Decimal,
    predicted_event_increment: Decimal,
    realized_event_increment: Decimal,
) -> ForwardSample:
    prediction_payload = {
        "run_id": run_id,
        "mode": mode,
        "sample_id": sample_id,
        "event_independence_key": event_independence_key,
        "decision_report_sha256": decision_report_sha256,
        "prediction_input_sha256": prediction_input_sha256,
        "source_available_at": source_available_at,
        "decision_time": decision_time,
        "prediction_recorded_at": prediction_recorded_at,
        "predicted_truth_probability": predicted_truth_probability,
        "predicted_return": predicted_return,
        "predicted_cost": predicted_cost,
        "predicted_event_increment": predicted_event_increment,
        "prediction_revision": 0,
        "correction_of_sha256": None,
    }
    unhashed_payload = {
        **prediction_payload,
        "outcome_available_at": outcome_available_at,
        "realization_recorded_at": realization_recorded_at,
        "realized_truth": realized_truth,
        "realized_return": realized_return,
        "realized_cost": realized_cost,
        "realized_event_increment": realized_event_increment,
    }
    candidate = ForwardSample.model_construct(
        **cast("dict[str, Any]", unhashed_payload),
        prediction_sha256="0" * 64,
        sample_sha256="0" * 64,
    )
    payload = {
        **unhashed_payload,
        "prediction_sha256": canonical_sha256(candidate.prediction_payload()),
    }
    return cast("ForwardSample", _hashed_model(ForwardSample, payload, "sample_sha256"))


class ForwardIncident(DomainModel):
    run_id: str = Field(min_length=1, max_length=160)
    mode: ForwardMode
    incident_id: str = Field(min_length=1, max_length=200)
    severity: ForwardIncidentSeverity
    category: str = Field(min_length=1, max_length=120)
    detected_at: UtcDateTime
    recorded_at: UtcDateTime
    resolved_at: UtcDateTime | None
    requires_restart: bool
    data_loss_detected: bool
    future_correction_attempted: bool
    incident_sha256: str

    @field_validator("incident_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forward incident hash")

    @model_validator(mode="after")
    def validate_incident(self) -> Self:
        if self.recorded_at < self.detected_at:
            raise ValueError("AQ-P11-INCIDENT-RECORDED-BEFORE-DETECTION")
        if self.resolved_at is not None and self.resolved_at < self.detected_at:
            raise ValueError("AQ-P11-INCIDENT-RESOLVED-BEFORE-DETECTION")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"incident_sha256"}))
        if self.incident_sha256 != expected:
            raise ValueError("AQ-P11-INCIDENT-HASH-MISMATCH")
        return self


def create_forward_incident(
    *,
    run_id: str,
    mode: ForwardMode,
    incident_id: str,
    severity: ForwardIncidentSeverity,
    category: str,
    detected_at: UtcDateTime,
    recorded_at: UtcDateTime,
    resolved_at: UtcDateTime | None,
    requires_restart: bool,
    data_loss_detected: bool = False,
    future_correction_attempted: bool = False,
) -> ForwardIncident:
    payload = {
        "run_id": run_id,
        "mode": mode,
        "incident_id": incident_id,
        "severity": severity,
        "category": category,
        "detected_at": detected_at,
        "recorded_at": recorded_at,
        "resolved_at": resolved_at,
        "requires_restart": requires_restart,
        "data_loss_detected": data_loss_detected,
        "future_correction_attempted": future_correction_attempted,
    }
    return cast(
        "ForwardIncident",
        _hashed_model(ForwardIncident, payload, "incident_sha256"),
    )


class ForwardIncidentLog(DomainModel):
    run_id: str = Field(min_length=1, max_length=160)
    mode: ForwardMode
    coverage_started_at: UtcDateTime
    coverage_ended_at: UtcDateTime
    incidents: Annotated[tuple[ForwardIncident, ...], Field(max_length=1000)]
    log_complete: bool
    log_sha256: str

    @field_validator("log_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forward incident log hash")

    @model_validator(mode="after")
    def validate_log(self) -> Self:
        if self.coverage_ended_at <= self.coverage_started_at:
            raise ValueError("AQ-P11-INCIDENT-LOG-COVERAGE-INVALID")
        validated = tuple(
            ForwardIncident.model_validate_json(item.model_dump_json()) for item in self.incidents
        )
        ordered = tuple(sorted(validated, key=lambda item: (item.detected_at, item.incident_id)))
        if validated != ordered:
            raise ValueError("forward incidents must be sorted")
        if len({item.incident_id for item in validated}) != len(validated):
            raise ValueError("forward incident ids must be unique")
        if any(item.run_id != self.run_id or item.mode is not self.mode for item in validated):
            raise ValueError("AQ-P11-INCIDENT-LOG-RUN-SPLICE")
        for item in validated:
            times = (item.detected_at, item.recorded_at)
            if item.resolved_at is not None:
                times = (*times, item.resolved_at)
            if any(
                instant < self.coverage_started_at or instant > self.coverage_ended_at
                for instant in times
            ):
                raise ValueError("AQ-P11-INCIDENT-OUTSIDE-LOG-COVERAGE")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"log_sha256"}))
        if self.log_sha256 != expected:
            raise ValueError("AQ-P11-INCIDENT-LOG-HASH-MISMATCH")
        return self


def create_forward_incident_log(
    *,
    run_id: str,
    mode: ForwardMode,
    coverage_started_at: UtcDateTime,
    coverage_ended_at: UtcDateTime,
    incidents: tuple[ForwardIncident, ...],
    log_complete: bool,
) -> ForwardIncidentLog:
    ordered = tuple(sorted(incidents, key=lambda item: (item.detected_at, item.incident_id)))
    payload = {
        "run_id": run_id,
        "mode": mode,
        "coverage_started_at": coverage_started_at,
        "coverage_ended_at": coverage_ended_at,
        "incidents": ordered,
        "log_complete": log_complete,
    }
    return cast(
        "ForwardIncidentLog",
        _hashed_model(ForwardIncidentLog, payload, "log_sha256"),
    )


class ForwardRecoveryReceipt(DomainModel):
    run_id: str = Field(min_length=1, max_length=160)
    mode: ForwardMode
    incident_id: str = Field(min_length=1, max_length=200)
    checkpoint_sha256: str
    pre_restart_chain_head_sha256: str
    restored_chain_head_sha256: str
    checkpoint_recorded_at: UtcDateTime
    resumed_at: UtcDateTime
    last_durable_sequence: int = Field(ge=0)
    gap_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    restored_without_loss: bool
    planned_drill: bool
    receipt_sha256: str

    @field_validator(
        "checkpoint_sha256",
        "pre_restart_chain_head_sha256",
        "restored_chain_head_sha256",
        "receipt_sha256",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forward recovery hash")

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.resumed_at < self.checkpoint_recorded_at:
            raise ValueError("AQ-P11-RECOVERY-RESUMED-BEFORE-CHECKPOINT")
        if (
            self.restored_without_loss
            and self.pre_restart_chain_head_sha256 != self.restored_chain_head_sha256
        ):
            raise ValueError("AQ-P11-RECOVERY-CHAIN-HEAD-MISMATCH")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("AQ-P11-RECOVERY-RECEIPT-HASH-MISMATCH")
        return self


def create_forward_recovery_receipt(
    *,
    run_id: str,
    mode: ForwardMode,
    incident_id: str,
    checkpoint_sha256: str,
    chain_head_sha256: str,
    checkpoint_recorded_at: UtcDateTime,
    resumed_at: UtcDateTime,
    last_durable_sequence: int,
    gap_count: int,
    duplicate_count: int,
    restored_without_loss: bool,
    planned_drill: bool,
) -> ForwardRecoveryReceipt:
    payload = {
        "run_id": run_id,
        "mode": mode,
        "incident_id": incident_id,
        "checkpoint_sha256": checkpoint_sha256,
        "pre_restart_chain_head_sha256": chain_head_sha256,
        "restored_chain_head_sha256": chain_head_sha256,
        "checkpoint_recorded_at": checkpoint_recorded_at,
        "resumed_at": resumed_at,
        "last_durable_sequence": last_durable_sequence,
        "gap_count": gap_count,
        "duplicate_count": duplicate_count,
        "restored_without_loss": restored_without_loss,
        "planned_drill": planned_drill,
    }
    return cast(
        "ForwardRecoveryReceipt",
        _hashed_model(ForwardRecoveryReceipt, payload, "receipt_sha256"),
    )


class ForwardSession(DomainModel):
    pair_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    mode: ForwardMode
    run_kind: ForwardRunKind
    evidence_tier: EvidenceTier
    started_at: UtcDateTime
    ended_at: UtcDateTime
    heartbeats: Annotated[tuple[ForwardHeartbeat, ...], Field(min_length=2, max_length=50000)]
    samples: Annotated[tuple[ForwardSample, ...], Field(min_length=1, max_length=10000)]
    incident_log: ForwardIncidentLog
    recovery_receipts: Annotated[
        tuple[ForwardRecoveryReceipt, ...], Field(min_length=1, max_length=1000)
    ]
    time_compressed: bool
    backtest_substitution: Literal[False] = False
    final_holdout_opened: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    alpha_promotion_eligible: Literal[False] = False
    session_sha256: str

    @field_validator("session_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forward session hash")

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        if self.ended_at <= self.started_at:
            raise ValueError("AQ-P11-FORWARD-SESSION-WINDOW-INVALID")
        expected_tier = (
            EvidenceTier.PAPER_FORWARD
            if self.mode is ForwardMode.PAPER
            else EvidenceTier.SHADOW_FORWARD
        )
        if self.run_kind is ForwardRunKind.WALL_CLOCK_FORWARD:
            if self.evidence_tier is not expected_tier or self.time_compressed:
                raise ValueError("AQ-P11-WALL-CLOCK-FORWARD-EVIDENCE-MISMATCH")
        elif self.evidence_tier is not EvidenceTier.DEVELOPMENT:
            raise ValueError("AQ-P11-DEVELOPMENT-FIXTURE-EVIDENCE-MISMATCH")

        heartbeats = tuple(
            ForwardHeartbeat.model_validate_json(item.model_dump_json()) for item in self.heartbeats
        )
        if (
            heartbeats[0].observed_at != self.started_at
            or heartbeats[-1].observed_at != self.ended_at
        ):
            raise ValueError("AQ-P11-HEARTBEAT-COVERAGE-MISMATCH")
        for index, heartbeat in enumerate(heartbeats):
            if (
                heartbeat.run_id != self.run_id
                or heartbeat.mode is not self.mode
                or heartbeat.sequence != index
            ):
                raise ValueError("AQ-P11-HEARTBEAT-SEQUENCE-OR-RUN-MISMATCH")
            expected_previous = None if index == 0 else heartbeats[index - 1].heartbeat_sha256
            if heartbeat.previous_heartbeat_sha256 != expected_previous:
                raise ValueError("AQ-P11-HEARTBEAT-CHAIN-BROKEN")
            if index > 0 and heartbeat.observed_at <= heartbeats[index - 1].observed_at:
                raise ValueError("AQ-P11-HEARTBEAT-TIME-NOT-MONOTONIC")

        samples = tuple(
            ForwardSample.model_validate_json(item.model_dump_json()) for item in self.samples
        )
        ordered_samples = tuple(
            sorted(samples, key=lambda item: (item.decision_time, item.sample_id))
        )
        if samples != ordered_samples:
            raise ValueError("forward samples must be sorted")
        if len({item.sample_id for item in samples}) != len(samples):
            raise ValueError("forward sample ids must be unique")
        if len({item.event_independence_key for item in samples}) != len(samples):
            raise ValueError("AQ-P11-INDEPENDENT-EVENT-SAMPLE-DUPLICATED")
        if any(
            item.run_id != self.run_id
            or item.mode is not self.mode
            or item.decision_time < self.started_at
            or item.realization_recorded_at > self.ended_at
            for item in samples
        ):
            raise ValueError("AQ-P11-FORWARD-SAMPLE-RUN-OR-WINDOW-SPLICE")

        incident_log = ForwardIncidentLog.model_validate_json(self.incident_log.model_dump_json())
        if (
            incident_log.run_id != self.run_id
            or incident_log.mode is not self.mode
            or incident_log.coverage_started_at != self.started_at
            or incident_log.coverage_ended_at != self.ended_at
        ):
            raise ValueError("AQ-P11-INCIDENT-LOG-COVERAGE-SPLICE")
        incident_by_id = {item.incident_id: item for item in incident_log.incidents}
        receipts = tuple(
            ForwardRecoveryReceipt.model_validate_json(item.model_dump_json())
            for item in self.recovery_receipts
        )
        if len({item.receipt_sha256 for item in receipts}) != len(receipts):
            raise ValueError("forward recovery receipts must be unique")
        receipt_incident_ids = tuple(item.incident_id for item in receipts)
        if len(set(receipt_incident_ids)) != len(receipt_incident_ids):
            raise ValueError("forward restart incidents require one recovery receipt each")
        expected_restart_incidents = {
            item.incident_id for item in incident_log.incidents if item.requires_restart
        }
        if set(receipt_incident_ids) != expected_restart_incidents:
            raise ValueError("AQ-P11-RESTART-RECOVERY-COVERAGE-MISMATCH")
        for receipt in receipts:
            incident = incident_by_id.get(receipt.incident_id)
            if receipt.last_durable_sequence >= len(heartbeats):
                raise ValueError("AQ-P11-RECOVERY-DURABLE-SEQUENCE-OUT-OF-RANGE")
            chain_head = heartbeats[receipt.last_durable_sequence]
            if (
                receipt.run_id != self.run_id
                or receipt.mode is not self.mode
                or incident is None
                or not incident.requires_restart
                or incident.resolved_at is None
                or receipt.checkpoint_recorded_at < self.started_at
                or receipt.resumed_at > self.ended_at
                or chain_head.heartbeat_sha256 != receipt.pre_restart_chain_head_sha256
                or chain_head.observed_at > receipt.checkpoint_recorded_at
                or receipt.checkpoint_recorded_at > incident.detected_at
                or receipt.resumed_at < incident.detected_at
                or receipt.resumed_at > incident.resolved_at
            ):
                raise ValueError("AQ-P11-RECOVERY-INCIDENT-BINDING-MISMATCH")

        expected = canonical_sha256(self.model_dump(mode="json", exclude={"session_sha256"}))
        if self.session_sha256 != expected:
            raise ValueError("AQ-P11-FORWARD-SESSION-HASH-MISMATCH")
        return self


def create_forward_session(
    *,
    pair_id: str,
    run_id: str,
    mode: ForwardMode,
    run_kind: ForwardRunKind,
    evidence_tier: EvidenceTier,
    started_at: UtcDateTime,
    ended_at: UtcDateTime,
    heartbeats: tuple[ForwardHeartbeat, ...],
    samples: tuple[ForwardSample, ...],
    incident_log: ForwardIncidentLog,
    recovery_receipts: tuple[ForwardRecoveryReceipt, ...],
    time_compressed: bool,
) -> ForwardSession:
    payload = {
        "pair_id": pair_id,
        "run_id": run_id,
        "mode": mode,
        "run_kind": run_kind,
        "evidence_tier": evidence_tier,
        "started_at": started_at,
        "ended_at": ended_at,
        "heartbeats": heartbeats,
        "samples": tuple(sorted(samples, key=lambda item: (item.decision_time, item.sample_id))),
        "incident_log": incident_log,
        "recovery_receipts": recovery_receipts,
        "time_compressed": time_compressed,
        "backtest_substitution": False,
        "final_holdout_opened": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
        "alpha_promotion_eligible": False,
    }
    return cast("ForwardSession", _hashed_model(ForwardSession, payload, "session_sha256"))


class ForwardProofPolicy(DomainModel):
    version: str = Field(min_length=1, max_length=80)
    approved_at: UtcDateTime
    effective_from: UtcDateTime
    minimum_calendar_days: int = Field(ge=30)
    minimum_independent_event_count: int = Field(ge=2)
    independent_event_threshold_rationale: str = Field(min_length=20, max_length=1000)
    maximum_heartbeat_gap_seconds: int = Field(ge=1, le=3600)
    maximum_truth_brier_score: UnitInterval
    maximum_truth_calibration_error: UnitInterval
    maximum_forecast_mae: NonNegativeDecimal
    minimum_forecast_direction_accuracy: UnitInterval
    maximum_cost_mae: NonNegativeDecimal
    maximum_cost_underprediction_rate: UnitInterval
    maximum_event_increment_mae: NonNegativeDecimal
    minimum_event_direction_accuracy: UnitInterval
    threshold_locked_before_run: Literal[True] = True
    final_holdout_opened: Literal[False] = False
    policy_sha256: str

    @field_validator("policy_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forward proof policy hash")

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.approved_at > self.effective_from:
            raise ValueError("AQ-P11-FORWARD-POLICY-NOT-PRECOMMITTED")
        if self.minimum_forecast_direction_accuracy < Decimal("0.5"):
            raise ValueError("forecast direction threshold must be at least chance level")
        if self.minimum_event_direction_accuracy < Decimal("0.5"):
            raise ValueError("event direction threshold must be at least chance level")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        if self.policy_sha256 != expected:
            raise ValueError("AQ-P11-FORWARD-POLICY-HASH-MISMATCH")
        return self


def create_forward_proof_policy(
    *,
    version: str,
    approved_at: UtcDateTime,
    effective_from: UtcDateTime,
    minimum_calendar_days: int,
    minimum_independent_event_count: int,
    independent_event_threshold_rationale: str,
    maximum_heartbeat_gap_seconds: int,
    maximum_truth_brier_score: Decimal,
    maximum_truth_calibration_error: Decimal,
    maximum_forecast_mae: Decimal,
    minimum_forecast_direction_accuracy: Decimal,
    maximum_cost_mae: Decimal,
    maximum_cost_underprediction_rate: Decimal,
    maximum_event_increment_mae: Decimal,
    minimum_event_direction_accuracy: Decimal,
) -> ForwardProofPolicy:
    payload = {
        "version": version,
        "approved_at": approved_at,
        "effective_from": effective_from,
        "minimum_calendar_days": minimum_calendar_days,
        "minimum_independent_event_count": minimum_independent_event_count,
        "independent_event_threshold_rationale": independent_event_threshold_rationale,
        "maximum_heartbeat_gap_seconds": maximum_heartbeat_gap_seconds,
        "maximum_truth_brier_score": maximum_truth_brier_score,
        "maximum_truth_calibration_error": maximum_truth_calibration_error,
        "maximum_forecast_mae": maximum_forecast_mae,
        "minimum_forecast_direction_accuracy": minimum_forecast_direction_accuracy,
        "maximum_cost_mae": maximum_cost_mae,
        "maximum_cost_underprediction_rate": maximum_cost_underprediction_rate,
        "maximum_event_increment_mae": maximum_event_increment_mae,
        "minimum_event_direction_accuracy": minimum_event_direction_accuracy,
        "threshold_locked_before_run": True,
        "final_holdout_opened": False,
    }
    return cast(
        "ForwardProofPolicy",
        _hashed_model(ForwardProofPolicy, payload, "policy_sha256"),
    )


class TruthCalibrationMetrics(DomainModel):
    sample_count: int = Field(gt=0)
    mean_predicted_probability: UnitInterval
    realized_positive_rate: UnitInterval
    brier_score: UnitInterval
    expected_calibration_error: UnitInterval


class ForecastCalibrationMetrics(DomainModel):
    sample_count: int = Field(gt=0)
    mean_predicted_return: FiniteDecimal
    mean_realized_return: FiniteDecimal
    mean_bias: FiniteDecimal
    mean_absolute_error: NonNegativeDecimal
    direction_accuracy: UnitInterval


class CostCalibrationMetrics(DomainModel):
    sample_count: int = Field(gt=0)
    mean_predicted_cost: NonNegativeDecimal
    mean_realized_cost: NonNegativeDecimal
    mean_bias: FiniteDecimal
    mean_absolute_error: NonNegativeDecimal
    underprediction_rate: UnitInterval


class EventIncrementAttributionMetrics(DomainModel):
    sample_count: int = Field(gt=0)
    independent_event_count: int = Field(gt=0)
    mean_predicted_increment: FiniteDecimal
    mean_realized_increment: FiniteDecimal
    mean_absolute_error: NonNegativeDecimal
    direction_accuracy: UnitInterval


def _truth_metrics(samples: tuple[ForwardSample, ...]) -> TruthCalibrationMetrics:
    probabilities = tuple(item.predicted_truth_probability for item in samples)
    outcomes = tuple(Decimal("1") if item.realized_truth else Decimal("0") for item in samples)
    mean_probability = _mean(probabilities)
    realized_rate = _mean(outcomes)
    buckets: dict[int, list[tuple[Decimal, Decimal]]] = {}
    for probability, outcome in zip(probabilities, outcomes, strict=True):
        bucket = min(9, int(probability * Decimal("10")))
        buckets.setdefault(bucket, []).append((probability, outcome))
    expected_calibration_error = sum(
        (
            Decimal(len(items))
            / Decimal(len(samples))
            * abs(_mean(tuple(item[0] for item in items)) - _mean(tuple(item[1] for item in items)))
            for items in buckets.values()
        ),
        start=Decimal("0"),
    )
    return TruthCalibrationMetrics(
        sample_count=len(samples),
        mean_predicted_probability=mean_probability,
        realized_positive_rate=realized_rate,
        brier_score=_mean(
            tuple((left - right) ** 2 for left, right in zip(probabilities, outcomes, strict=True))
        ),
        expected_calibration_error=canonical_result(expected_calibration_error),
    )


def _forecast_metrics(samples: tuple[ForwardSample, ...]) -> ForecastCalibrationMetrics:
    predicted = tuple(item.predicted_return for item in samples)
    realized = tuple(item.realized_return for item in samples)
    hits = tuple(
        Decimal("1") if _same_direction(left, right) else Decimal("0")
        for left, right in zip(predicted, realized, strict=True)
    )
    return ForecastCalibrationMetrics(
        sample_count=len(samples),
        mean_predicted_return=_mean(predicted),
        mean_realized_return=_mean(realized),
        mean_bias=_mean(
            tuple(left - right for left, right in zip(predicted, realized, strict=True))
        ),
        mean_absolute_error=_mean(
            tuple(abs(left - right) for left, right in zip(predicted, realized, strict=True))
        ),
        direction_accuracy=_mean(hits),
    )


def _cost_metrics(samples: tuple[ForwardSample, ...]) -> CostCalibrationMetrics:
    predicted = tuple(item.predicted_cost for item in samples)
    realized = tuple(item.realized_cost for item in samples)
    underpredicted = tuple(
        Decimal("1") if left < right else Decimal("0")
        for left, right in zip(predicted, realized, strict=True)
    )
    return CostCalibrationMetrics(
        sample_count=len(samples),
        mean_predicted_cost=_mean(predicted),
        mean_realized_cost=_mean(realized),
        mean_bias=_mean(
            tuple(left - right for left, right in zip(predicted, realized, strict=True))
        ),
        mean_absolute_error=_mean(
            tuple(abs(left - right) for left, right in zip(predicted, realized, strict=True))
        ),
        underprediction_rate=_mean(underpredicted),
    )


def _event_metrics(samples: tuple[ForwardSample, ...]) -> EventIncrementAttributionMetrics:
    predicted = tuple(item.predicted_event_increment for item in samples)
    realized = tuple(item.realized_event_increment for item in samples)
    hits = tuple(
        Decimal("1") if _same_direction(left, right) else Decimal("0")
        for left, right in zip(predicted, realized, strict=True)
    )
    return EventIncrementAttributionMetrics(
        sample_count=len(samples),
        independent_event_count=len({item.event_independence_key for item in samples}),
        mean_predicted_increment=_mean(predicted),
        mean_realized_increment=_mean(realized),
        mean_absolute_error=_mean(
            tuple(abs(left - right) for left, right in zip(predicted, realized, strict=True))
        ),
        direction_accuracy=_mean(hits),
    )


def _derive_mode_report(session: ForwardSession, policy: ForwardProofPolicy) -> dict[str, object]:
    validated_session = ForwardSession.model_validate_json(session.model_dump_json())
    validated_policy = ForwardProofPolicy.model_validate_json(policy.model_dump_json())
    samples = validated_session.samples
    truth = _truth_metrics(samples)
    forecast = _forecast_metrics(samples)
    cost = _cost_metrics(samples)
    event = _event_metrics(samples)
    elapsed_seconds = _elapsed_seconds(validated_session.started_at, validated_session.ended_at)
    elapsed_days = canonical_result(elapsed_seconds / Decimal("86400"))
    gaps = tuple(
        _elapsed_seconds(left.observed_at, right.observed_at)
        for left, right in zip(
            validated_session.heartbeats,
            validated_session.heartbeats[1:],
            strict=False,
        )
    )
    maximum_gap = max(gaps)
    continuity_pass = maximum_gap <= Decimal(validated_policy.maximum_heartbeat_gap_seconds)
    no_future_corrections_pass = not any(
        item.future_correction_attempted for item in validated_session.incident_log.incidents
    )
    incident_log_pass = validated_session.incident_log.log_complete and all(
        item.resolved_at is not None
        and not item.data_loss_detected
        and not item.future_correction_attempted
        for item in validated_session.incident_log.incidents
    )
    recovery_pass = bool(validated_session.recovery_receipts) and all(
        item.restored_without_loss and item.gap_count == 0 and item.duplicate_count == 0
        for item in validated_session.recovery_receipts
    )
    truth_pass = (
        truth.brier_score <= validated_policy.maximum_truth_brier_score
        and truth.expected_calibration_error <= validated_policy.maximum_truth_calibration_error
    )
    forecast_pass = (
        forecast.mean_absolute_error <= validated_policy.maximum_forecast_mae
        and forecast.direction_accuracy >= validated_policy.minimum_forecast_direction_accuracy
    )
    cost_pass = (
        cost.mean_absolute_error <= validated_policy.maximum_cost_mae
        and cost.underprediction_rate <= validated_policy.maximum_cost_underprediction_rate
    )
    event_pass = (
        event.mean_absolute_error <= validated_policy.maximum_event_increment_mae
        and event.direction_accuracy >= validated_policy.minimum_event_direction_accuracy
    )

    reasons: set[str] = set()
    extend_reasons: set[str] = set()
    if validated_session.run_kind is not ForwardRunKind.WALL_CLOCK_FORWARD:
        extend_reasons.add("DEVELOPMENT_FIXTURE_NOT_FORWARD")
    if (
        validated_policy.approved_at > validated_session.started_at
        or validated_policy.effective_from > validated_session.started_at
    ):
        reasons.add("FORWARD_POLICY_NOT_EFFECTIVE_BEFORE_RUN")
    if elapsed_days < Decimal(validated_policy.minimum_calendar_days):
        extend_reasons.add("MINIMUM_30_CALENDAR_DAYS_NOT_MET")
    if event.independent_event_count < validated_policy.minimum_independent_event_count:
        extend_reasons.add("INDEPENDENT_EVENT_SAMPLE_INSUFFICIENT")
    if not continuity_pass:
        reasons.add("CONTINUOUS_FORWARD_GAP_EXCEEDED")
    if not no_future_corrections_pass:
        reasons.add("FUTURE_CORRECTION_DETECTED")
    if not incident_log_pass:
        reasons.add("INCIDENT_LOG_INCOMPLETE_OR_UNRESOLVED")
    if not recovery_pass:
        reasons.add("RESTART_RECOVERY_NOT_PROVEN")
    if not truth_pass:
        reasons.add("TRUTH_CALIBRATION_FAILED")
    if not forecast_pass:
        reasons.add("FORECAST_CALIBRATION_FAILED")
    if not cost_pass:
        reasons.add("COST_CALIBRATION_FAILED")
    if not event_pass:
        reasons.add("EVENT_INCREMENT_ATTRIBUTION_FAILED")

    if reasons:
        status = ForwardProofStatus.FAIL_CLOSED
    elif extend_reasons:
        status = ForwardProofStatus.EXTEND_PAPER
    else:
        status = ForwardProofStatus.PASS
    all_reasons = reasons | extend_reasons
    if not all_reasons:
        all_reasons.add("FORWARD_MODE_PROOF_PASS")
    return {
        "session": validated_session,
        "policy": validated_policy,
        "elapsed_calendar_days": elapsed_days,
        "maximum_heartbeat_gap_seconds": maximum_gap,
        "continuous_forward_data_pass": continuity_pass,
        "no_future_corrections_pass": no_future_corrections_pass,
        "truth_calibration": truth,
        "truth_calibration_pass": truth_pass,
        "forecast_calibration": forecast,
        "forecast_calibration_pass": forecast_pass,
        "cost_calibration": cost,
        "cost_calibration_pass": cost_pass,
        "event_increment_attribution": event,
        "event_increment_attribution_pass": event_pass,
        "incident_log_pass": incident_log_pass,
        "restart_recovery_pass": recovery_pass,
        "status": status,
        "reason_codes": tuple(sorted(all_reasons)),
        "backtest_substitution_rejected": True,
        "alpha_promotion_eligible": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
    }


class ForwardModeProofReport(DomainModel):
    session: ForwardSession
    policy: ForwardProofPolicy
    elapsed_calendar_days: NonNegativeDecimal
    maximum_heartbeat_gap_seconds: NonNegativeDecimal
    continuous_forward_data_pass: bool
    no_future_corrections_pass: bool
    truth_calibration: TruthCalibrationMetrics
    truth_calibration_pass: bool
    forecast_calibration: ForecastCalibrationMetrics
    forecast_calibration_pass: bool
    cost_calibration: CostCalibrationMetrics
    cost_calibration_pass: bool
    event_increment_attribution: EventIncrementAttributionMetrics
    event_increment_attribution_pass: bool
    incident_log_pass: bool
    restart_recovery_pass: bool
    status: ForwardProofStatus
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    backtest_substitution_rejected: Literal[True] = True
    alpha_promotion_eligible: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    report_sha256: str

    @field_validator("report_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="forward mode report hash")

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        expected = _derive_mode_report(self.session, self.policy)
        expected_model = type(self).model_construct(
            **cast("dict[str, Any]", expected), report_sha256=self.report_sha256
        )
        actual = self.model_dump(exclude={"report_sha256"}, mode="json")
        expected_dump = expected_model.model_dump(exclude={"report_sha256"}, mode="json")
        if actual != expected_dump:
            raise ValueError("AQ-P11-FORWARD-MODE-REPORT-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("AQ-P11-FORWARD-MODE-REPORT-HASH-MISMATCH")
        return self


def evaluate_forward_mode(
    *, session: ForwardSession, policy: ForwardProofPolicy
) -> ForwardModeProofReport:
    payload = _derive_mode_report(session, policy)
    return cast(
        "ForwardModeProofReport",
        _hashed_model(ForwardModeProofReport, payload, "report_sha256"),
    )


def _paired_prediction_signature(sample: ForwardSample) -> tuple[object, ...]:
    return (
        sample.sample_id,
        sample.event_independence_key,
        sample.decision_report_sha256,
        sample.prediction_input_sha256,
        sample.source_available_at,
        sample.decision_time,
        sample.prediction_recorded_at,
        sample.outcome_available_at,
        sample.predicted_truth_probability,
        sample.predicted_return,
        sample.predicted_cost,
        sample.predicted_event_increment,
    )


def _derive_paper_shadow_proof(
    paper: ForwardModeProofReport,
    shadow: ForwardModeProofReport,
) -> dict[str, object]:
    validated_paper = ForwardModeProofReport.model_validate_json(paper.model_dump_json())
    validated_shadow = ForwardModeProofReport.model_validate_json(shadow.model_dump_json())
    if validated_paper.session.mode is not ForwardMode.PAPER:
        raise ValueError("AQ-P11-PAPER-REPORT-MODE-MISMATCH")
    if validated_shadow.session.mode is not ForwardMode.SHADOW:
        raise ValueError("AQ-P11-SHADOW-REPORT-MODE-MISMATCH")
    if validated_paper.policy != validated_shadow.policy:
        raise ValueError("AQ-P11-PAPER-SHADOW-POLICY-SPLICE")
    if (
        validated_paper.session.pair_id != validated_shadow.session.pair_id
        or validated_paper.session.started_at != validated_shadow.session.started_at
        or validated_paper.session.ended_at != validated_shadow.session.ended_at
    ):
        raise ValueError("AQ-P11-PAPER-SHADOW-WINDOW-SPLICE")
    paper_predictions = tuple(
        _paired_prediction_signature(item) for item in validated_paper.session.samples
    )
    shadow_predictions = tuple(
        _paired_prediction_signature(item) for item in validated_shadow.session.samples
    )
    if paper_predictions != shadow_predictions:
        raise ValueError("AQ-P11-PAPER-SHADOW-PREDICTION-SPLICE")

    forward_pass = (
        validated_paper.status is ForwardProofStatus.PASS
        and validated_shadow.status is ForwardProofStatus.PASS
    )
    return {
        "paper": validated_paper,
        "shadow": validated_shadow,
        "decision": (
            ForwardProofDecision.P11_FORWARD_PASS
            if forward_pass
            else ForwardProofDecision.NO_PROMOTION
        ),
        "next_action": (
            ForwardNextAction.PROCEED_TO_TESTNET_READINESS
            if forward_pass
            else ForwardNextAction.EXTEND_PAPER
        ),
        "truth_calibration_pass": (
            validated_paper.truth_calibration_pass and validated_shadow.truth_calibration_pass
        ),
        "forecast_calibration_pass": (
            validated_paper.forecast_calibration_pass and validated_shadow.forecast_calibration_pass
        ),
        "cost_calibration_pass": (
            validated_paper.cost_calibration_pass and validated_shadow.cost_calibration_pass
        ),
        "paper_pass": validated_paper.status is ForwardProofStatus.PASS,
        "shadow_pass": validated_shadow.status is ForwardProofStatus.PASS,
        "final_holdout_opened": False,
        "canary_review_ready": False,
        "alpha_promotion_eligible": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
    }


class PaperShadowForwardProof(DomainModel):
    paper: ForwardModeProofReport
    shadow: ForwardModeProofReport
    decision: ForwardProofDecision
    next_action: ForwardNextAction
    truth_calibration_pass: bool
    forecast_calibration_pass: bool
    cost_calibration_pass: bool
    paper_pass: bool
    shadow_pass: bool
    final_holdout_opened: Literal[False] = False
    canary_review_ready: Literal[False] = False
    alpha_promotion_eligible: Literal[False] = False
    order_submission_enabled: Literal[False] = False
    live_trading_locked: Literal[True] = True
    proof_sha256: str

    @field_validator("proof_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return ensure_sha256(value, field_name="paper shadow forward proof hash")

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        expected = _derive_paper_shadow_proof(self.paper, self.shadow)
        expected_model = type(self).model_construct(
            **cast("dict[str, Any]", expected), proof_sha256=self.proof_sha256
        )
        actual = self.model_dump(mode="json", exclude={"proof_sha256"})
        expected_dump = expected_model.model_dump(mode="json", exclude={"proof_sha256"})
        if actual != expected_dump:
            raise ValueError("AQ-P11-PAPER-SHADOW-PROOF-RECOMPUTATION-MISMATCH")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"proof_sha256"}))
        if self.proof_sha256 != expected_hash:
            raise ValueError("AQ-P11-PAPER-SHADOW-PROOF-HASH-MISMATCH")
        return self


def evaluate_paper_shadow_forward(
    *,
    paper: ForwardModeProofReport,
    shadow: ForwardModeProofReport,
) -> PaperShadowForwardProof:
    payload = _derive_paper_shadow_proof(paper, shadow)
    return cast(
        "PaperShadowForwardProof",
        _hashed_model(PaperShadowForwardProof, payload, "proof_sha256"),
    )
