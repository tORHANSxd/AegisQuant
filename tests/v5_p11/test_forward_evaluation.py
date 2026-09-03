"""Forward duration, calibration, paired-mode, and promotion-gate tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.forward import (
    ForwardMode,
    ForwardNextAction,
    ForwardProofDecision,
    ForwardProofStatus,
    ForwardRunKind,
    evaluate_forward_mode,
    evaluate_paper_shadow_forward,
)
from tests.v5_p11.helpers import make_policy, make_session


def test_development_fixture_never_becomes_forward_proof() -> None:
    report = evaluate_forward_mode(
        session=make_session(mode=ForwardMode.PAPER),
        policy=make_policy(),
    )
    assert report.status is ForwardProofStatus.EXTEND_PAPER
    assert "DEVELOPMENT_FIXTURE_NOT_FORWARD" in report.reason_codes
    assert "MINIMUM_30_CALENDAR_DAYS_NOT_MET" in report.reason_codes
    assert report.alpha_promotion_eligible is False


def test_real_wall_clock_run_shorter_than_30_days_must_extend() -> None:
    report = evaluate_forward_mode(
        session=make_session(
            mode=ForwardMode.PAPER,
            run_kind=ForwardRunKind.WALL_CLOCK_FORWARD,
            days=29,
        ),
        policy=make_policy(),
    )
    assert report.status is ForwardProofStatus.EXTEND_PAPER
    assert report.elapsed_calendar_days == 29


def test_30_day_wall_clock_run_can_pass_contract_gate() -> None:
    report = evaluate_forward_mode(
        session=make_session(
            mode=ForwardMode.PAPER,
            run_kind=ForwardRunKind.WALL_CLOCK_FORWARD,
            days=30,
        ),
        policy=make_policy(),
    )
    assert report.status is ForwardProofStatus.PASS
    assert report.reason_codes == ("FORWARD_MODE_PROOF_PASS",)
    assert report.truth_calibration_pass is True
    assert report.forecast_calibration_pass is True
    assert report.cost_calibration_pass is True
    assert report.event_increment_attribution_pass is True


def test_insufficient_independent_events_extends_instead_of_lowering_threshold() -> None:
    report = evaluate_forward_mode(
        session=make_session(
            mode=ForwardMode.PAPER,
            run_kind=ForwardRunKind.WALL_CLOCK_FORWARD,
            days=30,
            sample_count=3,
        ),
        policy=make_policy(minimum_independent_event_count=4),
    )
    assert report.status is ForwardProofStatus.EXTEND_PAPER
    assert "INDEPENDENT_EVENT_SAMPLE_INSUFFICIENT" in report.reason_codes


def test_policy_cannot_lower_master_plan_duration() -> None:
    with pytest.raises(ValidationError):
        make_policy(minimum_calendar_days=29)


def test_heartbeat_gap_fails_closed() -> None:
    report = evaluate_forward_mode(
        session=make_session(
            mode=ForwardMode.PAPER,
            heartbeat_step=timedelta(hours=2),
        ),
        policy=make_policy(),
    )
    assert report.status is ForwardProofStatus.FAIL_CLOSED
    assert "CONTINUOUS_FORWARD_GAP_EXCEEDED" in report.reason_codes


def test_calibration_failure_fails_closed() -> None:
    report = evaluate_forward_mode(
        session=make_session(mode=ForwardMode.PAPER, poor_calibration=True),
        policy=make_policy(),
    )
    assert report.status is ForwardProofStatus.FAIL_CLOSED
    assert "TRUTH_CALIBRATION_FAILED" in report.reason_codes
    assert "FORECAST_CALIBRATION_FAILED" in report.reason_codes
    assert "EVENT_INCREMENT_ATTRIBUTION_FAILED" in report.reason_codes
    assert report.truth_calibration.mean_predicted_probability == Decimal("0.5")
    assert report.truth_calibration.realized_positive_rate == Decimal("0.5")
    assert report.truth_calibration.expected_calibration_error == Decimal("0.9")


def test_data_loss_incident_fails_closed() -> None:
    report = evaluate_forward_mode(
        session=make_session(mode=ForwardMode.PAPER, data_loss_detected=True),
        policy=make_policy(),
    )
    assert report.status is ForwardProofStatus.FAIL_CLOSED
    assert "INCIDENT_LOG_INCOMPLETE_OR_UNRESOLVED" in report.reason_codes


def test_future_correction_attempt_fails_closed() -> None:
    report = evaluate_forward_mode(
        session=make_session(mode=ForwardMode.PAPER, future_correction_attempted=True),
        policy=make_policy(),
    )
    assert report.status is ForwardProofStatus.FAIL_CLOSED
    assert "FUTURE_CORRECTION_DETECTED" in report.reason_codes


def test_paired_development_runs_remain_no_promotion() -> None:
    policy = make_policy()
    proof = evaluate_paper_shadow_forward(
        paper=evaluate_forward_mode(session=make_session(mode=ForwardMode.PAPER), policy=policy),
        shadow=evaluate_forward_mode(session=make_session(mode=ForwardMode.SHADOW), policy=policy),
    )
    assert proof.decision is ForwardProofDecision.NO_PROMOTION
    assert proof.next_action is ForwardNextAction.EXTEND_PAPER
    assert proof.paper_pass is False
    assert proof.shadow_pass is False
    assert proof.canary_review_ready is False
    assert proof.alpha_promotion_eligible is False
    assert proof.live_trading_locked is True


def test_paired_30_day_forward_only_allows_testnet_readiness() -> None:
    policy = make_policy()
    proof = evaluate_paper_shadow_forward(
        paper=evaluate_forward_mode(
            session=make_session(
                mode=ForwardMode.PAPER,
                run_kind=ForwardRunKind.WALL_CLOCK_FORWARD,
                days=30,
            ),
            policy=policy,
        ),
        shadow=evaluate_forward_mode(
            session=make_session(
                mode=ForwardMode.SHADOW,
                run_kind=ForwardRunKind.WALL_CLOCK_FORWARD,
                days=30,
            ),
            policy=policy,
        ),
    )
    assert proof.decision is ForwardProofDecision.P11_FORWARD_PASS
    assert proof.next_action is ForwardNextAction.PROCEED_TO_TESTNET_READINESS
    assert proof.paper_pass is True
    assert proof.shadow_pass is True
    assert proof.canary_review_ready is False
    assert proof.alpha_promotion_eligible is False


def test_paper_and_shadow_predictions_cannot_be_spliced() -> None:
    policy = make_policy()
    paper = evaluate_forward_mode(session=make_session(mode=ForwardMode.PAPER), policy=policy)
    shadow = evaluate_forward_mode(
        session=make_session(mode=ForwardMode.SHADOW, sample_count=3),
        policy=policy,
    )
    with pytest.raises(ValueError, match="PAPER-SHADOW-PREDICTION-SPLICE"):
        evaluate_paper_shadow_forward(paper=paper, shadow=shadow)
