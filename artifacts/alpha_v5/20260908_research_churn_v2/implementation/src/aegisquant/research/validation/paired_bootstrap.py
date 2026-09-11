"""Paired circular block inference on a common fixed-frequency return clock."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class PairedBootstrap:
    compound_returns: FloatArray
    mean_returns: FloatArray
    observed_compound_returns: FloatArray
    observed_mean_returns: FloatArray
    reality_check_p_value: float
    repetitions: int
    block_bars: int

    def difference(self, candidate: int, baseline: int) -> dict[str, float]:
        delta = self.compound_returns[:, candidate] - self.compound_returns[:, baseline]
        low, high = np.quantile(delta, (0.025, 0.975))
        observed_mean = float(
            self.observed_mean_returns[candidate] - self.observed_mean_returns[baseline]
        )
        centered = self.mean_returns[:, candidate] - self.mean_returns[:, baseline] - observed_mean
        return {
            "observed_compound_return_difference": float(
                self.observed_compound_returns[candidate] - self.observed_compound_returns[baseline]
            ),
            "ci95_lower": float(low),
            "ci95_upper": float(high),
            "one_sided_mean_p_value": float(
                (np.sum(centered >= observed_mean) + 1) / (len(delta) + 1)
            ),
        }


def paired_block_bootstrap(
    values: FloatArray,
    *,
    repetitions: int = 10000,
    block_bars: int = 6,
    seed: int = 20260903,
) -> PairedBootstrap:
    if values.ndim != 2 or not np.all(np.isfinite(values)) or np.any(values <= -1):
        raise ValueError("bootstrap requires finite aligned strategy return columns above -100%")
    count, strategies = values.shape
    if count < block_bars * 4 or block_bars < 1 or repetitions < 100 or strategies < 1:
        raise ValueError("insufficient bootstrap observations or repetitions")
    full_blocks, remainder = divmod(count, block_bars)
    starts_per_draw = full_blocks + bool(remainder)
    # Prefix sums avoid allocating repetitions x bars x strategies arrays.
    doubled = np.concatenate((values, values[:block_bars]), axis=0)
    prefix = np.concatenate((np.zeros((1, strategies)), np.cumsum(doubled, axis=0)))
    log_prefix = np.concatenate((np.zeros((1, strategies)), np.cumsum(np.log1p(doubled), axis=0)))
    block_sum = prefix[block_bars : count + block_bars] - prefix[:count]
    block_log = log_prefix[block_bars : count + block_bars] - log_prefix[:count]
    rng = np.random.default_rng(seed)
    compounded = np.empty((repetitions, strategies))
    means = np.empty_like(compounded)
    for begin in range(0, repetitions, 128):
        end = min(repetitions, begin + 128)
        starts = rng.integers(0, count, size=(end - begin, starts_per_draw))
        totals = np.sum(block_sum[starts[:, :full_blocks]], axis=1)
        logs = np.sum(block_log[starts[:, :full_blocks]], axis=1)
        if remainder:
            last = starts[:, -1]
            totals += prefix[last + remainder] - prefix[last]
            logs += log_prefix[last + remainder] - log_prefix[last]
        compounded[begin:end] = np.expm1(logs)
        means[begin:end] = totals / count
    observed_means = np.mean(values, axis=0)
    max_null = np.max(means - observed_means, axis=1)
    reality_p = (int(np.sum(max_null >= max(0.0, float(np.max(observed_means))))) + 1) / (
        repetitions + 1
    )
    if not math.isfinite(reality_p) or not np.all(np.isfinite(compounded)):
        raise ValueError("bootstrap produced non-finite statistics")
    return PairedBootstrap(
        compounded,
        means,
        np.expm1(np.sum(np.log1p(values), axis=0)),
        observed_means,
        reality_p,
        repetitions,
        block_bars,
    )


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    if not p_values or any(not 0 <= value <= 1 for value in p_values.values()):
        raise ValueError("Holm requires finite probabilities")
    adjusted: dict[str, float] = {}
    previous = 0.0
    for rank, (name, value) in enumerate(sorted(p_values.items(), key=lambda item: item[1])):
        previous = min(1.0, max(previous, (len(p_values) - rank) * value))
        adjusted[name] = previous
    return adjusted
