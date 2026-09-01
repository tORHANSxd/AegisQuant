from __future__ import annotations

from decimal import Decimal

from aegisquant.research.models.monitoring import (
    DriftAction,
    DriftPolicy,
    MonitoringWindow,
    assess_drift,
)


def _window(offset: float) -> MonitoringWindow:
    return MonitoringWindow(
        feature_names=("price", "event"),
        features=tuple((float(index) + offset, float(index % 2)) for index in range(6)),
        predictions=tuple(float(index) / 10 + offset for index in range(6)),
        residuals=tuple(float(index) / 100 + offset for index in range(6)),
        calibration_errors=tuple(float(index) / 100 for index in range(6)),
        inference_latency_ms=(1.0,) * 6,
    )


def test_drift_monitor_degrades_and_abstains_on_ood() -> None:
    policy = DriftPolicy(
        warning_score=Decimal("1"),
        critical_score=Decimal("2"),
        ood_abstain_score=Decimal("3"),
    )
    stable = assess_drift(reference=_window(0), current=_window(0), policy=policy)
    shifted = assess_drift(reference=_window(0), current=_window(100), policy=policy)
    assert stable.action is DriftAction.NONE
    assert shifted.action is DriftAction.ABSTAIN
    assert shifted.reason_codes == ("AQ-MODEL-OOD",)
