"""Adaptive and distribution-aware conformal monitoring tests."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.research.forecasting import (
    AdaptiveConformalPolicy,
    CalibrationDriftAction,
    CalibrationMethod,
    IntervalCoverageObservation,
    IntervalCoverageWindow,
    adaptive_conformal_interval,
)
from tests.v5_p09.helpers import (
    NOW,
    conformal_policy,
    conformal_report,
    coverage_observations,
    coverage_window,
)


def test_distribution_aware_coverage_is_monitored_per_cell() -> None:
    report = conformal_report()
    assert report.policy.method is CalibrationMethod.DISTRIBUTION_AWARE_CONFORMAL
    assert report.observed_coverage == Decimal("0.8")
    assert report.coverage_shortfall == 0
    assert report.action is CalibrationDriftAction.NONE
    assert report.distribution_scale_normalized is True
    assert report.recommended_residual_quantile == Decimal("0.15")
    assert report.recommended_scale_multiplier == Decimal("1.5")
    assert report.exchangeability_assumed is False
    assert report.real_world_coverage_claimed is False

    interval = adaptive_conformal_interval(
        prediction=Decimal("0.01"),
        report=report,
        base_half_width=Decimal("0.10"),
    )
    assert interval.lower <= interval.median <= interval.upper
    assert interval.asset_id == report.window.asset_id
    assert interval.horizon is report.window.horizon
    assert interval.regime is report.window.regime


def test_distribution_aware_interval_scales_with_forecast_uncertainty() -> None:
    report = conformal_report()
    narrow = adaptive_conformal_interval(
        prediction=Decimal("0"),
        report=report,
        base_half_width=Decimal("0.05"),
    )
    wide = adaptive_conformal_interval(
        prediction=Decimal("0"),
        report=report,
        base_half_width=Decimal("0.20"),
    )
    assert narrow.upper - narrow.median == Decimal("0.075")
    assert wide.upper - wide.median == Decimal("0.30")
    with pytest.raises(ValueError, match="BASE-SCALE-REQUIRED"):
        adaptive_conformal_interval(prediction=Decimal("0"), report=report)


def test_critical_undercoverage_forces_abstention() -> None:
    poor = coverage_window(observations=coverage_observations(realized=(Decimal("1"),) * 5))
    report = conformal_report(window=poor)
    assert report.observed_coverage == 0
    assert report.action is CalibrationDriftAction.ABSTAIN
    assert "INTERVAL_UNDERCOVERAGE_CRITICAL" in report.reason_codes
    with pytest.raises(ValueError, match="CALIBRATION-ABSTAIN"):
        adaptive_conformal_interval(prediction=Decimal("0"), report=report)


def test_insufficient_or_stale_windows_fail_closed() -> None:
    short = coverage_window(observations=coverage_observations()[:2])
    insufficient = conformal_report(window=short)
    assert insufficient.action is CalibrationDriftAction.ABSTAIN
    assert "INSUFFICIENT_COVERAGE_SAMPLES" in insufficient.reason_codes

    stale = coverage_window(decision_time=NOW + timedelta(minutes=10))
    stale_report = conformal_report(
        window=stale,
        policy=conformal_policy(maximum_window_age_seconds=Decimal("120")),
    )
    assert stale_report.action is CalibrationDriftAction.ABSTAIN
    assert "STALE_COVERAGE_WINDOW" in stale_report.reason_codes


def test_static_conformal_is_forbidden_for_the_p09_policy() -> None:
    with pytest.raises(ValueError, match="STATIC-CONFORMAL-FORBIDDEN"):
        AdaptiveConformalPolicy(
            method=CalibrationMethod.PLATT_LOGISTIC,
            target_coverage=Decimal("0.8"),
            warning_shortfall=Decimal("0.1"),
            critical_shortfall=Decimal("0.2"),
            minimum_sample_count=5,
            maximum_window_age_seconds=Decimal("120"),
            maximum_adjustment_step=Decimal("0.05"),
        )


@pytest.mark.parametrize("field", ["maximum_window_age_seconds", "maximum_adjustment_step"])
def test_adaptive_policy_rejects_zero_operational_limits(field: str) -> None:
    payload = conformal_policy().model_dump(mode="python")
    payload[field] = Decimal("0")
    with pytest.raises(ValueError):
        AdaptiveConformalPolicy.model_validate(payload)


def test_distribution_aware_calibration_requires_positive_forecast_scale() -> None:
    observations = list(coverage_observations())
    observations[0] = observations[0].model_copy(
        update={
            "predicted_lower": Decimal("0"),
            "predicted_median": Decimal("0"),
            "predicted_upper": Decimal("0"),
        }
    )
    with pytest.raises(ValueError, match="DISTRIBUTION-SCALE-NONPOSITIVE"):
        conformal_report(window=coverage_window(observations=tuple(observations)))


def test_critical_overcoverage_degrades_without_granting_false_precision() -> None:
    always_covered = coverage_window(
        observations=coverage_observations(realized=(Decimal("0"),) * 5)
    )
    report = conformal_report(window=always_covered)
    assert report.observed_coverage == Decimal("1")
    assert report.action is CalibrationDriftAction.DEGRADE
    assert "INTERVAL_OVERCOVERAGE_CRITICAL" in report.reason_codes


def test_future_outcome_and_interval_order_are_rejected() -> None:
    with pytest.raises(ValueError, match="INTERVAL-ORDER"):
        IntervalCoverageObservation(
            sample_id="bad-interval",
            predicted_lower=Decimal("1"),
            predicted_median=Decimal("0"),
            predicted_upper=Decimal("2"),
            realized_value=Decimal("0"),
            predicted_at=NOW - timedelta(minutes=2),
            outcome_available_at=NOW - timedelta(minutes=1),
        )
    outside = list(coverage_observations())
    outside[0] = outside[0].model_copy(update={"outcome_available_at": NOW + timedelta(seconds=1)})
    with pytest.raises(ValueError, match="OUTSIDE-WINDOW"):
        coverage_window(observations=tuple(outside))


def test_coverage_metrics_are_recomputed_instead_of_trusting_callers() -> None:
    report = conformal_report()
    payload = report.model_dump(mode="json")
    payload["observed_coverage"] = "1"
    with pytest.raises(ValueError, match="RECOMPUTATION-MISMATCH"):
        type(report).model_validate_json(json.dumps(payload))

    window_payload = report.window.model_dump(mode="json")
    window_payload["decision_time"] = (NOW - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="WINDOW-TIME-ORDER"):
        IntervalCoverageWindow.model_validate_json(json.dumps(window_payload))
