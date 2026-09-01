"""Signed official playbook and rumor-containment tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.risk.models import (
    CircuitBreakerType,
    MajorEventType,
    RiskAction,
    RiskConfirmation,
    RiskEvent,
    RiskState,
)
from aegisquant.risk.playbooks import apply_event_playbook, verify_signed_playbooks
from tests.p11_helpers import (
    AS_OF,
    playbook_registry,
    risk_policy,
    signed_playbooks,
    trusted_public_keys,
)


def event(*, confirmation: RiskConfirmation, action: RiskAction, reduction: Decimal) -> RiskEvent:
    return RiskEvent(
        risk_event_id=f"event-{confirmation.value.lower()}-{action.value.lower()}",
        breaker_type=CircuitBreakerType.MAJOR_EVENT,
        confirmation=confirmation,
        action=action,
        major_event_type=MajorEventType.OFFICIAL_SECURITY_INCIDENT,
        observed_at=AS_OF - timedelta(seconds=1),
        available_at=AS_OF,
        evidence_ids=("source-evidence",),
        official_source=confirmation is RiskConfirmation.CONFIRMED,
        llm_generated=confirmation is RiskConfirmation.RUMOR,
        requested_reduction_fraction=reduction,
    )


def test_registry_signature_covers_all_five_official_event_types() -> None:
    registry = verify_signed_playbooks(
        signed_playbooks(), trusted_public_keys=trusted_public_keys()
    )
    assert {item.event_type for item in registry.playbooks} == set(MajorEventType)
    decision = apply_event_playbook(
        event=event(
            confirmation=RiskConfirmation.CONFIRMED,
            action=RiskAction.MONITOR,
            reduction=Decimal("0"),
        ),
        registry=registry,
        policy=risk_policy(),
    )
    assert decision.action is RiskAction.HALT
    assert decision.target_state is RiskState.HALTED


def test_rumor_can_only_monitor_tighten_or_reduce_with_bounded_fraction() -> None:
    registry = playbook_registry()
    contained = apply_event_playbook(
        event=event(
            confirmation=RiskConfirmation.RUMOR,
            action=RiskAction.REDUCE,
            reduction=Decimal("0.20"),
        ),
        registry=registry,
        policy=risk_policy(),
    )
    assert contained.target_state is RiskState.REDUCE_ONLY
    assert contained.llm_full_liquidation_allowed is False
    with pytest.raises(ValueError, match="ACTION-PROHIBITED"):
        apply_event_playbook(
            event=event(
                confirmation=RiskConfirmation.RUMOR,
                action=RiskAction.HALT,
                reduction=Decimal("0"),
            ),
            registry=registry,
            policy=risk_policy(),
        )
    with pytest.raises(ValueError, match="REDUCTION-LIMIT"):
        apply_event_playbook(
            event=event(
                confirmation=RiskConfirmation.RUMOR,
                action=RiskAction.REDUCE,
                reduction=Decimal("1"),
            ),
            registry=registry,
            policy=risk_policy(),
        )
