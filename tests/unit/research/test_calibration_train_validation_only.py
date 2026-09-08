from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from aegisquant.research.models.baselines import BaselineDataset
from aegisquant.research.models.economic_filter import EconomicModelFamily, fit_economic_filter
from aegisquant.research.models.economic_gate import CalibrationStatus

ORIGIN = datetime(2021, 1, 1, tzinfo=UTC)


def dataset(start: int, count: int) -> BaselineDataset:
    return BaselineDataset(
        sample_ids=tuple(f"sample-{i}" for i in range(start, start + count)),
        timestamps=tuple(ORIGIN + timedelta(hours=i * 4) for i in range(start, start + count)),
        feature_names=("causal_trend",),
        features=tuple((float(np.sin(i)),) for i in range(start, start + count)),
        targets=tuple(float(np.sin(i) * 0.01) for i in range(start, start + count)),
    )


@pytest.mark.parametrize("family", ("XGBOOST", "LIGHTGBM", "ELASTIC_NET"))
def test_test_labels_cannot_change_fitted_model_or_calibration(family: EconomicModelFamily) -> None:
    train, validation, test = dataset(0, 40), dataset(46, 40), dataset(94, 8)
    train_ends = tuple(t + timedelta(hours=24) for t in train.timestamps)
    validation_ends = tuple(t + timedelta(hours=24) for t in validation.timestamps)
    original = fit_economic_filter(
        family=family,
        train=train,
        validation=validation,
        test=test,
        validation_round_trip_costs=(Decimal("0.002"),) * 40,
        train_label_end_times=train_ends,
        validation_label_end_times=validation_ends,
    )
    poisoned = fit_economic_filter(
        family=family,
        train=train,
        validation=validation,
        test=test.model_copy(update={"targets": (99.0,) * 8}),
        validation_round_trip_costs=(Decimal("0.002"),) * 40,
        train_label_end_times=train_ends,
        validation_label_end_times=validation_ends,
    )
    assert original == poisoned
    assert original.calibration_status is CalibrationStatus.VALIDATION_CALIBRATED
    assert original.primary_direction_source == "TREND_MODULE_ONLY"
    assert all(
        f.calibrated_through is not None and f.calibrated_through < f.available_time
        for f in original.forecasts
    )


def test_overlapping_validation_label_horizon_is_rejected_before_fitting() -> None:
    train, validation, test = dataset(0, 40), dataset(46, 40), dataset(87, 8)
    with pytest.raises(ValueError, match="not purged"):
        fit_economic_filter(
            family="ELASTIC_NET",
            train=train,
            validation=validation,
            test=test,
            train_label_end_times=tuple(t + timedelta(hours=24) for t in train.timestamps),
            validation_label_end_times=tuple(
                t + timedelta(hours=24) for t in validation.timestamps
            ),
            validation_round_trip_costs=(Decimal("0.002"),) * 40,
        )
