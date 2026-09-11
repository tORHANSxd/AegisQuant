"""Monotonic-safe risk state transitions and deterministic control replay."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.risk.models import RiskState
from aegisquant.risk.policy import RecoveryCondition

SAFETY_RANK = {
    RiskState.NORMAL: 0,
    RiskState.CAUTION: 1,
    RiskState.REDUCE_ONLY: 2,
    RiskState.HALTED: 3,
}


class RecoveryAssessment(DomainModel):
    data_fresh: bool
    model_fresh: bool
    ledger_reconciled: bool
    margin_safe: bool
    liquidity_safe: bool
    venue_operational: bool
    security_clear: bool
    major_event_clear: bool

    def satisfied(self) -> frozenset[RecoveryCondition]:
        mapping = {
            RecoveryCondition.DATA_FRESH: self.data_fresh,
            RecoveryCondition.MODEL_FRESH: self.model_fresh,
            RecoveryCondition.LEDGER_RECONCILED: self.ledger_reconciled,
            RecoveryCondition.MARGIN_SAFE: self.margin_safe,
            RecoveryCondition.LIQUIDITY_SAFE: self.liquidity_safe,
            RecoveryCondition.VENUE_OPERATIONAL: self.venue_operational,
            RecoveryCondition.SECURITY_CLEAR: self.security_clear,
            RecoveryCondition.MAJOR_EVENT_CLEAR: self.major_event_clear,
        }
        return frozenset(condition for condition, passed in mapping.items() if passed)


class RiskTransitionRecord(DomainModel):
    sequence: int = Field(ge=1)
    previous_state: RiskState
    target_state: RiskState
    automatic: bool
    actor: str
    reason_code: str
    occurred_at: UtcDateTime
    recovery_conditions: tuple[RecoveryCondition, ...]


class RiskControlType(StrEnum):
    CAUTION = "CAUTION"
    REDUCE_ONLY = "REDUCE_ONLY"
    KILL_SWITCH = "KILL_SWITCH"
    RECOVERY_BEGIN = "RECOVERY_BEGIN"
    RECOVERY_COMPLETE = "RECOVERY_COMPLETE"


class RiskControlEvent(DomainModel):
    sequence: int = Field(ge=1)
    control_type: RiskControlType
    occurred_at: UtcDateTime
    reason_code: str
    actor: str = "independent-risk-engine"


class RiskReplayResult(DomainModel):
    initial_state: RiskState
    final_state: RiskState
    transitions: tuple[RiskTransitionRecord, ...]
    order: tuple[int, ...]


def transition_risk_state(
    *,
    sequence: int,
    current: RiskState,
    target: RiskState,
    automatic: bool,
    actor: str,
    reason_code: str,
    occurred_at: UtcDateTime,
    recovery: RecoveryAssessment | None = None,
) -> RiskTransitionRecord:
    if not actor.strip() or not reason_code.strip():
        raise ValueError("risk transition requires actor and reason")
    conditions = tuple(sorted(recovery.satisfied(), key=str)) if recovery is not None else ()
    if automatic:
        if current is RiskState.RECOVERY or target is RiskState.RECOVERY:
            raise ValueError("AQ-RISK-AUTOMATIC-RECOVERY-PROHIBITED")
        if SAFETY_RANK[target] < SAFETY_RANK[current]:
            raise ValueError("AQ-RISK-AUTOMATIC-UNSAFE-TRANSITION")
    else:
        if actor.casefold() in {"ai", "llm", "model", "strategy"}:
            raise ValueError("AQ-RISK-RECOVERY-HUMAN-AUTHORIZATION-REQUIRED")
        requires_recovery = (current is RiskState.HALTED and target is RiskState.RECOVERY) or (
            current is RiskState.RECOVERY and target in {RiskState.NORMAL, RiskState.CAUTION}
        )
        if requires_recovery and (
            recovery is None or recovery.satisfied() != frozenset(RecoveryCondition)
        ):
            raise ValueError("AQ-RISK-RECOVERY-PREREQUISITES-INCOMPLETE")
        if current is RiskState.HALTED and target not in {RiskState.HALTED, RiskState.RECOVERY}:
            raise ValueError("AQ-RISK-HALTED-MUST-ENTER-RECOVERY")
    return RiskTransitionRecord(
        sequence=sequence,
        previous_state=current,
        target_state=target,
        automatic=automatic,
        actor=actor,
        reason_code=reason_code,
        occurred_at=occurred_at,
        recovery_conditions=conditions,
    )


def replay_risk_controls(
    *,
    initial_state: RiskState,
    events: tuple[RiskControlEvent, ...],
    recovery: RecoveryAssessment,
) -> RiskReplayResult:
    if tuple(item.sequence for item in events) != tuple(range(1, len(events) + 1)):
        raise ValueError("risk control replay sequence must be contiguous")
    current = initial_state
    records: list[RiskTransitionRecord] = []
    for event in events:
        target = {
            RiskControlType.CAUTION: RiskState.CAUTION,
            RiskControlType.REDUCE_ONLY: RiskState.REDUCE_ONLY,
            RiskControlType.KILL_SWITCH: RiskState.HALTED,
            RiskControlType.RECOVERY_BEGIN: RiskState.RECOVERY,
            RiskControlType.RECOVERY_COMPLETE: RiskState.NORMAL,
        }[event.control_type]
        manual = event.control_type in {
            RiskControlType.RECOVERY_BEGIN,
            RiskControlType.RECOVERY_COMPLETE,
        }
        record = transition_risk_state(
            sequence=event.sequence,
            current=current,
            target=target,
            automatic=not manual,
            actor=event.actor,
            reason_code=event.reason_code,
            occurred_at=event.occurred_at,
            recovery=recovery if manual else None,
        )
        records.append(record)
        current = target
    return RiskReplayResult(
        initial_state=initial_state,
        final_state=current,
        transitions=tuple(records),
        order=tuple(item.sequence for item in events),
    )
