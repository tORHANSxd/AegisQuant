"""Natural-month walk-forward partitions with explicit label purge and bar embargo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from aegisquant.data.hashing import canonical_sha256
from aegisquant.research.validation.splits import SampleSpan, purge_interval_partitions


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


@dataclass(frozen=True)
class CalendarIntervalFold(CalendarFold):
    purged_indices: tuple[int, ...]
    interval_contract_sha256: str
    source_span_sha256: str
    source_sample_ids: tuple[str, ...]


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
    sample_spans: tuple[SampleSpan, ...] | None = None,
) -> tuple[CalendarFold, ...]:
    if not len(available_times) == len(label_end_times) == len(valid):
        raise ValueError("walk-forward metadata dimensions differ")
    if any((a >= b if sample_spans is None else a > b) for a, b in pairwise(available_times)):
        raise ValueError("walk-forward availability must strictly increase")
    if sample_spans is not None and (
        len(sample_spans) != len(available_times)
        or any(
            span.group_time != time or span.label_end_time != end
            for span, time, end in zip(sample_spans, available_times, label_end_times, strict=True)
        )
    ):
        raise ValueError("strict calendar span identities/times must align with observations")
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
        strict_removed: tuple[int, ...] = ()
        interval_hash = None
        if sample_spans is not None:
            # Include long labels before interval purge so their whole time group
            # is removed, rather than losing the offending row in legacy filtering.
            invalid_times = {
                time for time, good in zip(available_times, valid, strict=True) if not good
            }
            raw = tuple(
                tuple(
                    span
                    for span, good in zip(sample_spans, valid, strict=True)
                    if good
                    and span.group_time not in invalid_times
                    and left <= span.group_time < right
                )
                for left, right in (
                    (start, validation_start - purge),
                    (validation_start + embargo, test_start - purge),
                    (test_start + embargo, test_end),
                )
            )
            kept, _ = purge_interval_partitions(
                raw, ends=(validation_start, test_start, test_end), information_embargo=embargo
            )
            index_by_id = {span.sample_id: i for i, span in enumerate(sample_spans)}
            if len(index_by_id) != len(sample_spans):
                raise ValueError("calendar sample identities must be unique")
            train, validation, test = (
                tuple(index_by_id[item.sample_id] for item in part) for part in kept
            )
            all_kept = set(train + validation + test)
            strict_removed = tuple(
                i
                for i, (time, good) in enumerate(zip(available_times, valid, strict=True))
                if good and start <= time < test_end and i not in all_kept
            )
            interval_hash = canonical_sha256(
                {
                    "policy": "ALL_BOUNDARIES_INTERVAL_V2",
                    "spans": [item.model_dump(mode="json") for part in raw for item in part],
                    "removed": strict_removed,
                }
            )
        if min(len(train), len(validation), len(test)) < 20:
            raise ValueError("insufficient valid observations in calendar partition")
        fold = CalendarFold(
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
        if interval_hash is not None:
            fold = CalendarIntervalFold(
                **fold.__dict__,
                purged_indices=strict_removed,
                interval_contract_sha256=interval_hash,
                source_span_sha256=canonical_sha256(
                    [item.model_dump(mode="json") for item in sample_spans or ()]
                ),
                source_sample_ids=tuple(item.sample_id for item in sample_spans or ()),
            )
        folds.append(fold)
        start = add_months(start, step_months)
    return tuple(folds)
