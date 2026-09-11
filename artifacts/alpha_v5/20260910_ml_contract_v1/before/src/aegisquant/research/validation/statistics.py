"""Auditable PBO, probabilistic/deflated Sharpe, and FDR statistics."""

from __future__ import annotations

import math
from decimal import Decimal
from itertools import combinations
from statistics import NormalDist

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import FiniteDecimal, UnitInterval

EULER_MASCHERONI = 0.5772156649015329


def _finite(value: Decimal, name: str) -> float:
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return float(value)


def _decimal(value: float) -> Decimal:
    if not math.isfinite(value):
        raise ValueError("statistic produced non-finite result")
    return Decimal(format(value, ".15g"))


class SharpeInference(DomainModel):
    observed_sharpe: FiniteDecimal
    benchmark_sharpe: FiniteDecimal
    probability: UnitInterval
    observations: int = Field(ge=2)
    skewness: FiniteDecimal
    kurtosis: FiniteDecimal


def probabilistic_sharpe_ratio(
    *,
    observed_sharpe: Decimal,
    benchmark_sharpe: Decimal,
    observations: int,
    skewness: Decimal,
    kurtosis: Decimal,
) -> SharpeInference:
    if observations < 2:
        raise ValueError("PSR requires at least two observations")
    observed = _finite(observed_sharpe, "observed_sharpe")
    benchmark = _finite(benchmark_sharpe, "benchmark_sharpe")
    skew = _finite(skewness, "skewness")
    kurt = _finite(kurtosis, "kurtosis")
    if kurt < 1:
        raise ValueError("PSR kurtosis must be raw kurtosis >= 1")
    denominator_sq = 1.0 - skew * observed + ((kurt - 1.0) / 4.0) * observed**2
    if denominator_sq <= 0:
        raise ValueError("PSR variance adjustment must be positive")
    statistic = (observed - benchmark) * math.sqrt(observations - 1) / math.sqrt(denominator_sq)
    probability = min(1.0, max(0.0, NormalDist().cdf(statistic)))
    return SharpeInference(
        observed_sharpe=observed_sharpe,
        benchmark_sharpe=benchmark_sharpe,
        probability=_decimal(probability),
        observations=observations,
        skewness=skewness,
        kurtosis=kurtosis,
    )


def deflated_sharpe_ratio(
    *,
    observed_sharpe: Decimal,
    observations: int,
    skewness: Decimal,
    kurtosis: Decimal,
    trial_sharpes: tuple[Decimal, ...],
) -> SharpeInference:
    if not trial_sharpes:
        raise ValueError("DSR requires all trial Sharpes")
    trials = tuple(_finite(item, "trial_sharpe") for item in trial_sharpes)
    if len(trials) == 1:
        benchmark = 0.0
    else:
        mean = sum(trials) / len(trials)
        variance = sum((item - mean) ** 2 for item in trials) / (len(trials) - 1)
        standard_deviation = math.sqrt(variance)
        count = len(trials)
        expected_max_z = (1.0 - EULER_MASCHERONI) * NormalDist().inv_cdf(
            1.0 - 1.0 / count
        ) + EULER_MASCHERONI * NormalDist().inv_cdf(1.0 - 1.0 / (count * math.e))
        benchmark = standard_deviation * expected_max_z
    return probabilistic_sharpe_ratio(
        observed_sharpe=observed_sharpe,
        benchmark_sharpe=_decimal(benchmark),
        observations=observations,
        skewness=skewness,
        kurtosis=kurtosis,
    )


class PBOResult(DomainModel):
    probability: UnitInterval
    logits: tuple[FiniteDecimal, ...]
    combinations: int = Field(gt=0)
    segment_count: int = Field(ge=4)
    strategy_count: int = Field(ge=2)


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def probability_of_backtest_overfitting(
    returns_by_segment: tuple[tuple[Decimal, ...], ...],
) -> PBOResult:
    segment_count = len(returns_by_segment)
    if segment_count < 4 or segment_count % 2:
        raise ValueError("PBO requires an even number of at least four segments")
    strategy_count = len(returns_by_segment[0]) if returns_by_segment else 0
    if strategy_count < 2 or any(len(row) != strategy_count for row in returns_by_segment):
        raise ValueError("PBO requires a rectangular matrix with at least two strategies")
    for row in returns_by_segment:
        for value in row:
            _finite(value, "segment return")
    logits: list[Decimal] = []
    all_segments = set(range(segment_count))
    for train_indices in combinations(range(segment_count), segment_count // 2):
        test_indices = tuple(sorted(all_segments - set(train_indices)))
        train_scores = tuple(
            _mean(tuple(returns_by_segment[index][strategy] for index in train_indices))
            for strategy in range(strategy_count)
        )
        selected = max(range(strategy_count), key=lambda index: (train_scores[index], -index))
        test_scores = tuple(
            _mean(tuple(returns_by_segment[index][strategy] for index in test_indices))
            for strategy in range(strategy_count)
        )
        ordered = sorted(range(strategy_count), key=lambda index: (test_scores[index], index))
        rank_from_worst = ordered.index(selected) + 1
        relative_rank = rank_from_worst / (strategy_count + 1)
        logits.append(_decimal(math.log(relative_rank / (1.0 - relative_rank))))
    probability = sum(value <= 0 for value in logits) / len(logits)
    return PBOResult(
        probability=_decimal(probability),
        logits=tuple(logits),
        combinations=len(logits),
        segment_count=segment_count,
        strategy_count=strategy_count,
    )


class AdjustedPValue(DomainModel):
    hypothesis_id: str
    raw_p_value: UnitInterval
    adjusted_p_value: UnitInterval
    rejected: bool


class MultipleTestingReport(DomainModel):
    method: str
    alpha: UnitInterval
    total_trials: int = Field(gt=0)
    results: tuple[AdjustedPValue, ...]

    @model_validator(mode="after")
    def validate_count(self) -> MultipleTestingReport:
        if len(self.results) != self.total_trials:
            raise ValueError("multiple-testing report must include every trial")
        return self


def benjamini_hochberg(p_values: dict[str, Decimal], *, alpha: Decimal) -> MultipleTestingReport:
    if not p_values:
        raise ValueError("FDR correction requires p-values")
    alpha_float = _finite(alpha, "alpha")
    if not 0 < alpha_float < 1:
        raise ValueError("alpha must be in (0, 1)")
    ordered = sorted(
        ((hypothesis_id, _finite(value, "p_value")) for hypothesis_id, value in p_values.items()),
        key=lambda item: (item[1], item[0]),
    )
    count = len(ordered)
    adjusted = [0.0] * count
    running = 1.0
    for index in range(count - 1, -1, -1):
        rank = index + 1
        running = min(running, ordered[index][1] * count / rank)
        adjusted[index] = min(1.0, running)
    results = tuple(
        AdjustedPValue(
            hypothesis_id=hypothesis_id,
            raw_p_value=_decimal(raw),
            adjusted_p_value=_decimal(adjusted[index]),
            rejected=adjusted[index] <= alpha_float,
        )
        for index, (hypothesis_id, raw) in enumerate(ordered)
    )
    return MultipleTestingReport(
        method="Benjamini-Hochberg FDR",
        alpha=alpha,
        total_trials=count,
        results=results,
    )
