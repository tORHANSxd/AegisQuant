from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.domain.identifiers import ArtifactId, ContentId
from aegisquant.domain.intelligence import EngagementSnapshot
from aegisquant.research.validation import (
    EconomicPeriod,
    Regime,
    RegimeObservation,
    apply_cost_stress,
    engagement_as_of_with_delay,
    event_latency_scenarios,
    parameter_perturbations,
    point_in_time_regime_slices,
)

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)


def periods() -> tuple[EconomicPeriod, ...]:
    return (
        EconomicPeriod(
            period_id="p1",
            decision_time=NOW,
            gross_return=Decimal("0.02"),
            base_cost=Decimal("0.002"),
            net_return=Decimal("0.018"),
        ),
        EconomicPeriod(
            period_id="p2",
            decision_time=NOW + timedelta(hours=1),
            gross_return=Decimal("-0.01"),
            base_cost=Decimal("0.001"),
            net_return=Decimal("-0.011"),
        ),
    )


def engagement(name: str, available_at: datetime, value: int) -> EngagementSnapshot:
    return EngagementSnapshot(
        engagement_snapshot_id=ArtifactId(name),
        content_id=ContentId("content-1"),
        observed_time=available_at - timedelta(seconds=2),
        available_time=available_at,
        metrics={"likes": value},
    )


def test_cost_and_latency_stresses_cover_required_grid() -> None:
    stress = apply_cost_stress(periods())
    assert [item.multiplier for item in stress] == [
        Decimal("1"),
        Decimal("1.5"),
        Decimal("2"),
    ]
    assert [item.net_return for item in stress] == [
        Decimal("0.007"),
        Decimal("0.0055"),
        Decimal("0.004"),
    ]
    latency = event_latency_scenarios(NOW)
    assert [item.delay_seconds for item in latency] == [0, 5, 30, 120, 600]
    assert latency[-1].stressed_available_time == NOW + timedelta(seconds=600)


def test_delayed_engagement_never_selects_future_snapshot() -> None:
    snapshots = (
        engagement("early", NOW - timedelta(seconds=20), 1),
        engagement("late", NOW - timedelta(seconds=2), 99),
        engagement("future", NOW + timedelta(seconds=1), 999),
    )
    selected = engagement_as_of_with_delay(snapshots, decision_time=NOW, delay_seconds=5)
    assert selected is not None
    assert selected.engagement_snapshot_id == ArtifactId("early")


def test_parameter_and_regime_stress_are_deterministic_and_point_in_time() -> None:
    perturbations = parameter_perturbations({"lookback": Decimal("10"), "threshold": Decimal("2")})
    assert len(perturbations) == 8
    assert perturbations[0]["lookback"] == Decimal("9")
    assert perturbations[-1]["threshold"] == Decimal("2.2")

    regimes = (
        RegimeObservation(regime=Regime.BULL, event_time=NOW, available_time=NOW),
        RegimeObservation(
            regime=Regime.BEAR,
            event_time=NOW + timedelta(minutes=30),
            available_time=NOW + timedelta(hours=2),
        ),
    )
    slices = point_in_time_regime_slices(periods(), regimes)
    assert len(slices) == 1
    assert slices[0].regime is Regime.BULL
    assert slices[0].net_return == Decimal("0.007")
