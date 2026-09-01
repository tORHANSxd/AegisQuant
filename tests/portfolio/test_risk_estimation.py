"""Covariance shrinkage, factor, and regime-risk tests."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.portfolio.models import CovarianceEstimate, RiskRegime
from tests.p11_helpers import AS_OF, covariance


def test_covariance_combines_shrinkage_factor_and_regime_risk() -> None:
    estimate = covariance()
    assert estimate.regime is RiskRegime.STRESSED
    assert estimate.matrix == (
        (Decimal("0.10"), Decimal("0.0300")),
        (Decimal("0.0300"), Decimal("0.1850")),
    )
    assert len(estimate.estimate_sha256) == 64


def test_covariance_rejects_asymmetric_or_future_availability() -> None:
    baseline = covariance()
    asymmetric = baseline.model_dump(mode="json")
    asymmetric["matrix"] = (
        ("0.1", "0.2"),
        ("0.1", "0.2"),
    )
    with pytest.raises(ValueError, match="symmetric"):
        CovarianceEstimate.model_validate_json(json.dumps(asymmetric))
    future = baseline.model_dump(mode="json")
    future["observed_at"] = AS_OF.isoformat()
    future["available_at"] = (AS_OF - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="availability"):
        CovarianceEstimate.model_validate_json(json.dumps(future))
