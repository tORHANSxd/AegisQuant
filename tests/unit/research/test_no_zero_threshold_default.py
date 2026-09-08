from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.research.models.baselines import (
    BaselineModelKind,
    BaselinePrediction,
    CalibratedThreshold,
    ResearchModality,
    evaluate_predictions,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def prediction(values: tuple[str, ...]) -> BaselinePrediction:
    return BaselinePrediction(
        model_id="diagnostic",
        model_kind=BaselineModelKind.LINEAR,
        model_spec_sha256="a" * 64,
        sample_ids=tuple(str(i) for i in range(len(values))),
        predictions=tuple(map(Decimal, values)),
    )


def calibration() -> CalibratedThreshold:
    return CalibratedThreshold(
        edge_threshold=Decimal("0.001"),
        class_flat_band=Decimal("0.001"),
        calibrated_at=NOW - timedelta(days=1),
        evidence_sha256="b" * 64,
    )


def test_without_calibrated_threshold_returns_no_trade() -> None:
    result = evaluate_predictions(
        predictions=prediction(("0.000001", "-0.000001")),
        modality=ResearchModality.MARKET_ONLY,
        realized_returns=(Decimal("0.1"), Decimal("-0.1")),
        cost_rates=(Decimal("0.001"),) * 2,
    )
    assert result.decision == "NO_TRADE"
    assert result.turnover == result.net_return == 0
    assert result.account.account_metrics.trade_statistics.closed_trade_count == 0


def test_zero_threshold_and_future_calibration_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CalibratedThreshold(
            edge_threshold=Decimal("0"),
            class_flat_band=Decimal("0"),
            calibrated_at=NOW,
            evidence_sha256="b" * 64,
        )
    with pytest.raises(ValueError, match="must precede"):
        evaluate_predictions(
            predictions=prediction(("0.1",)),
            modality=ResearchModality.MARKET_ONLY,
            realized_returns=(Decimal("0.1"),),
            cost_rates=(Decimal("0.001"),),
            calibration=calibration(),
            evaluation_start=NOW - timedelta(days=2),
        )
