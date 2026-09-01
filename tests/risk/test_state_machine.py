"""Monotonic-safe transitions, kill switch, reduce-only, and recovery replay."""

from __future__ import annotations

from datetime import timedelta

import pytest

from aegisquant.risk.models import RiskState
from aegisquant.risk.state_machine import (
    RecoveryAssessment,
    RiskControlEvent,
    RiskControlType,
    replay_risk_controls,
    transition_risk_state,
)
from tests.p11_helpers import AS_OF


def healthy_recovery() -> RecoveryAssessment:
    return RecoveryAssessment(
        data_fresh=True,
        model_fresh=True,
        ledger_reconciled=True,
        margin_safe=True,
        liquidity_safe=True,
        venue_operational=True,
        security_clear=True,
        major_event_clear=True,
    )


def test_automatic_transition_can_only_move_to_same_or_safer_state() -> None:
    record = transition_risk_state(
        sequence=1,
        current=RiskState.NORMAL,
        target=RiskState.REDUCE_ONLY,
        automatic=True,
        actor="independent-risk-engine",
        reason_code="AQ-RISK-LOSS-LIMIT",
        occurred_at=AS_OF,
    )
    assert record.target_state is RiskState.REDUCE_ONLY
    with pytest.raises(ValueError, match="UNSAFE-TRANSITION"):
        transition_risk_state(
            sequence=2,
            current=RiskState.HALTED,
            target=RiskState.NORMAL,
            automatic=True,
            actor="independent-risk-engine",
            reason_code="unsafe",
            occurred_at=AS_OF,
        )
    with pytest.raises(ValueError, match="AUTOMATIC-RECOVERY"):
        transition_risk_state(
            sequence=2,
            current=RiskState.HALTED,
            target=RiskState.RECOVERY,
            automatic=True,
            actor="independent-risk-engine",
            reason_code="unsafe",
            occurred_at=AS_OF,
        )


def test_kill_switch_reduce_only_and_manual_recovery_are_replayable() -> None:
    events = (
        RiskControlEvent(
            sequence=1,
            control_type=RiskControlType.REDUCE_ONLY,
            occurred_at=AS_OF,
            reason_code="AQ-RISK-MARGIN-LIMIT",
        ),
        RiskControlEvent(
            sequence=2,
            control_type=RiskControlType.KILL_SWITCH,
            occurred_at=AS_OF + timedelta(seconds=1),
            reason_code="AQ-RISK-SECURITY-HALTED",
        ),
        RiskControlEvent(
            sequence=3,
            control_type=RiskControlType.RECOVERY_BEGIN,
            occurred_at=AS_OF + timedelta(seconds=2),
            reason_code="operator-started-recovery",
            actor="human-operator",
        ),
        RiskControlEvent(
            sequence=4,
            control_type=RiskControlType.RECOVERY_COMPLETE,
            occurred_at=AS_OF + timedelta(seconds=3),
            reason_code="operator-completed-recovery",
            actor="human-operator",
        ),
    )
    first = replay_risk_controls(
        initial_state=RiskState.NORMAL, events=events, recovery=healthy_recovery()
    )
    second = replay_risk_controls(
        initial_state=RiskState.NORMAL, events=events, recovery=healthy_recovery()
    )
    assert first == second
    assert [item.target_state for item in first.transitions] == [
        RiskState.REDUCE_ONLY,
        RiskState.HALTED,
        RiskState.RECOVERY,
        RiskState.NORMAL,
    ]


def test_recovery_requires_all_conditions_and_non_ai_authorization() -> None:
    incomplete = healthy_recovery().model_copy(update={"security_clear": False})
    with pytest.raises(ValueError, match="PREREQUISITES"):
        transition_risk_state(
            sequence=1,
            current=RiskState.HALTED,
            target=RiskState.RECOVERY,
            automatic=False,
            actor="human-operator",
            reason_code="try-recovery",
            occurred_at=AS_OF,
            recovery=incomplete,
        )
    with pytest.raises(ValueError, match="HUMAN-AUTHORIZATION"):
        transition_risk_state(
            sequence=1,
            current=RiskState.HALTED,
            target=RiskState.RECOVERY,
            automatic=False,
            actor="llm",
            reason_code="try-recovery",
            occurred_at=AS_OF,
            recovery=healthy_recovery(),
        )
