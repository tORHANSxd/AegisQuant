"""Paired circular block inference on a common fixed-frequency return clock."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
LOG_GROWTH_ESTIMAND = "MEAN_LOG_NET_RETURN_DIFFERENCE_PER_OBSERVATION_V1"


@dataclass(frozen=True)
class PairedBootstrap:
    compound_returns: FloatArray
    mean_returns: FloatArray
    observed_compound_returns: FloatArray
    observed_mean_returns: FloatArray
    reality_check_p_value: float
    repetitions: int
    block_bars: int

    @property
    def estimand_ids(self) -> dict[str, str]:
        """Sidecar identity; legacy serialized fields and difference keys stay intact."""
        return {
            "ci95": "TERMINAL_COMPOUND_NET_RETURN_DIFFERENCE_V1",
            "one_sided_mean_p_value": "MEAN_SIMPLE_NET_RETURN_DIFFERENCE_PER_OBSERVATION_V1",
        }

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


def _validate_returns(values: FloatArray, repetitions: int, block_bars: int) -> None:
    if values.ndim != 2 or not np.all(np.isfinite(values)) or np.any(values <= -1):
        raise ValueError("bootstrap requires finite aligned strategy return columns above -100%")
    count, strategies = values.shape
    if count < block_bars * 4 or block_bars < 1 or repetitions < 100 or strategies < 1:
        raise ValueError("insufficient bootstrap observations or repetitions")


def _circular_block_totals(
    values: FloatArray, *, repetitions: int, block_bars: int, seed: int
) -> FloatArray:
    """One shared row-index draw for every column; never draw assets independently."""
    count, strategies = values.shape
    full_blocks, remainder = divmod(count, block_bars)
    starts_per_draw = full_blocks + bool(remainder)
    # Prefix sums avoid allocating repetitions x bars x strategies arrays.
    doubled = np.concatenate((values, values[:block_bars]), axis=0)
    prefix = np.concatenate((np.zeros((1, strategies)), np.cumsum(doubled, axis=0)))
    block_sum = prefix[block_bars : count + block_bars] - prefix[:count]
    rng = np.random.default_rng(seed)
    sampled = np.empty((repetitions, strategies))
    for begin in range(0, repetitions, 128):
        end = min(repetitions, begin + 128)
        starts = rng.integers(0, count, size=(end - begin, starts_per_draw))
        totals = np.sum(block_sum[starts[:, :full_blocks]], axis=1)
        if remainder:
            last = starts[:, -1]
            totals += prefix[last + remainder] - prefix[last]
        sampled[begin:end] = totals
    return sampled


def paired_block_bootstrap(
    values: FloatArray,
    *,
    repetitions: int = 10000,
    block_bars: int = 6,
    seed: int = 20260903,
) -> PairedBootstrap:
    _validate_returns(values, repetitions, block_bars)
    count = len(values)
    means = (
        _circular_block_totals(values, repetitions=repetitions, block_bars=block_bars, seed=seed)
        / count
    )
    compounded = np.expm1(
        _circular_block_totals(
            np.log1p(values), repetitions=repetitions, block_bars=block_bars, seed=seed
        )
    )
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


@dataclass(frozen=True)
class PairedLogGrowth:
    """CI and centered one-sided test for the same mean log-growth difference."""

    mean_log_returns: FloatArray
    observed_mean_log_returns: FloatArray
    repetitions: int
    block_bars: int
    estimand_id: str = LOG_GROWTH_ESTIMAND

    def difference(self, candidate: int, baseline: int) -> dict[str, float | str]:
        delta = self.mean_log_returns[:, candidate] - self.mean_log_returns[:, baseline]
        observed = float(
            self.observed_mean_log_returns[candidate] - self.observed_mean_log_returns[baseline]
        )
        low, high = np.quantile(delta, (0.025, 0.975))
        return {
            "estimand_id": self.estimand_id,
            "observed_mean_log_return_difference": observed,
            "ci95_lower": float(low),
            "ci95_upper": float(high),
            "one_sided_p_value": float(
                (np.sum(delta - observed >= observed) + 1) / (self.repetitions + 1)
            ),
        }


def paired_log_growth_bootstrap(
    values: FloatArray,
    *,
    repetitions: int = 10000,
    block_bars: int,
    seed: int,
) -> PairedLogGrowth:
    """Inputs are simple net returns on a caller-validated common clock, including CASH."""
    _validate_returns(values, repetitions, block_bars)
    logs = np.log1p(values)
    sampled = _circular_block_totals(
        logs, repetitions=repetitions, block_bars=block_bars, seed=seed
    ) / len(values)
    if not np.all(np.isfinite(sampled)):
        raise ValueError("bootstrap produced non-finite log growth")
    return PairedLogGrowth(sampled, np.mean(logs, axis=0), repetitions, block_bars)


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    if not p_values or any(not 0 <= value <= 1 for value in p_values.values()):
        raise ValueError("Holm requires finite probabilities")
    adjusted: dict[str, float] = {}
    previous = 0.0
    for rank, (name, value) in enumerate(sorted(p_values.items(), key=lambda item: item[1])):
        previous = min(1.0, max(previous, (len(p_values) - rank) * value))
        adjusted[name] = previous
    return adjusted
