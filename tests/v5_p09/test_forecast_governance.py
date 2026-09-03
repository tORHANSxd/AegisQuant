"""End-to-end deterministic P09 forecast-governance tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from aegisquant.research.forecasting import MarketRegime, SkepticSeverity
from tests.v5_p09.helpers import (
    conformal_report,
    coverage_observations,
    coverage_window,
    disagreement_report,
    governance_report,
    route_decision,
    routing_snapshot,
    signal_snapshot,
)


def test_healthy_development_governance_never_grants_order_capability() -> None:
    report = governance_report()
    assert report.should_abstain is False
    assert report.reason_codes == ()
    assert report.statistically_learned_ensemble_controls_weights is True
    assert report.alpha_promotion_eligible is False
    assert report.final_holdout_opened is False
    assert report.order_submission_enabled is False
    assert report.live_trading_locked is True


def test_meta_reasoner_can_only_tighten_by_recommending_abstention() -> None:
    report = governance_report(recommend_abstain=True)
    assert report.should_abstain is True
    assert "META_REASONER_RECOMMENDS_ABSTAIN" in report.reason_codes
    assert report.order_submission_enabled is False


def test_disagreement_ood_and_calibration_drift_all_propagate_to_abstain() -> None:
    disagreement = disagreement_report(
        snapshot=signal_snapshot(returns=(Decimal("-0.03"), Decimal("0.04")))
    )
    disagreement_result = governance_report(disagreement=disagreement)
    assert disagreement_result.should_abstain is True
    assert "MODEL_DIRECTION_CONFLICT" in disagreement_result.reason_codes

    ood_route = route_decision(snapshot=routing_snapshot(ood_score=Decimal("5")))
    ood_result = governance_report(route=ood_route)
    assert ood_result.should_abstain is True
    assert "OUT_OF_DISTRIBUTION" in ood_result.reason_codes

    poor_coverage = conformal_report(
        window=coverage_window(observations=coverage_observations(realized=(Decimal("1"),) * 5))
    )
    calibration_result = governance_report(calibration=poor_coverage)
    assert calibration_result.should_abstain is True
    assert "CALIBRATION_ABSTAIN" in calibration_result.reason_codes


def test_skeptic_blocker_is_independent_and_fail_closed() -> None:
    report = governance_report(
        skeptic_blocks=True,
        skeptic_severity=SkepticSeverity.CRITICAL,
    )
    assert report.should_abstain is True
    assert any(reason.startswith("SKEPTIC_") for reason in report.reason_codes)


def test_cross_cell_governance_splice_is_rejected() -> None:
    disagreement = disagreement_report()
    route = route_decision()
    calibration = conformal_report(window=coverage_window(regime=MarketRegime.NEWS_SHOCK))
    with pytest.raises(ValueError, match="CELL-SPLICE"):
        governance_report(
            disagreement=disagreement,
            route=route,
            calibration=calibration,
        )
