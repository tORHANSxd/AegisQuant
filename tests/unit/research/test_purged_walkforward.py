from datetime import UTC, datetime, timedelta

import pytest

from aegisquant.research.validation.calendar_walkforward import add_months, calendar_walkforward


def test_calendar_months_purge_label_overlap_and_embargo() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    times = tuple(start + timedelta(hours=4 * i) for i in range(4000))
    labels = tuple(time + timedelta(hours=48) for time in times)
    folds = calendar_walkforward(
        available_times=times,
        label_end_times=labels,
        valid=(True,) * len(times),
        first_train_start=start,
        development_end=datetime(2021, 10, 1, tzinfo=UTC),
    )
    assert len(folds) == 2
    seen: set[int] = set()
    for fold in folds:
        assert fold.validation_start == add_months(fold.train_start, 12)
        assert fold.test_end == add_months(fold.test_start, 3)
        assert max(labels[i] for i in fold.train_indices) < fold.validation_start
        assert max(labels[i] for i in fold.validation_indices) < fold.test_start
        assert min(times[i] for i in fold.test_indices) >= fold.test_start + timedelta(hours=4)
        assert not seen.intersection(fold.test_indices)
        seen.update(fold.test_indices)


def test_insufficient_purge_is_rejected() -> None:
    with pytest.raises(ValueError, match="purge"):
        calendar_walkforward(
            available_times=(),
            label_end_times=(),
            valid=(),
            first_train_start=datetime(2020, 1, 1, tzinfo=UTC),
            development_end=datetime(2022, 1, 1, tzinfo=UTC),
            purge_bars=6,
        )
