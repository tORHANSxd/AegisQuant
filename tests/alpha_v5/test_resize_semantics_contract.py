"""Only deterministic synthetic quantities and event tables; no market loader or replay."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aegisquant.data.hashing import sha256_file
from aegisquant.portfolio.optimizer import target_quantity_adjustment
from aegisquant.research.strategies.buffered_target import (
    Action,
    BufferPolicy,
    Snapshot,
    TargetSmoother,
    decide_buffered_target,
    rebalance_risk_benefit,
)
from aegisquant.research.validation.evidence_contract import (
    ReviewClock,
    resize_cost_allowed,
    resolve_required_evidence,
    review_clock_transition,
)

D = Decimal
T = datetime(2020, 1, 1, tzinfo=UTC)


def test_invoked_pure_functions_match_frozen_sources(project_root: Path) -> None:
    for name in ("research/strategies/buffered_target.py", "portfolio/optimizer.py"):
        relative = f"src/aegisquant/{name}"
        frozen = (
            project_root / "artifacts/alpha_v5/20260908_research_churn_v3/implementation" / relative
        )
        assert sha256_file(project_root / relative) == sha256_file(frozen)


def test_variance_utility_dimensions_and_lambda_direction() -> None:
    benefit = rebalance_risk_benefit(D(".4"), D(".33"), D(".3"), D(".6"), timedelta(days=2))
    cost = D(".07") * D(".0016")  # Synthetic 16bps, not an estimate of historical fees.
    assert abs(benefit - D(".00000896919918")) < D("1e-14")
    assert cost == D(".000112")
    assert abs(cost / benefit - D("12.48717949")) < D("1e-8")
    assert not resize_cost_allowed(benefit, cost, D(1))
    assert resize_cost_allowed(benefit, cost, D(13))
    assert resize_cost_allowed(benefit, benefit, D(1))
    assert not resize_cost_allowed(D(0), D(0), D(1))


def test_distance_monotonicity_and_raw_smoothed_conflict() -> None:
    def benefit(proposed: str) -> Decimal:
        return rebalance_risk_benefit(D(".4"), D(proposed), D(".3"), D(".6"), timedelta(days=2))

    assert benefit(".30") > benefit(".33") > benefit(".37") > benefit(".39") > 0
    assert benefit(".40") == benefit(".50") == benefit(".2") == 0
    # .50 approaches a smoothed .60 target while moving away from raw .30.
    assert abs(D(".50") - D(".60")) < abs(D(".40") - D(".60"))
    assert benefit(".50") == 0
    assert rebalance_risk_benefit(D(1), D(0), D(0), D(0), timedelta(days=2)) == 0


@pytest.mark.parametrize("bad", [D("-0.1"), D("1.1"), D("NaN"), D("Infinity"), D("-Infinity"), 0.4])
def test_utility_rejects_invalid_weights(bad: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        rebalance_risk_benefit(bad, D(".33"), D(".3"), D(".6"), timedelta(days=2))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "vol,horizon",
    [
        (D(-1), timedelta(days=2)),
        (D("NaN"), timedelta(days=2)),
        (D("Infinity"), timedelta(days=2)),
        (D(1), timedelta(0)),
    ],
)
def test_utility_volatility_and_horizon_boundaries(vol: Decimal, horizon: timedelta) -> None:
    with pytest.raises(ValueError):
        rebalance_risk_benefit(D(".4"), D(".33"), D(".3"), vol, horizon)


def test_review_consumes_clock_before_veto_and_pending_does_not() -> None:
    state, due = review_clock_transition(ReviewClock(), "DECISION", T)
    assert due and state.last_review == T
    # Cost veto does not undo this already performed review.
    state, _ = review_clock_transition(state, "REJECT", T)
    state, due = review_clock_transition(state, "DECISION", T + timedelta(hours=47))
    assert not due and state.last_review == T
    state, due = review_clock_transition(state, "DECISION", T + timedelta(hours=48), pending=True)
    assert due and state.last_review == T
    state, due = review_clock_transition(state, "DECISION", T + timedelta(hours=48))
    assert due and state.last_review == T + timedelta(hours=48)
    _, due = review_clock_transition(state, "DECISION", T + timedelta(hours=48))
    assert not due


def test_submission_fill_refusal_cancel_and_same_timestamp_order() -> None:
    state, _ = review_clock_transition(ReviewClock(), "SUBMIT", T)
    for event in ("PARTIAL_FILL", "CANCEL_REQUEST", "CANCEL_ACK", "REJECT", "FILL"):
        state, _ = review_clock_transition(state, event, T + timedelta(hours=1))
        assert state.last_review == state.last_submitted == T
    assert state.last_fill == T + timedelta(hours=1)
    state, _ = review_clock_transition(state, "SUBMIT", T + timedelta(hours=1))
    assert state.last_review == state.last_submitted == T + timedelta(hours=1)
    with pytest.raises(ValueError, match="BACKWARDS"):
        review_clock_transition(state, "FILL", T)
    with pytest.raises(ValueError, match="NON-UTC"):
        review_clock_transition(ReviewClock(), "DECISION", T.replace(tzinfo=None))


@pytest.mark.parametrize("overrides", [{"good": False}, {"trend": False}, {"held": D(0)}])
def test_ineligible_review_does_not_advance(overrides: dict[str, object]) -> None:
    state, due = review_clock_transition(ReviewClock(), "DECISION", T, **overrides)  # type: ignore[arg-type]
    assert due and state.last_review is None


def test_gap_only_resets_smoother_not_all_indicator_readiness() -> None:
    smoother = TargetSmoother()
    smoother.update(T, D(".8"), timedelta(days=5))
    reset = TargetSmoother()
    assert reset.update(T + timedelta(days=10), D(".2"), timedelta(days=5)) == D(".2")
    state, _ = review_clock_transition(ReviewClock(last_review=T), "GAP", T + timedelta(days=10))
    assert state.last_review == T
    assert resolve_required_evidence(collected=True, received=True) == "NOT_VERIFIED"
    assert resolve_required_evidence(collected=False, received=False) == "NOT_COLLECTED"


def test_hard_exit_caps_and_pending_reconciliation_have_priority() -> None:
    snapshot = Snapshot(
        T, T, D(".4"), D(".3"), D(".3"), D(1), True, last_regular_review=T, equity_quantity=D(1)
    )
    policy = BufferPolicy(review_interval=timedelta(hours=48))
    assert decide_buffered_target(snapshot, policy).reason == "REGULAR_REVIEW_NOT_DUE"
    hard = decide_buffered_target(replace(snapshot, hard_exit=True), policy)
    assert hard.target_quantity == 0 and hard.action == Action.REQUEST_TARGET
    cap = decide_buffered_target(replace(snapshot, hard_max_quantity=D(".2")), policy)
    assert cap.reason == "HARD_CAP_REDUCTION" and cap.target_quantity == D(".2")
    pending = decide_buffered_target(
        replace(snapshot, hard_exit=True, pending_order_count=1), policy
    )
    assert pending.action == Action.RECONCILE_PENDING and pending.target_quantity is None
    assert (
        decide_buffered_target(
            replace(snapshot, hard_exit=True, market_executable=False), policy
        ).action
        == Action.BLOCKED
    )


def test_second_rounding_minimum_notional_pending_and_tiny_nav() -> None:
    arguments = {
        "current_quantity": D(".4"),
        "signed_pending_quantity": D(0),
        "price": D(1000),
        "quantity_step": D(".01"),
        "minimum_notional": D(5),
        "minimum_economic_notional": D(50),
    }
    first = target_quantity_adjustment(target_quantity=D(".333"), **arguments)
    assert first.signed_order_quantity == D("-.06")
    second = target_quantity_adjustment(
        target_quantity=D(".4") + first.signed_order_quantity, **arguments
    )
    assert second.signed_order_quantity == first.signed_order_quantity
    assert (
        target_quantity_adjustment(target_quantity=D(".39"), **arguments).signed_order_quantity == 0
    )
    conflict = target_quantity_adjustment(
        target_quantity=D(".3"), **{**arguments, "signed_pending_quantity": D(".02")}
    )
    assert conflict.cancel_pending_first and conflict.signed_order_quantity == 0
    # Tiny synthetic NAV still cannot evade the minimum economic notional.
    tiny = target_quantity_adjustment(
        target_quantity=D(".0000001"), **{**arguments, "current_quantity": D(0)}
    )
    assert tiny.signed_order_quantity == 0
