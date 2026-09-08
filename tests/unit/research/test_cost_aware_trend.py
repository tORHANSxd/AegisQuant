from datetime import timedelta
from decimal import Decimal

import numpy as np
import pytest

from aegisquant.features.registry import FeatureRegistry
from aegisquant.research.strategies.cost_aware_trend import (
    build_trend_features,
    fit_training_scaler,
    trend_targets,
)
from tests.p06.helpers import NOW, bars


def test_hysteresis_requires_confirmation_and_only_emits_long_flat() -> None:
    scores = np.asarray([0.3, 0.4, 0, -0.1, -0.3, 0.3, 0.1, 0.4, 0.5], dtype=np.float64)
    output = trend_targets(scores, np.ones(len(scores), dtype=np.bool_))
    assert output.tolist() == [0, 1, 1, 1, 0, 0, 0, 0, 1]
    assert set(output).issubset({0, 1})


def test_features_are_causal_and_scaler_uses_only_training_window() -> None:
    source = bars(310, volume="100")
    values = tuple(
        b.model_copy(
            update={
                "event_time": NOW + timedelta(hours=4 * i),
                "available_time": NOW + timedelta(hours=4 * (i + 1)) - timedelta(milliseconds=1),
            }
        )
        for i, b in enumerate(source)
    )
    original = build_trend_features(values)
    changed = (
        *values[:-1],
        values[-1].model_copy(update={"close": Decimal("500"), "high": Decimal("501")}),
    )
    future_changed = build_trend_features(changed)
    np.testing.assert_equal(original.values[:-1], future_changed.values[:-1])
    gapped = (
        *values[:290],
        *(
            b.model_copy(
                update={
                    "event_time": b.event_time + timedelta(hours=4),
                    "available_time": b.available_time + timedelta(hours=4),
                }
            )
            for b in values[290:]
        ),
    )
    after_gap = build_trend_features(gapped)
    assert after_gap.valid[280]
    assert not np.any(after_gap.valid[290:])
    train = np.arange(240, 280, dtype=np.int64)
    scaler = fit_training_scaler(original, train, validation_start=values[281].available_time)
    other = fit_training_scaler(future_changed, train, validation_start=values[281].available_time)
    assert scaler == other
    with pytest.raises(ValueError, match="precede validation"):
        fit_training_scaler(original, train, validation_start=values[260].available_time)


def test_gap_requires_full_warmup_and_unclosed_bars_are_rejected() -> None:
    with pytest.raises(ValueError, match="completed bars"):
        build_trend_features(bars(4))


def test_cat_feature_schema_is_registered_with_training_only_normalization() -> None:
    registry = FeatureRegistry()
    registry.register_cost_aware_trend()
    assert len(registry.definitions()) == 17
    assert all(d.normalization.startswith("training_only") for d in registry.definitions())
