from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.domain.intelligence import QualityState
from aegisquant.research.baselines import (
    BaselineObservation,
    BaselineStrategyKind,
    generate_strategy_targets,
    screen_strategy,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def observation(index: int, **updates: object) -> BaselineObservation:
    payload: dict[str, object] = {
        "sample_id": f"sample-{index}",
        "instrument_id": "BTCUSDT",
        "decision_time": NOW + timedelta(hours=index),
        "realized_next_return": Decimal("0.01") if index % 2 == 0 else Decimal("-0.02"),
        "trend_score": Decimal("1") if index % 2 == 0 else Decimal("-1"),
        "cross_sectional_rank": Decimal("0.9") if index % 2 == 0 else Decimal("0.1"),
        "funding_rate": Decimal("0.003"),
        "basis": Decimal("0.002"),
        "official_event": True,
        "independent_source_count": 2,
        "event_novelty": Decimal("0.8"),
        "event_stance": Decimal("0.9"),
        "manipulation_risk": Decimal("0.1"),
        "market_reflection": Decimal("0.2"),
        "quality_state": QualityState.GOOD,
        "cost_rate": Decimal("0.001"),
    }
    payload.update(updates)
    return BaselineObservation.model_validate(payload)


def test_every_required_strategy_emits_bounded_targets() -> None:
    values = (observation(0), observation(1))
    assert set(BaselineStrategyKind) == {
        BaselineStrategyKind.CASH,
        BaselineStrategyKind.BUY_AND_HOLD,
        BaselineStrategyKind.SIMPLE_TREND,
        BaselineStrategyKind.CROSS_SECTIONAL,
        BaselineStrategyKind.FUNDING_BASIS,
        BaselineStrategyKind.OFFICIAL_EVENT_RISK_OVERLAY,
        BaselineStrategyKind.CONSERVATIVE_EVENT,
    }
    for strategy in BaselineStrategyKind:
        targets = generate_strategy_targets(strategy, values)
        assert len(targets) == len(values)
        assert all(abs(item.target_fraction) <= 1 for item in targets)


def test_conservative_event_requires_corroboration_quality_and_low_manipulation() -> None:
    rejected = observation(
        0,
        official_event=False,
        independent_source_count=1,
        manipulation_risk=Decimal("0.9"),
    )
    target = generate_strategy_targets(BaselineStrategyKind.CONSERVATIVE_EVENT, (rejected,))[0]
    assert target.monitor_only is True
    assert target.target_fraction == 0
    assert target.reason_code == "MONITOR_ONLY"

    accepted = generate_strategy_targets(
        BaselineStrategyKind.CONSERVATIVE_EVENT, (observation(1),)
    )[0]
    assert accepted.monitor_only is False
    assert accepted.target_fraction == Decimal("0.25")


def test_simple_trend_screening_matches_independent_gross_cost_net_math() -> None:
    values = (observation(0), observation(1), observation(2))
    result = screen_strategy(BaselineStrategyKind.SIMPLE_TREND, values)
    targets = (Decimal("1"), Decimal("-1"), Decimal("1"))
    returns = (Decimal("0.01"), Decimal("-0.02"), Decimal("0.01"))
    gross = sum(
        (target * value for target, value in zip(targets, returns, strict=True)), Decimal("0")
    )
    turnover = Decimal("1") + Decimal("2") + Decimal("2")
    cost = turnover * Decimal("0.001")
    assert result.gross_return == gross == Decimal("0.04")
    assert result.turnover == turnover
    assert result.transaction_cost == cost
    assert result.net_return == gross - cost == Decimal("0.035")
    assert result.authoritative_backtest_required is True
