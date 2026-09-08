from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.portfolio.economic_gate import (
    EconomicAction,
    EconomicGatePolicy,
    decide_economic_transition,
)
from aegisquant.portfolio.event_risk_overlay import EventRiskOverlay
from aegisquant.portfolio.transition_costs import ExecutionLegCost, TransitionCostEstimate
from aegisquant.research.models.economic_gate import CalibrationStatus, EconomicForecast


def test_event_overlay_cannot_create_direction_and_only_tightens_entry_and_size() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    overlay = EventRiskOverlay(
        available_time=now,
        valid_until=now + timedelta(hours=1),
        position_scale=Decimal("0.5"),
        entry_hurdle_multiplier=Decimal("2"),
        expected_slippage_multiplier=Decimal("2"),
        evidence_sha256="1" * 64,
    )
    leg = ExecutionLegCost(
        fee=Decimal("0.001"),
        half_spread=Decimal("0.0001"),
        slippage=Decimal("0.0001"),
        impact=Decimal("0"),
    )
    forecast = EconomicForecast(
        expected_gross_return=Decimal("0.1"),
        q10_return=Decimal("0.09"),
        q50_return=Decimal("0.1"),
        q90_return=Decimal("0.11"),
        p_net_positive=Decimal("0.9"),
        prediction_uncertainty=Decimal("0.01"),
        available_time=now,
        calibration_status=CalibrationStatus.VALIDATION_CALIBRATED,
        calibrated_through=now - timedelta(days=1),
        calibration_sha256="2" * 64,
    )

    def decide(trend: bool, current: Decimal = Decimal("0"), risk: EventRiskOverlay | None = None):
        return decide_economic_transition(
            policy=EconomicGatePolicy(),
            forecast=forecast,
            costs=TransitionCostEstimate(entry=leg, exit=leg, available_time=now, source="fixture"),
            decision_time=now,
            current_weight=current,
            trend_candidate=trend,
            trend_exit_confirmed=not trend,
            data_quality_passed=True,
            risk_allows_entry=True,
            volatility_sizing=False,
            event_overlay=risk,
        )

    assert decide(False, risk=overlay).action is EconomicAction.NO_TRADE
    base, tightened = decide(True), decide(True, risk=overlay)
    assert tightened.target_weight == base.target_weight / 2
    assert tightened.entry_hurdle > base.entry_hurdle
    assert decide(True, Decimal("0.8"), overlay).action is EconomicAction.REDUCE
    assert (
        decide(True, Decimal("0.8"), overlay.model_copy(update={"risk_veto": True})).action
        is EconomicAction.EXIT_LONG
    )
    with pytest.raises(ValueError, match="not yet available"):
        decide(True, risk=overlay.model_copy(update={"available_time": now + timedelta(seconds=1)}))


def test_llm_buy_sell_or_position_direction_fields_are_forbidden() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="Extra inputs"):
        EventRiskOverlay.model_validate(
            {
                "available_time": now,
                "valid_until": now + timedelta(hours=1),
                "evidence_sha256": "1" * 64,
                "direction": "BUY",
            }
        )
