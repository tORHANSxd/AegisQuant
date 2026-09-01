"""Risk-bound intent translation and deterministic client identity."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.execution.commands import command_content_sha256, translate_order_intent
from aegisquant.execution.models import ExecutionEnvironment
from aegisquant.risk.models import RiskDecisionStatus, RiskState
from tests.p12_helpers import (
    NOW,
    STRATEGY,
    command,
    decision,
    intent,
    reference_price,
    rules,
)


def test_translation_is_deterministic_and_content_addressed() -> None:
    first = command()
    second = command()
    assert first == second
    assert first.content_sha256 == command_content_sha256(first, include_hash=False)
    assert str(first.command.client_order_id).startswith("aq-")
    assert first.identity.checksum == str(first.command.client_order_id)[-5:]


def test_rejected_risk_decision_cannot_reach_command_boundary() -> None:
    rejected = decision().model_copy(
        update={
            "status": RiskDecisionStatus.REJECTED,
            "state": RiskState.NORMAL,
            "new_risk_allowed": False,
            "approved_targets": (),
        }
    )
    with pytest.raises(ValueError, match="NOT-ACTIONABLE"):
        translate_order_intent(
            intent=intent(),
            decision=rejected,
            strategy_id=STRATEGY,
            release_id="release-p12-v1",
            venue_id=rules().venue_id,
            environment=ExecutionEnvironment.SIMULATED,
            rules=rules(),
            reference_price=reference_price(),
            issued_at=NOW + timedelta(seconds=2),
        )


def test_expired_risk_or_intent_is_rejected() -> None:
    with pytest.raises(ValueError, match="EXPIRED"):
        translate_order_intent(
            intent=intent(),
            decision=decision(),
            strategy_id=STRATEGY,
            release_id="release-p12-v1",
            venue_id=rules().venue_id,
            environment=ExecutionEnvironment.SIMULATED,
            rules=rules(),
            reference_price=reference_price(),
            issued_at=NOW + timedelta(minutes=6),
        )


def test_non_finite_or_nonpositive_notional_never_validates() -> None:
    payload = command().model_dump()
    payload["notional"] = Decimal("NaN")
    with pytest.raises(ValueError, match="finite"):
        command().__class__.model_validate(payload)
