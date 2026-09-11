"""Natural-month walk-forward partitions with explicit label purge and bar embargo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise


def add_months(value: datetime, months: int) -> datetime:
    if value.day != 1 or any((value.hour, value.minute, value.second, value.microsecond)):
        raise ValueError("calendar boundaries must be UTC month starts")
    if value.utcoffset() != timedelta(0):
        raise ValueError("calendar boundaries must use UTC")
    year, month = divmod(value.year * 12 + value.month - 1 + months, 12)
    return value.replace(year=year, month=month + 1)


@dataclass(frozen=True)
class CalendarFold:
    fold_id: str
    train_start: datetime
    validation_start: datetime
    test_start: datetime
    test_end: datetime
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    purge_bars: int
    embargo_bars: int


def calendar_walkforward(
    *,
    available_times: tuple[datetime, ...],
    label_end_times: tuple[datetime | None, ...],
    valid: tuple[bool, ...],
    first_train_start: datetime,
    development_end: datetime,
    train_months: int = 12,
    validation_months: int = 3,
    test_months: int = 3,
    step_months: int = 3,
    maximum_horizon_bars: int = 12,
    purge_bars: int = 12,
    embargo_bars: int = 1,
    frequency_seconds: int = 14400,
) -> tuple[CalendarFold, ...]:
    if not len(available_times) == len(label_end_times) == len(valid):
        raise ValueError("walk-forward metadata dimensions differ")
    if any(a >= b for a, b in pairwise(available_times)):
        raise ValueError("walk-forward availability must strictly increase")
    if min(train_months, validation_months, test_months, step_months, frequency_seconds) <= 0:
        raise ValueError("walk-forward windows must be positive")
    if purge_bars < maximum_horizon_bars or embargo_bars < 1 or maximum_horizon_bars < 1:
        raise ValueError("purge must cover maximum horizon and embargo at least one bar")
    if step_months < test_months:
        raise ValueError("test folds must not overlap")
    add_months(development_end, 0)
    folds: list[CalendarFold] = []
    start = first_train_start
    purge = timedelta(seconds=purge_bars * frequency_seconds)
    embargo = timedelta(seconds=embargo_bars * frequency_seconds)
    while True:
        validation_start = add_months(start, train_months)
        test_start = add_months(validation_start, validation_months)
        test_end = add_months(test_start, test_months)
        if test_end > development_end:
            break

        def labelled(left: datetime, right: datetime) -> tuple[int, ...]:
            return tuple(
                i
                for i, (time, end, good) in enumerate(
                    zip(available_times, label_end_times, valid, strict=True)
                )
                if good and left <= time < right - purge and end is not None and end < right
            )

        train = labelled(start, validation_start)
        validation = labelled(validation_start + embargo, test_start)
        test = tuple(
            i
            for i, (time, good) in enumerate(zip(available_times, valid, strict=True))
            if good and test_start + embargo <= time < test_end
        )
        if min(len(train), len(validation), len(test)) < 20:
            raise ValueError("insufficient valid observations in calendar partition")
        folds.append(
            CalendarFold(
                f"{test_start:%Y%m}-{test_end:%Y%m}",
                start,
                validation_start,
                test_start,
                test_end,
                train,
                validation,
                test,
                purge_bars,
                embargo_bars,
            )
        )
        start = add_months(start, step_months)
    return tuple(folds)
