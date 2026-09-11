"""New risk controls are opt-in and are checked through actual event fills."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from aegisquant.research.strategies.buffered_target import (
    BufferPolicy,
    RiskResizePolicy,
    Snapshot,
    TargetSmoother,
    decide_buffered_target,
    rebalance_risk_benefit,
)
from aegisquant.research.validation.cat_contract import CatAuditPolicy
from aegisquant.research.validation.cat_replay import replay_cat
from tests.integration.cat_helpers import ROOT, fixture


def test_smoother_has_exact_half_life_and_monotonic_observation_time():
    smoother = TargetSmoother()
    time = datetime(2024, 1, 1, tzinfo=UTC)
    half_life = timedelta(days=5)
    assert smoother.update(time, Decimal("0.2"), half_life) == Decimal("0.2")
    assert smoother.update(time + half_life, Decimal("0.6"), half_life) == Decimal("0.4")
    with pytest.raises(ValueError, match="increasing"):
        smoother.update(time, Decimal("0.8"), half_life)


def test_buffer_absolute_floor_asymmetry_and_hard_exit():
    time = datetime(2024, 1, 1, tzinfo=UTC)
    policy = BufferPolicy(
        restore_half_width=Decimal("0.2"),
        reduce_half_width=Decimal("0.1"),
        absolute_weight_floor=Decimal("0.03"),
    )
    snapshot = Snapshot(
        time,
        time,
        Decimal("79"),
        Decimal("100"),
        Decimal("100"),
        Decimal("200"),
        True,
        equity_quantity=Decimal("1000"),
    )
    assert decide_buffered_target(snapshot, policy).target_quantity == Decimal("79")
    asymmetric = replace(policy, absolute_weight_floor=Decimal("0"))
    assert decide_buffered_target(snapshot, asymmetric).target_quantity == Decimal("80")
    assert decide_buffered_target(
        replace(snapshot, current_quantity=Decimal("111")), asymmetric
    ).target_quantity == Decimal("110")
    assert decide_buffered_target(replace(snapshot, hard_exit=True), policy).target_quantity == 0
    with pytest.raises(ValueError, match="equity_quantity"):
        decide_buffered_target(replace(snapshot, equity_quantity=None), policy)


def test_risk_benefit_does_not_reward_moving_farther_from_raw_target():
    horizon = timedelta(days=2)
    assert (
        rebalance_risk_benefit(
            Decimal("0.3"), Decimal("0.2"), Decimal("0.4"), Decimal("0.5"), horizon
        )
        == 0
    )
    assert (
        rebalance_risk_benefit(
            Decimal("0.3"), Decimal("0.4"), Decimal("0.4"), Decimal("0.5"), horizon
        )
        > 0
    )


def run_case(*, enabled: bool, exit_at: int | None = None, cap_at: int | None = None):
    spec, bars, features = fixture()
    volatility = np.full(len(features.available_times), 0.4)
    indices = {t: i for i, t in enumerate(features.available_times)}
    for j, bar in enumerate(bars):
        volatility[indices[bar.available_time]] = (0.32, 0.55)[j // 6 % 2]
    features = replace(features, annualized_volatility=volatility)
    return replay_cat(
        root=ROOT,
        spec=spec,
        bars=bars,
        features=features,
        feature_indices=indices,
        trend_by_time={
            b.available_time: exit_at is None or j < exit_at for j, b in enumerate(bars)
        },
        forecasts={},
        level="A1",
        audit_policy=CatAuditPolicy(version="cat-audit-r2"),
        buffer_policy=BufferPolicy(),
        resize_policy=RiskResizePolicy() if enabled else None,
        risk_weight_caps={
            b.available_time: Decimal("0.1") if cap_at is not None and j >= cap_at else Decimal("1")
            for j, b in enumerate(bars)
        },
    )


def test_churn_controls_reach_orders_and_cost_gate_uses_actual_increment():
    base, _ = run_case(enabled=False)
    result, trace = run_case(enabled=True)
    assert result.fills[0].quantity == base.fills[0].quantity
    assert len(result.fills) < len(base.fills)
    assert result.positions[-1].quantity == 0
    assert abs(result.cost_identity_residual) < Decimal("1e-8")
    assert any(r.get("resize_gate_reason") == "REBALANCE_COST_EXCEEDS_RISK_BENEFIT" for r in trace)
    for row in trace:
        if row.get("resize_gate_reason") == "REBALANCE_RISK_BENEFIT_COVERS_COST":
            assert Decimal(row["rebalance_cost_equity_fraction"]) <= Decimal(
                row["rebalance_risk_benefit"]
            )
        if row.get("smoothed_risk_weight") is not None:
            assert row["smoothed_risk_weight"] == row["risk_only_weight"]
    assert all(p.cash >= 0 and p.position_value >= 0 for p in result.equity_curve)


@pytest.mark.parametrize("kind", ["trend", "cap"])
def test_hard_reduction_bypasses_new_review_clock_and_cost_gate(kind: str):
    result, trace = run_case(
        enabled=True, exit_at=2 if kind == "trend" else None, cap_at=2 if kind == "cap" else None
    )
    row = trace[2]
    assert not row["rebalance_permitted"]
    assert Decimal(row["final_weight"]) <= (Decimal("0") if kind == "trend" else Decimal("0.1"))
    assert row.get("resize_gate_reason") is None
    assert result.fills[1].side.value == "SELL"


def test_no_model_policy_required_for_smoothed_replay():
    from aegisquant.research.validation.cat_contract import CatSwitches

    spec, bars, features = fixture()
    with pytest.raises(ValueError, match="no-ML"):
        replay_cat(
            root=ROOT,
            spec=spec,
            bars=bars,
            features=features,
            feature_indices={t: i for i, t in enumerate(features.available_times)},
            trend_by_time={},
            forecasts={},
            level="A1",
            resize_policy=RiskResizePolicy(),
            audit_policy=CatAuditPolicy(switches=CatSwitches(use_model_entry_filter=True)),
        )
