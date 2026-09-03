from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.intelligence import ForecastHorizon
from aegisquant.intelligence.world.fusion import (
    AblationPrediction,
    AblationView,
    ResultSign,
    build_feature_snapshot,
    fuse_event_market_impact,
    run_same_budget_ablation,
)
from tests.intelligence.world.helpers import NOW, fusion_features
from tests.p08_helpers import fitted_horizon_coefficients


def test_fusion_requires_point_in_time_price_book_oi_funding_basis_and_onchain() -> None:
    snapshot = build_feature_snapshot(
        asset_id="BTC", as_of_time=NOW, features=fusion_features("BTC")
    )
    assert len(snapshot.features) == 6
    with pytest.raises(ValidationError, match="requires price/book/OI"):
        build_feature_snapshot(asset_id="BTC", as_of_time=NOW, features=fusion_features("BTC")[:-1])
    future = fusion_features("BTC", available_at=NOW + timedelta(seconds=1))
    with pytest.raises(ValidationError, match="LOOKAHEAD"):
        build_feature_snapshot(asset_id="BTC", as_of_time=NOW, features=future)


def test_fused_forecast_is_multi_asset_multi_horizon_and_proposal_only() -> None:
    snapshots = tuple(
        build_feature_snapshot(asset_id=asset, as_of_time=NOW, features=fusion_features(asset))
        for asset in ("BTC", "ETH")
    )
    impacts = fuse_event_market_impact(
        horizon_coefficients=fitted_horizon_coefficients(),
        event_cluster_id="event-1",
        event_directional_score=Decimal("0.4"),
        event_confidence=Decimal("0.8"),
        manipulation_risk=Decimal("0.1"),
        snapshots=snapshots,
        evidence_ids=("evidence-1",),
        model_versions=("fusion-p10-v1",),
    )
    assert {item.asset_id for item in impacts} == {"BTC", "ETH"}
    assert {point.horizon for point in impacts[0].horizons} == {
        ForecastHorizon.FIVE_MINUTES,
        ForecastHorizon.THIRTY_MINUTES,
        ForecastHorizon.FOUR_HOURS,
        ForecastHorizon.ONE_DAY,
        ForecastHorizon.SEVEN_DAYS,
    }
    assert all(item.action == "RESEARCH_PROPOSAL_ONLY" for item in impacts)


def _ablation_predictions(*, mismatch_budget: bool = False) -> tuple[AblationPrediction, ...]:
    actual = {"sample-a": Decimal("0.10"), "sample-b": Decimal("-0.10")}
    predicted = {
        AblationView.MARKET_ONLY: (Decimal("0.08"), Decimal("-0.08")),
        AblationView.EVENT_ONLY: (Decimal("0.10"), Decimal("0.10")),
        AblationView.FUSED: (Decimal("0.09"), Decimal("-0.09")),
        AblationView.RISK_ONLY: (Decimal("0"), Decimal("0")),
    }
    manifest = canonical_sha256({"dataset": "p10-ablation-fixture"})
    items: list[AblationPrediction] = []
    for view, predictions in predicted.items():
        for index, sample_id in enumerate(actual):
            budget = 2 if mismatch_budget and view is AblationView.FUSED else 1
            items.append(
                AblationPrediction(
                    sample_id=sample_id,
                    view=view,
                    prediction_time=NOW,
                    feature_available_at=NOW,
                    outcome_available_at=NOW + timedelta(hours=1),
                    predicted_return=predictions[index],
                    actual_return=actual[sample_id],
                    compute_budget_units=budget,
                    dataset_manifest_hash=manifest,
                )
            )
    return tuple(items)


def test_same_budget_ablation_reports_positive_and_negative_results_without_selection() -> None:
    report = run_same_budget_ablation(_ablation_predictions())
    signs = {score.view: score.result_sign for score in report.scores}
    assert signs[AblationView.FUSED] is ResultSign.POSITIVE
    assert signs[AblationView.EVENT_ONLY] is ResultSign.NEGATIVE
    assert signs[AblationView.RISK_ONLY] is ResultSign.NEGATIVE
    assert report.selection_performed is False
    assert len(report.scores) == 4


def test_ablation_rejects_budget_mismatch_and_future_features() -> None:
    with pytest.raises(ValueError, match="identical total compute budget"):
        run_same_budget_ablation(_ablation_predictions(mismatch_budget=True))
    with pytest.raises(ValidationError, match="FUTURE-FEATURE"):
        AblationPrediction(
            sample_id="future",
            view=AblationView.MARKET_ONLY,
            prediction_time=NOW,
            feature_available_at=NOW + timedelta(seconds=1),
            outcome_available_at=NOW + timedelta(hours=1),
            predicted_return=Decimal("0"),
            actual_return=Decimal("0"),
            compute_budget_units=1,
            dataset_manifest_hash=canonical_sha256({"dataset": "fixture"}),
        )
