from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.research.models import (
    BaselineDataset,
    BaselineModelKind,
    BaselineModelSpec,
    ResearchModality,
    compare_modalities,
    evaluate_predictions,
    fit_predict_baseline,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def dataset(
    *,
    start: int,
    count: int,
    names: tuple[str, ...] = ("market_1", "market_2", "event_1", "event_2"),
) -> BaselineDataset:
    features = tuple(
        tuple(float((start + index + 1) * (column + 1)) / 10 for column in range(len(names)))
        for index in range(count)
    )
    targets = tuple((-1.0, 0.0, 1.0)[(start + index) % 3] for index in range(count))
    return BaselineDataset(
        sample_ids=tuple(f"sample-{start + index:02d}" for index in range(count)),
        timestamps=tuple(NOW + timedelta(hours=start + index) for index in range(count)),
        feature_names=names,
        features=features,
        targets=targets,
    )


@pytest.mark.parametrize(
    "kind",
    (
        BaselineModelKind.LINEAR,
        BaselineModelKind.LOGISTIC,
        BaselineModelKind.ELASTIC_NET,
        BaselineModelKind.SIMPLE_STATE,
    ),
)
def test_classical_baselines_are_deterministic_and_finite(kind: BaselineModelKind) -> None:
    train = dataset(start=0, count=9)
    test = dataset(start=10, count=4)
    spec = BaselineModelSpec(model_id=f"model-{kind.value}", kind=kind, seed=7)
    first = fit_predict_baseline(spec=spec, train=train, test=test)
    second = fit_predict_baseline(spec=spec, train=train, test=test)
    assert first == second
    assert first.sample_ids == test.sample_ids
    assert all(value.is_finite() for value in first.predictions)
    if kind is BaselineModelKind.LOGISTIC:
        assert first.positive_probabilities is not None


def test_har_rv_contract_and_temporal_boundary() -> None:
    names = ("rv_daily", "rv_weekly", "rv_monthly")
    train = dataset(start=0, count=9, names=names)
    test = dataset(start=10, count=4, names=names)
    prediction = fit_predict_baseline(
        spec=BaselineModelSpec(model_id="har-rv", kind=BaselineModelKind.HAR_RV),
        train=train,
        test=test,
    )
    assert all(value >= 0 for value in prediction.predictions)

    overlapping = dataset(start=8, count=4, names=names)
    with pytest.raises(ValueError, match="training must precede"):
        fit_predict_baseline(
            spec=BaselineModelSpec(model_id="har-rv", kind=BaselineModelKind.HAR_RV),
            train=train,
            test=overlapping,
        )


def test_market_event_fused_comparison_uses_same_budget_and_explicit_costs() -> None:
    train = dataset(start=0, count=9)
    test = dataset(start=10, count=4)
    result = compare_modalities(
        spec=BaselineModelSpec(model_id="linear-fair", kind=BaselineModelKind.LINEAR, seed=11),
        train=train,
        test=test,
        market_columns=(0, 1),
        event_columns=(2, 3),
        realized_returns=(Decimal("0.01"), Decimal("-0.02"), Decimal("0.03"), Decimal("-0.01")),
        cost_rates=(Decimal("0.001"),) * 4,
    )
    assert {item.modality for item in result.evaluations} == set(ResearchModality)
    assert len(result.budget_sha256) == 64
    assert all(
        item.net_return == item.gross_return - item.transaction_cost for item in result.evaluations
    )

    prediction = fit_predict_baseline(
        spec=BaselineModelSpec(model_id="logistic", kind=BaselineModelKind.LOGISTIC),
        train=train,
        test=test,
    )
    evaluation = evaluate_predictions(
        predictions=prediction,
        modality=ResearchModality.FUSED,
        realized_returns=(Decimal("0.01"), Decimal("-0.02"), Decimal("0.03"), Decimal("-0.01")),
        cost_rates=(Decimal("0.001"),) * 4,
    )
    assert evaluation.brier_score is not None
