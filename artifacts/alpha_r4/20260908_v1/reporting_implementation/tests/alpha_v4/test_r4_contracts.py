"""R4 checks against actual event fills, risk constraints and causal state."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import numpy as np
import pytest

from aegisquant.research.strategies.buffered_target import (
    BufferPolicy,
    Snapshot,
    decide_buffered_target,
)
from aegisquant.research.strategies.cost_aware_trend import (
    R4TrendPolicy,
    TrendPolicy,
    build_trend_features,
)
from aegisquant.research.validation.cat_contract import CatAuditPolicy
from aegisquant.research.validation.cat_replay import replay_cat
from tests.integration.cat_helpers import ROOT, fixture


def run_case(
    *,
    buffered: bool = False,
    fractions: Decimal | None = None,
    caps: Decimal | None = None,
    flat_at: int | None = None,
    terminal_exit: bool = True,
):
    spec, original_bars, features = fixture()
    bars = tuple(
        b.model_copy(
            update={
                "open": Decimal("100"),
                "close": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("99"),
            }
        )
        for b in original_bars
    )
    vol = np.full(len(features.available_times), 0.4)
    for j, b in enumerate(bars):
        index = features.available_times.index(b.available_time)
        vol[index] = (0.4, 0.55, 0.32, 0.43)[(j // 8) % 4]
    features = replace(features, annualized_volatility=vol)
    return replay_cat(
        root=ROOT,
        spec=spec,
        bars=bars,
        features=features,
        feature_indices={t: i for i, t in enumerate(features.available_times)},
        trend_by_time={
            b.available_time: flat_at is None or i < flat_at for i, b in enumerate(bars)
        },
        forecasts={},
        level="A1",
        audit_policy=CatAuditPolicy(version="cat-audit-r2"),
        buffer_policy=BufferPolicy() if buffered else None,
        signal_fractions={b.available_time: fractions for b in bars}
        if fractions is not None
        else None,
        risk_weight_caps={b.available_time: caps for b in bars} if caps is not None else None,
        terminal_exit=terminal_exit,
    )


def test_buffer_changes_only_risk_resize_and_retains_paid_exit():
    original, before = run_case()
    result, trace = run_case(buffered=True)
    assert result.fills[0] == original.fills[0]
    assert result.positions[-1].quantity == 0
    assert abs(result.cost_identity_residual) < Decimal("1e-8")
    assert any(r.get("buffer_reason") == "BUFFER_RISK_REDUCE" for r in trace)
    assert any(r.get("buffer_reason") == "BUFFER_RISK_RESTORE" for r in trace)
    for row in trace:
        if row.get("buffer_lower") is None:
            continue
        qty, target = Decimal(row["current_quantity"]), Decimal(row["target_quantity"])
        lower, upper = Decimal(row["buffer_lower"]), Decimal(row["buffer_upper"])
        assert target == min(upper, max(lower, qty))
        assert row["rebalance_permitted"]
    assert before[0]["target_quantity"] == trace[0]["target_quantity"]
    for point in result.equity_curve:
        assert point.cash >= 0
        assert point.equity == point.cash + point.position_value
    by_order = {str(o.order.backtest_order_id): o.order for o in result.orders}
    for fill in result.fills:
        assert fill.event_time > by_order[str(fill.backtest_order_id)].decision_time


def test_hard_cap_and_trend_exit_bypass_buffer_and_cooldown():
    result, trace = run_case(buffered=True, flat_at=2)
    assert trace[2]["reason"] == "CONFIRMED_TREND_EXIT"
    assert Decimal(trace[2]["target_quantity"]) == 0
    assert not trace[2]["rebalance_permitted"]
    assert result.positions[-1].quantity == 0
    capped, capped_trace = run_case(buffered=True, caps=Decimal("0.1"))
    assert all(p.cash >= 0 for p in capped.equity_curve)
    assert max(Decimal(r["final_weight"]) for r in capped_trace) <= Decimal("0.1")
    zero, _ = run_case(buffered=True, caps=Decimal("0"))
    assert not zero.orders


def test_ensemble_uses_one_shared_budget_and_rejects_invalid_fraction():
    full, _ = run_case(buffered=True)
    third, trace = run_case(buffered=True, fractions=Decimal("1") / 3)
    assert third.fills[0].quantity.amount < full.fills[0].quantity.amount / 2
    assert abs(
        Decimal(trace[0]["risk_only_weight"]) - Decimal(trace[0]["raw_risk_weight"]) / 3
    ) < Decimal("1e-27")
    with pytest.raises(ValueError, match="budget"):
        run_case(buffered=True, fractions=Decimal("1.1"))


def test_legacy_policy_is_not_reinterpreted_for_new_periods():
    with pytest.raises(ValueError):
        TrendPolicy.model_validate({"fast_days": 20, "slow_days": 80})
    with pytest.raises(ValueError, match="pairs"):
        R4TrendPolicy(fast_days=10, slow_days=160)
    _, bars, _ = fixture()
    long = build_trend_features(bars, R4TrendPolicy(fast_days=40, slow_days=160))
    assert not np.any(long.valid)


def test_pending_target_and_future_availability_remain_explicit():
    _, bars, _ = fixture()
    time = bars[0].available_time
    base = Snapshot(
        time,
        time,
        Decimal("100"),
        Decimal("90"),
        Decimal("100"),
        Decimal("150"),
        True,
        pending_order_count=1,
        regular_review_due_override=True,
    )
    assert decide_buffered_target(base).action.value == "RECONCILE_PENDING"
    with pytest.raises(ValueError, match="不可用"):
        replace(base, available_time=bars[1].available_time)


def test_continuous_operation_has_no_synthetic_intermediate_exit():
    result, trace = run_case(buffered=True, terminal_exit=False)
    assert all(r["reason"] != "PREREGISTERED_FOLD_END_NEXT_OPEN_EXIT" for r in trace)
    assert result.positions[-1].quantity > 0
    assert result.forced_close_final_equity is not None
    assert result.mark_to_market_final_equity is not None
    assert result.forced_close_final_equity < result.mark_to_market_final_equity


def test_same_fill_shadow_uses_stressed_quote_fee_and_preserves_quantities():
    from scripts.summarize_alpha_r4 import shadow_cost

    result, _ = run_case()
    for fill in result.fills:
        assert abs(shadow_cost(fill, Decimal("1")) - fill.cost_breakdown.total) < Decimal("1e-20")
        assert shadow_cost(fill, Decimal("2")) > shadow_cost(fill, Decimal("1.5"))


def test_paired_null_is_recentered_before_comparing_observed_increment():
    from aegisquant.research.validation.paired_bootstrap import paired_block_bootstrap
    from scripts.summarize_alpha_r4 import automatic_block

    rng = np.random.default_rng(731)
    white = rng.normal(0, 0.001, 600)
    ar = np.zeros(600)
    for i in range(1, len(ar)):
        ar[i] = 0.95 * ar[i - 1] + white[i]
    assert automatic_block(ar) > automatic_block(white)
    assert automatic_block(np.zeros(600)) == 2
    common = paired_block_bootstrap(
        np.column_stack([white, white + 0.001]), repetitions=1000, block_bars=10
    )
    assert common.difference(1, 0)["one_sided_mean_p_value"] < 0.01
    identical = paired_block_bootstrap(
        np.column_stack([white, white]), repetitions=1000, block_bars=10
    )
    assert identical.difference(1, 0)["one_sided_mean_p_value"] == 1


def test_long_window_readiness_and_future_perturbation():
    from aegisquant.domain.identifiers import BacktestEventId

    _, original, _ = fixture()
    prototype = original[0]
    bars = tuple(
        prototype.model_copy(
            update={
                "event_id": BacktestEventId(f"r4-warmup-{i}"),
                "event_time": prototype.event_time + timedelta(hours=4 * i),
                "available_time": prototype.available_time + timedelta(hours=4 * i),
                "open": Decimal(str(100 + 10 * np.sin(i / 20))),
                "close": Decimal(str(100 + 10 * np.sin(i / 20))),
                "high": Decimal(str(101 + 10 * np.sin(i / 20))),
                "low": Decimal(str(99 + 10 * np.sin(i / 20))),
            }
        )
        for i in range(1400)
    )
    policy = R4TrendPolicy(fast_days=40, slow_days=160)
    full = build_trend_features(bars, policy)
    prefix = build_trend_features(bars[:1100], policy)
    np.testing.assert_array_equal(full.values[:1100], prefix.values)
    np.testing.assert_array_equal(full.valid[:1100], prefix.valid)
    assert np.flatnonzero(full.valid)[0] >= 960
    gap_bars = tuple(
        b
        if i < 1200
        else b.model_copy(
            update={
                "event_time": b.event_time + timedelta(hours=4),
                "available_time": b.available_time + timedelta(hours=4),
            }
        )
        for i, b in enumerate(bars)
    )
    with_gap = build_trend_features(gap_bars, policy)
    assert not np.any(with_gap.valid[1200:])
