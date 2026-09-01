from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import comb

import pytest
from pydantic import ValidationError

from aegisquant.research.validation import (
    SampleSpan,
    TemporalSplitPolicy,
    WalkForwardMode,
    combinatorial_symmetric_splits,
    walk_forward_splits,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def samples(count: int = 12) -> tuple[SampleSpan, ...]:
    return tuple(
        SampleSpan(
            sample_id=f"sample-{index:02d}",
            group_time=NOW + timedelta(hours=index),
            label_start_time=NOW + timedelta(hours=index, minutes=1),
            label_end_time=NOW + timedelta(hours=index, minutes=30),
            regime="BULL" if index % 2 == 0 else "BEAR",
        )
        for index in range(count)
    )


def policy(mode: WalkForwardMode = WalkForwardMode.EXPANDING) -> TemporalSplitPolicy:
    return TemporalSplitPolicy(
        policy_id="p07-walk-forward-v1",
        mode=mode,
        train_groups=3,
        validation_groups=1,
        calibration_groups=1,
        test_groups=1,
        purge_groups=1,
        embargo_groups=1,
        step_groups=1,
        minimum_folds=5,
        shuffle=False,
    )


def test_random_time_split_is_forbidden() -> None:
    payload = policy().model_dump()
    payload["shuffle"] = True
    with pytest.raises(ValidationError, match="RANDOM-TIME-SPLIT-FORBIDDEN"):
        TemporalSplitPolicy.model_validate(payload)


def test_walk_forward_has_five_disjoint_purged_and_embargoed_folds() -> None:
    folds = walk_forward_splits(samples(), policy())
    assert len(folds) == 5
    for fold in folds:
        partitions = (fold.train_ids, fold.validation_ids, fold.calibration_ids, fold.test_ids)
        combined = tuple(value for partition in partitions for value in partition)
        assert len(combined) == len(set(combined))
        assert len(fold.purged_ids) == 2
        assert max(fold.train_ids) < min(fold.validation_ids) < min(fold.test_ids)


def test_recent_state_training_only_uses_validation_regime() -> None:
    folds = walk_forward_splits(samples(), policy(WalkForwardMode.RECENT_STATE))
    by_id = {item.sample_id: item for item in samples()}
    for fold in folds:
        validation_regime = by_id[fold.validation_ids[0]].regime
        assert {by_id[item].regime for item in fold.train_ids} == {validation_regime}


def test_cscv_enumerates_every_symmetric_segment_combination() -> None:
    folds = combinatorial_symmetric_splits(samples(), segment_count=6)
    assert len(folds) == comb(6, 3)
    assert len({item.fold_id for item in folds}) == len(folds)
    assert all(set(item.train_ids).isdisjoint(item.test_ids) for item in folds)
