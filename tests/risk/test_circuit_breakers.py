"""All eight independent circuit-breaker families."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from aegisquant.risk.engine import evaluate_circuit_breakers
from aegisquant.risk.models import (
    CircuitBreakerType,
    MajorEventType,
    RiskAction,
    RiskConfirmation,
    RiskEvent,
    RiskState,
)
from tests.p11_helpers import AS_OF, DECISION_TIME, risk_policy, snapshot


def test_data_and_model_staleness_reject_new_risk() -> None:
    outcome = evaluate_circuit_breakers(
        snapshot=snapshot(stale_seconds=31),
        policy=risk_policy(),
        decision_time=DECISION_TIME,
    )
    assert outcome.state is RiskState.CAUTION
    assert outcome.new_risk_allowed is False
    assert {item.breaker_type for item in outcome.alerts} == {
        CircuitBreakerType.DATA,
        CircuitBreakerType.MODEL,
    }


def test_loss_margin_liquidity_venue_security_and_event_breakers() -> None:
    event = RiskEvent(
        risk_event_id="official-security-event",
        breaker_type=CircuitBreakerType.MAJOR_EVENT,
        confirmation=RiskConfirmation.CONFIRMED,
        action=RiskAction.HALT,
        major_event_type=MajorEventType.OFFICIAL_SECURITY_INCIDENT,
        observed_at=AS_OF - timedelta(seconds=1),
        available_at=AS_OF,
        evidence_ids=("official-advisory",),
        official_source=True,
    )
    outcome = evaluate_circuit_breakers(
        snapshot=snapshot(
            daily_pnl=Decimal("-0.06"),
            drawdown=Decimal("0.11"),
            margin=Decimal("0.81"),
            liquidity=Decimal("0.19"),
            venue_operational=False,
            security_clear=False,
            major_event_clear=False,
        ),
        policy=risk_policy(),
        decision_time=DECISION_TIME,
        events=(event,),
    )
    assert outcome.state is RiskState.HALTED
    assert outcome.target_scale == 0
    assert {item.breaker_type for item in outcome.alerts} >= {
        CircuitBreakerType.LOSS,
        CircuitBreakerType.MARGIN,
        CircuitBreakerType.LIQUIDITY,
        CircuitBreakerType.VENUE,
        CircuitBreakerType.SECURITY,
        CircuitBreakerType.MAJOR_EVENT,
    }
