from __future__ import annotations

import pytest

from aegisquant.research.models.deep import DeepModelKind, DeepModelSpec, fit_predict_deep
from aegisquant.research.models.tree import TreeModelKind, TreeModelSpec, fit_predict_tree
from tests.p08_helpers import model_dataset


@pytest.mark.parametrize("kind", tuple(TreeModelKind))
def test_tree_models_share_deterministic_probability_contract(kind: TreeModelKind) -> None:
    train = model_dataset(start=0, count=24)
    test = model_dataset(start=25, count=5)
    spec = TreeModelSpec(model_id=f"tree-{kind.value}", kind=kind, seed=7, estimators=12)
    first = fit_predict_tree(spec=spec, train=train, test=test)
    second = fit_predict_tree(spec=spec, train=train, test=test)
    assert first == second
    assert first.sample_ids == test.sample_ids
    assert all(
        lower <= median <= upper
        for lower, median, upper in zip(first.q05, first.q50, first.q95, strict=True)
    )


@pytest.mark.parametrize("kind", tuple(DeepModelKind))
def test_two_deep_time_series_candidates_are_bounded_and_deterministic(
    kind: DeepModelKind,
) -> None:
    train = model_dataset(start=0, count=24)
    test = model_dataset(start=25, count=5)
    spec = DeepModelSpec(
        model_id=f"deep-{kind.value}",
        kind=kind,
        seed=7,
        context_length=6,
        hidden_size=8,
        attention_heads=2,
        epochs=3,
    )
    first = fit_predict_deep(spec=spec, train=train, test=test)
    second = fit_predict_deep(spec=spec, train=train, test=test)
    assert first == second
    assert first.sample_ids == test.sample_ids
