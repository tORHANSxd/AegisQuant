"""AegisAlpha-CAT: causal four-hour features and a long/flat trend state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Literal

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from pydantic import Field, model_validator

from aegisquant.backtest.models import BarEvent
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
IntArray = NDArray[np.int64]
CAT_FEATURE_NAMES = (
    "ma_distance_natr",
    "momentum_fast_vol",
    "momentum_slow_vol",
    "breakout_position",
    "log_return_1",
    "log_return_6",
    "log_return_30",
    "log_return_60",
    "log_return_240",
    "natr",
    "realized_vol_6",
    "realized_vol_42",
    "realized_vol_180",
    "downside_semivariance",
    "log_volume_zscore",
    "amihud_proxy",
    "weekend",
)


class TrendPolicy(DomainModel):
    version: Literal["aegisalpha-cat-v1"] = "aegisalpha-cat-v1"
    frequency_seconds: Literal[14400] = 14400
    fast_days: Literal[7, 10, 14] = 10
    slow_days: Literal[30, 40, 60] = 40
    entry_threshold: float = 0.25
    exit_threshold: float = -0.25
    confirmations: int = Field(default=2, ge=1, le=6)
    horizon_bars: Literal[6, 12] = 6
    maximum_weight: float = Field(default=1.0, gt=0, le=1)
    allow_short: Literal[False] = False
    fixed_take_profit: None = None

    @model_validator(mode="after")
    def ordered_thresholds(self) -> TrendPolicy:
        if (
            not np.isfinite(self.entry_threshold)
            or not np.isfinite(self.exit_threshold)
            or self.entry_threshold <= self.exit_threshold
        ):
            raise ValueError("trend entry must exceed exit threshold")
        return self


DEFAULT_TREND_POLICY = TrendPolicy()


@dataclass(frozen=True)
class TrendFeatures:
    available_times: tuple[datetime, ...]
    values: FloatArray
    valid: BoolArray
    annualized_volatility: FloatArray
    feature_names: tuple[str, ...] = CAT_FEATURE_NAMES
    trend_valid: BoolArray | None = None


def _rolling(values: FloatArray, window: int, kind: str) -> FloatArray:
    result = np.full(len(values), np.nan, dtype=np.float64)
    if len(values) < window:
        return result
    view = sliding_window_view(values, window)
    if kind == "mean":
        result[window - 1 :] = np.mean(view, axis=1)
    elif kind == "std":
        result[window - 1 :] = np.std(view, axis=1)
    elif kind == "max":
        result[window - 1 :] = np.max(view, axis=1)
    elif kind == "min":
        result[window - 1 :] = np.min(view, axis=1)
    else:
        raise ValueError("unsupported rolling statistic")
    return result


def _ema(values: FloatArray, window: int, gap: BoolArray) -> FloatArray:
    result = np.empty_like(values)
    alpha = 2 / (window + 1)
    result[0] = values[0]
    for index in range(1, len(values)):
        result[index] = (
            values[index] if gap[index] else alpha * values[index] + (1 - alpha) * result[index - 1]
        )
    return result


def build_trend_features(
    bars: tuple[BarEvent, ...], policy: TrendPolicy = DEFAULT_TREND_POLICY
) -> TrendFeatures:
    if not bars or any(b.event_time >= b.available_time for b in bars):
        raise ValueError("CAT features require completed bars with explicit close availability")
    times = tuple(b.available_time for b in bars)
    if any(a >= b for a, b in pairwise(times)):
        raise ValueError("CAT bar availability must be strictly increasing")
    if any(
        not 14399 <= (bar.available_time - bar.event_time).total_seconds() <= 14400 for bar in bars
    ):
        raise ValueError("CAT requires an explicitly closed four-hour bar")
    close = np.asarray([float(b.close) for b in bars], dtype=np.float64)
    high = np.asarray([float(b.high) for b in bars], dtype=np.float64)
    low = np.asarray([float(b.low) for b in bars], dtype=np.float64)
    volume = np.asarray([float(b.volume) for b in bars], dtype=np.float64)
    gap = np.asarray(
        [True, *((b - a).total_seconds() != 14400 for a, b in pairwise(times))],
        dtype=np.bool_,
    )
    log_price = np.log(close)
    log_returns: dict[int, FloatArray] = {}
    for window in (1, 6, 30, 60, 240, policy.fast_days * 6, policy.slow_days * 6):
        change = np.full(len(close), np.nan, dtype=np.float64)
        change[window:] = log_price[window:] - log_price[:-window]
        log_returns[window] = change
    one = log_returns[1]
    previous: FloatArray = np.r_[close[0], close[:-1]]
    true_range = np.maximum(high - low, np.maximum(np.abs(high - previous), np.abs(low - previous)))
    natr = _ema(true_range, 14, gap) / close
    fast, slow = policy.fast_days * 6, policy.slow_days * 6
    ma_distance = np.log(_ema(close, fast, gap) / _ema(close, slow, gap)) / np.maximum(natr, 1e-12)
    fast_vol, slow_vol = _rolling(one, fast, "std"), _rolling(one, slow, "std")
    upper, lower = _rolling(high, 120, "max"), _rolling(low, 120, "min")
    breakout = (2 * close - upper - lower) / np.maximum(upper - lower, 1e-12)
    vol6, vol42, vol180 = (_rolling(one, length, "std") for length in (6, 42, 180))
    log_volume = np.log1p(volume)
    volume_z = (log_volume - _rolling(log_volume, 42, "mean")) / np.maximum(
        _rolling(log_volume, 42, "std"), 1e-12
    )
    amihud = _rolling(np.abs(one) / np.maximum(close * volume, 1), 42, "mean")
    values = np.column_stack(
        (
            ma_distance,
            log_returns[fast] / np.maximum(fast_vol * np.sqrt(fast), 1e-12),
            log_returns[slow] / np.maximum(slow_vol * np.sqrt(slow), 1e-12),
            breakout,
            *(log_returns[window] for window in (1, 6, 30, 60, 240)),
            natr,
            vol6,
            vol42,
            vol180,
            _rolling(np.minimum(one, 0) ** 2, 42, "mean"),
            volume_z,
            amihud,
            np.asarray([float(time.weekday() >= 5) for time in times], dtype=np.float64),
        )
    )
    last_gap = np.maximum.accumulate(np.where(gap, np.arange(len(bars)), 0))
    valid = (
        np.all(np.isfinite(values), axis=1)
        & (np.arange(len(bars)) - last_gap >= max(240, slow))
        & (volume > 0)
    )
    trend_valid = (
        np.isfinite(ma_distance)
        & np.isfinite(vol42)
        & (volume > 0)
        & (np.arange(len(bars)) - last_gap >= slow)
    )
    return TrendFeatures(times, values, valid, vol42 * np.sqrt(365.25 * 6), trend_valid=trend_valid)


class TrainingRobustScaler(DomainModel):
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    median: tuple[float, ...]
    scale: tuple[float, ...]
    trained_through: UtcDateTime
    train_samples_sha256: str

    def transform(self, values: FloatArray) -> FloatArray:
        if values.ndim != 2 or values.shape[1] != len(self.median):
            raise ValueError("robust transformer feature schema differs")
        return (np.clip(values, self.lower, self.upper) - np.asarray(self.median)) / np.asarray(
            self.scale
        )


def fit_training_scaler(
    features: TrendFeatures, train_indices: IntArray, *, validation_start: datetime
) -> TrainingRobustScaler:
    if len(train_indices) < 20 or np.any(~features.valid[train_indices]):
        raise ValueError("at least twenty valid training rows required")
    selected_times = tuple(features.available_times[int(i)] for i in train_indices)
    if max(selected_times) >= validation_start:
        raise ValueError("scaler training must precede validation")
    values = features.values[train_indices]
    lower, upper = np.quantile(values, (0.01, 0.99), axis=0)
    clipped = np.clip(values, lower, upper)
    median = np.median(clipped, axis=0)
    scale = np.maximum(1.4826 * np.median(np.abs(clipped - median), axis=0), 1e-12)
    return TrainingRobustScaler(
        lower=tuple(map(float, lower)),
        upper=tuple(map(float, upper)),
        median=tuple(map(float, median)),
        scale=tuple(map(float, scale)),
        trained_through=max(selected_times),
        train_samples_sha256=canonical_sha256([time.isoformat() for time in selected_times]),
    )


def trend_targets(
    scores: FloatArray, valid: BoolArray, policy: TrendPolicy = DEFAULT_TREND_POLICY
) -> FloatArray:
    if len(scores) != len(valid):
        raise ValueError("trend scores and validity dimensions differ")
    output = np.zeros(len(scores), dtype=np.float64)
    current = confirmations = 0
    for index, (score, good) in enumerate(zip(scores, valid, strict=True)):
        if not good or not np.isfinite(score) or (current and score < policy.exit_threshold):
            current = confirmations = 0
        elif not current:
            confirmations = confirmations + 1 if score > policy.entry_threshold else 0
            if confirmations >= policy.confirmations:
                current = 1
        output[index] = current
    return output
