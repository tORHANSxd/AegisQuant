"""Auditable PBO, probabilistic/deflated Sharpe, and FDR statistics."""

from __future__ import annotations

import math
from decimal import Decimal
from itertools import combinations
from statistics import NormalDist
from typing import Any, Literal

from pydantic import Field, model_validator

from aegisquant.data.hashing import ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import FiniteDecimal, UnitInterval


def audited_deflated_sharpe_ratio(
    *,
    observed_sharpe: Decimal,
    observations: int,
    skewness: Decimal,
    kurtosis: Decimal,
    trial_sharpes: tuple[Decimal, ...] | None,
    trial_ids: tuple[str, ...] | None,
    complete_trial_history: bool,
    return_frequency: str | None,
    kurtosis_convention: str | None,
    sample_dependence: str | None,
    trial_correlation_policy: str | None,
    evidence_sha256: str | None,
) -> dict[str, Any]:
    """A strict per-period IID diagnostic; unknown dependence/history never fabricates DSR."""
    missing: list[str] = []
    if not complete_trial_history or not trial_ids or not trial_sharpes:
        missing.append("COMPLETE_TRIAL_HISTORY")
    if return_frequency not in {"UTC_DAILY_PER_PERIOD", "UTC_4H_PER_PERIOD"}:
        missing.append("PER_PERIOD_SHARPE_FREQUENCY")
    if kurtosis_convention != "RAW":
        missing.append("RAW_KURTOSIS")
    if sample_dependence != "IID_JUSTIFIED":
        missing.append("SAMPLE_DEPENDENCE_NOT_IDENTIFIED")
    if trial_correlation_policy != "ALL_REGISTERED_CANDIDATES_NO_REDUCTION":
        missing.append("TRIAL_CORRELATION_POLICY")
    if evidence_sha256 is None:
        missing.append("SUPPORTING_EVIDENCE")
    else:
        ensure_sha256(evidence_sha256, field_name="DSR evidence")
    if missing:
        return {"status": "INSUFFICIENT", "probability": None, "missing": missing}
    if trial_ids is None or trial_sharpes is None:
        raise ValueError("DSR full trial history is required")
    if len(trial_ids) != len(trial_sharpes) or len(set(trial_ids)) != len(trial_ids):
        raise ValueError("DSR requires all unique candidate identities aligned with Sharpes")
    result = deflated_sharpe_ratio(
        observed_sharpe=observed_sharpe,
        observations=observations,
        skewness=skewness,
        kurtosis=kurtosis,
        trial_sharpes=trial_sharpes,
    )
    return {
        "status": "SUPPLIED_EVIDENCE_DIAGNOSTIC_ONLY",
        "probability": result.probability,
        "inference": result.model_dump(mode="json"),
        "trial_ids": trial_ids,
        "return_frequency": return_frequency,
        "sample_dependence": sample_dependence,
        "trial_correlation_policy": trial_correlation_policy,
        "evidence_sha256": evidence_sha256,
        "independent_trial_count_estimated": False,
    }


def audited_probability_of_backtest_overfitting(
    returns_by_segment: tuple[tuple[tuple[Decimal, ...], ...], ...] | None,
    *,
    strategy_ids: tuple[str, ...] | None,
    score_id: Literal["MEAN_RETURN_V2", "SHARPE_PER_PERIOD_V2"],
    registered_selection_score_id: str,
    complete_trial_history: bool,
) -> dict[str, Any]:
    """CSCV over raw per-period returns, using the actual frozen selection score.

    Uniform weight across tied training winners; test ties use mid-ranks and
    half weight at the median. Identical candidates are not identifiable.
    """
    if (
        score_id not in {"MEAN_RETURN_V2", "SHARPE_PER_PERIOD_V2"}
        or score_id != registered_selection_score_id
    ):
        raise ValueError("PBO score must match the registered selection algorithm")
    if not complete_trial_history or returns_by_segment is None or strategy_ids is None:
        return {
            "status": "INSUFFICIENT",
            "probability": None,
            "reason": "MISSING_FULL_SELECTION_HISTORY",
        }
    count, strategies = len(returns_by_segment), len(strategy_ids)
    if (
        count < 4
        or count > 12
        or count % 2
        or strategies < 2
        or len(set(strategy_ids)) != strategies
    ):
        raise ValueError("PBO requires 4..12 even segments and unique candidates")
    for segment in returns_by_segment:
        if (
            len(segment) != strategies
            or any(not values for values in segment)
            or len({len(values) for values in segment}) != 1
        ):
            raise ValueError("PBO requires aligned complete per-period returns for every candidate")
        for values in segment:
            for value in values:
                _finite(value, "PBO period return")

    def score(indices: tuple[int, ...], strategy: int) -> Decimal | None:
        values = tuple(value for index in indices for value in returns_by_segment[index][strategy])
        mean = _mean(values)
        if score_id == "MEAN_RETURN_V2":
            return mean
        variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
        return mean / variance.sqrt() if variance > 0 else None

    losses: list[Decimal] = []
    unidentifiable = 0
    tied_selections = 0
    for train in combinations(range(count), count // 2):
        test = tuple(index for index in range(count) if index not in train)
        train_scores = tuple(score(train, i) for i in range(strategies))
        test_scores = tuple(score(test, i) for i in range(strategies))
        if (
            None in train_scores
            or None in test_scores
            or (len(set(train_scores)) == len(set(test_scores)) == 1)
        ):
            unidentifiable += 1
            continue
        known_train = tuple(value for value in train_scores if value is not None)
        known_test = tuple(value for value in test_scores if value is not None)
        winners = tuple(i for i, value in enumerate(known_train) if value == max(known_train))
        tied_selections += len(winners) > 1
        winner_losses: list[Decimal] = []
        for winner in winners:
            lower = sum(value < known_test[winner] for value in known_test)
            equal = sum(value == known_test[winner] for value in known_test)
            rank = Decimal(lower) + Decimal(equal + 1) / 2
            median = Decimal(strategies + 1) / 2
            winner_losses.append(
                Decimal(1) if rank < median else Decimal("0.5") if rank == median else Decimal(0)
            )
        losses.append(_mean(tuple(winner_losses)))
    return {
        "status": "UNIDENTIFIABLE" if unidentifiable else "SUPPLIED_MATRIX_DIAGNOSTIC_ONLY",
        "probability": None if unidentifiable else _mean(tuple(losses)),
        "combinations": math.comb(count, count // 2),
        "unidentifiable_combinations": unidentifiable,
        "tied_training_selections": tied_selections,
        "score_id": score_id,
        "tie_rule": "UNIFORM_TRAIN_WINNERS_TEST_MIDRANK_MEDIAN_HALF",
        "strategy_ids": tuple(sorted(strategy_ids)),
        "causal_walkforward_replacement": False,
    }


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
