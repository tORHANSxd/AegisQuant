"""Temporal walk-forward, purge/embargo, CPCV, and CSCV split contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum
from itertools import combinations
from typing import Annotated

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime


class WalkForwardMode(StrEnum):
    EXPANDING = "EXPANDING"
    ROLLING = "ROLLING"
    RECENT_STATE = "RECENT_STATE"


class SampleSpan(DomainModel):
    sample_id: str
    group_time: UtcDateTime
    label_start_time: UtcDateTime
    label_end_time: UtcDateTime
    regime: str | None = None

    @model_validator(mode="after")
    def validate_span(self) -> SampleSpan:
        if not self.group_time < self.label_start_time <= self.label_end_time:
            raise ValueError("sample label window must be strictly future")
        return self


class TemporalSplitPolicy(DomainModel):
    policy_id: str
    mode: WalkForwardMode
    train_groups: Annotated[int, Field(ge=2)]
    validation_groups: Annotated[int, Field(ge=1)]
    calibration_groups: Annotated[int, Field(ge=1)]
    test_groups: Annotated[int, Field(ge=1)]
    purge_groups: Annotated[int, Field(ge=0)]
    embargo_groups: Annotated[int, Field(ge=0)]
    step_groups: Annotated[int, Field(ge=1)]
    minimum_folds: Annotated[int, Field(ge=1)] = 1
    shuffle: bool = False

    @model_validator(mode="after")
    def random_time_split_is_forbidden(self) -> TemporalSplitPolicy:
        if self.shuffle:
            raise ValueError("AQ-RESEARCH-RANDOM-TIME-SPLIT-FORBIDDEN")
        return self


class TemporalFold(DomainModel):
    fold_id: str
    train_ids: tuple[str, ...]
    validation_ids: tuple[str, ...]
    calibration_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    purged_ids: tuple[str, ...]
    validation_starts_at: UtcDateTime
    test_ends_at: UtcDateTime

    @model_validator(mode="after")
    def validate_partitions(self) -> TemporalFold:
        partitions = (
            self.train_ids,
            self.validation_ids,
            self.calibration_ids,
            self.test_ids,
        )
        if any(not values for values in partitions):
            raise ValueError("temporal fold partitions cannot be empty")
        combined = tuple(value for partition in partitions for value in partition)
        if len(set(combined)) != len(combined):
            raise ValueError("temporal fold partitions must be disjoint")
        payload = {
            "train_ids": list(self.train_ids),
            "validation_ids": list(self.validation_ids),
            "calibration_ids": list(self.calibration_ids),
            "test_ids": list(self.test_ids),
            "purged_ids": list(self.purged_ids),
            "validation_starts_at": self.validation_starts_at.isoformat(),
            "test_ends_at": self.test_ends_at.isoformat(),
        }
        if self.fold_id != canonical_sha256(payload):
            raise ValueError("fold id must equal canonical partition hash")
        return self


def _sample_ids(
    grouped: dict[UtcDateTime, tuple[SampleSpan, ...]], selected_times: tuple[UtcDateTime, ...]
) -> tuple[str, ...]:
    return tuple(sorted(sample.sample_id for time in selected_times for sample in grouped[time]))


def walk_forward_splits(
    samples: Iterable[SampleSpan], policy: TemporalSplitPolicy
) -> tuple[TemporalFold, ...]:
    values = tuple(samples)
    if len({item.sample_id for item in values}) != len(values):
        raise ValueError("sample ids must be unique")
    grouped_lists: dict[UtcDateTime, list[SampleSpan]] = defaultdict(list)
    for sample in values:
        grouped_lists[sample.group_time].append(sample)
    grouped = {
        time: tuple(sorted(items, key=lambda item: item.sample_id))
        for time, items in grouped_lists.items()
    }
    times = tuple(sorted(grouped))
    fixed_after_train = (
        policy.purge_groups
        + policy.validation_groups
        + policy.calibration_groups
        + policy.embargo_groups
        + policy.test_groups
    )
    folds: list[TemporalFold] = []
    train_end = policy.train_groups
    while train_end + fixed_after_train <= len(times):
        validation_start = train_end + policy.purge_groups
        validation_end = validation_start + policy.validation_groups
        calibration_end = validation_end + policy.calibration_groups
        test_start = calibration_end + policy.embargo_groups
        test_end = test_start + policy.test_groups

        train_times = (
            times[:train_end]
            if policy.mode is WalkForwardMode.EXPANDING
            else times[max(0, train_end - policy.train_groups) : train_end]
        )
        validation_times = times[validation_start:validation_end]
        calibration_times = times[validation_end:calibration_end]
        test_times = times[test_start:test_end]
        validation_boundary = validation_times[0]
        train_samples = tuple(
            sample
            for time in train_times
            for sample in grouped[time]
            if sample.label_end_time < validation_boundary
        )
        removed = tuple(
            sample
            for time in train_times
            for sample in grouped[time]
            if sample.label_end_time >= validation_boundary
        )
        if policy.mode is WalkForwardMode.RECENT_STATE:
            target_regime = grouped[validation_times[0]][0].regime
            train_samples = tuple(
                sample for sample in train_samples if sample.regime == target_regime
            )
        if not train_samples:
            raise ValueError("purge or state filtering removed all training samples")
        train_ids = tuple(sorted(sample.sample_id for sample in train_samples))
        validation_ids = _sample_ids(grouped, validation_times)
        calibration_ids = _sample_ids(grouped, calibration_times)
        test_ids = _sample_ids(grouped, test_times)
        gap_times = times[train_end:validation_start] + times[calibration_end:test_start]
        purged_ids = tuple(
            sorted(
                {
                    *(sample.sample_id for sample in removed),
                    *(sample.sample_id for time in gap_times for sample in grouped[time]),
                }
            )
        )
        payload = {
            "train_ids": list(train_ids),
            "validation_ids": list(validation_ids),
            "calibration_ids": list(calibration_ids),
            "test_ids": list(test_ids),
            "purged_ids": list(purged_ids),
            "validation_starts_at": validation_boundary.isoformat(),
            "test_ends_at": test_times[-1].isoformat(),
        }
        folds.append(
            TemporalFold(
                fold_id=canonical_sha256(payload),
                train_ids=train_ids,
                validation_ids=validation_ids,
                calibration_ids=calibration_ids,
                test_ids=test_ids,
                purged_ids=purged_ids,
                validation_starts_at=validation_boundary,
                test_ends_at=test_times[-1],
            )
        )
        train_end += policy.step_groups
    if len(folds) < policy.minimum_folds:
        raise ValueError(
            f"walk-forward produced {len(folds)} folds; {policy.minimum_folds} required"
        )
    return tuple(folds)


class CombinatorialFold(DomainModel):
    fold_id: str
    train_segment_ids: tuple[int, ...]
    test_segment_ids: tuple[int, ...]
    train_ids: tuple[str, ...]
    test_ids: tuple[str, ...]


def combinatorial_symmetric_splits(
    samples: Iterable[SampleSpan], *, segment_count: int
) -> tuple[CombinatorialFold, ...]:
    values = tuple(sorted(samples, key=lambda item: (item.group_time, item.sample_id)))
    if segment_count < 4 or segment_count % 2 or segment_count > 12:
        raise ValueError("CSCV segment_count must be even and between 4 and 12")
    times = tuple(sorted({item.group_time for item in values}))
    if len(times) < segment_count:
        raise ValueError("CSCV requires at least one time group per segment")
    segment_by_time = {
        time: min(index * segment_count // len(times), segment_count - 1)
        for index, time in enumerate(times)
    }
    ids_by_segment = {
        segment: tuple(
            item.sample_id for item in values if segment_by_time[item.group_time] == segment
        )
        for segment in range(segment_count)
    }
    output: list[CombinatorialFold] = []
    all_segments = set(range(segment_count))
    for test_segments_tuple in combinations(range(segment_count), segment_count // 2):
        test_segments = tuple(test_segments_tuple)
        train_segments = tuple(sorted(all_segments - set(test_segments)))
        train_ids = tuple(
            sample_id for segment in train_segments for sample_id in ids_by_segment[segment]
        )
        test_ids = tuple(
            sample_id for segment in test_segments for sample_id in ids_by_segment[segment]
        )
        payload = {
            "train_segment_ids": list(train_segments),
            "test_segment_ids": list(test_segments),
            "train_ids": list(train_ids),
            "test_ids": list(test_ids),
        }
        output.append(
            CombinatorialFold(
                fold_id=canonical_sha256(payload),
                train_segment_ids=train_segments,
                test_segment_ids=test_segments,
                train_ids=train_ids,
                test_ids=test_ids,
            )
        )
    return tuple(output)
