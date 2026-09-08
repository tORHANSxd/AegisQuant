"""Prediction diagnostics, deliberately separate from trading profitability."""

from __future__ import annotations

import math
from decimal import Decimal
from statistics import NormalDist

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    UnitInterval,
    canonical_result,
)


class PredictionMetrics(DomainModel):
    mean_squared_error: NonNegativeDecimal
    mean_absolute_error: NonNegativeDecimal
    r2_out_of_sample: FiniteDecimal | None
    pearson_ic: FiniteDecimal | None
    spearman_ic: FiniteDecimal | None
    direction_accuracy: UnitInterval
    balanced_accuracy: UnitInterval
    macro_f1: UnitInterval
    matthews_correlation: FiniteDecimal | None
    # Rows are actual, columns predicted, in SHORT / FLAT / LONG order.
    confusion_matrix: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
    class_order: tuple[str, str, str] = ("SHORT", "FLAT", "LONG")
    brier_score: NonNegativeDecimal | None
    brier_scope: str
    calibration_error: NonNegativeDecimal | None
    abstention_coverage: UnitInterval
    sign_test_statistic: FiniteDecimal | None
    sign_test_p_value: UnitInterval | None
    sign_test_observations: int
    sign_test_assumption: str = "PT1992 asymptotic independence; not a serial-dependence gate"
    r2_benchmark: str = "UNAVAILABLE_UNLESS_SUPPLIED_FROM_PAST_DATA"


def _finite(value: float | None) -> Decimal | None:
    return (
        canonical_result(Decimal(str(value)))
        if value is not None and math.isfinite(value)
        else None
    )


def _correlation(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    a, b = [v - mean_left for v in left], [v - mean_right for v in right]
    denominator = math.sqrt(sum(v * v for v in a) * sum(v * v for v in b))
    return (
        max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b, strict=True)) / denominator))
        if denominator
        else None
    )


def _ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        for index in ordered[start:end]:
            ranks[index] = (start + end - 1) / 2 + 1
        start = end
    return tuple(ranks)


def prediction_metrics(
    predicted: tuple[Decimal, ...],
    actual: tuple[Decimal, ...],
    *,
    flat_band: Decimal = Decimal("0"),
    past_benchmark: tuple[Decimal, ...] | None = None,
    class_probabilities: tuple[tuple[Decimal, Decimal, Decimal], ...] | None = None,
    positive_probabilities: tuple[Decimal, ...] | None = None,
) -> PredictionMetrics:
    if not predicted or len(predicted) != len(actual) or flat_band < 0:
        raise ValueError("prediction metric dimensions or flat band are invalid")
    count = len(actual)
    if past_benchmark is not None and len(past_benchmark) != count:
        raise ValueError("past-only benchmark dimensions differ")
    for probability_rows in (class_probabilities, positive_probabilities):
        if probability_rows is not None and len(probability_rows) != count:
            raise ValueError("probability dimensions differ")
    if any(not value.is_finite() for value in (*predicted, *actual)):
        raise ValueError("prediction metrics require finite observations")
    errors = tuple(p - a for p, a in zip(predicted, actual, strict=True))
    sse = sum((error * error for error in errors), Decimal("0"))
    benchmark_sse = (
        sum(((b - a) ** 2 for b, a in zip(past_benchmark, actual, strict=True)), Decimal("0"))
        if past_benchmark is not None
        else Decimal("0")
    )

    def category(value: Decimal) -> int:
        return 2 if value > flat_band else 0 if value < -flat_band else 1

    p_class, a_class = tuple(map(category, predicted)), tuple(map(category, actual))
    matrix = [[0] * 3 for _ in range(3)]
    for p, a in zip(p_class, a_class, strict=True):
        matrix[a][p] += 1
    actual_count = [sum(row) for row in matrix]
    predicted_count = [sum(matrix[a][p] for a in range(3)) for p in range(3)]
    correct = sum(matrix[k][k] for k in range(3))
    # Balanced accuracy averages recalls of supported actual classes; macro-F1
    # always includes all three classes (undefined F1 is zero).
    recalls = [Decimal(matrix[k][k]) / actual_count[k] for k in range(3) if actual_count[k]]
    f1 = [
        Decimal(2 * matrix[k][k]) / (actual_count[k] + predicted_count[k])
        if actual_count[k] + predicted_count[k]
        else Decimal("0")
        for k in range(3)
    ]
    mcc_denominator = Decimal(
        (count**2 - sum(x * x for x in actual_count))
        * (count**2 - sum(x * x for x in predicted_count))
    ).sqrt()
    mcc_numerator = correct * count - sum(
        a * p for a, p in zip(actual_count, predicted_count, strict=True)
    )
    brier: Decimal | None = None
    calibration: Decimal | None = None
    confidence_hits: list[tuple[Decimal, bool]] = []
    scope = "UNAVAILABLE"
    if class_probabilities is not None:
        if any(
            any(p < 0 or p > 1 for p in row) or abs(sum(row) - 1) > Decimal("1e-12")
            for row in class_probabilities
        ):
            raise ValueError("class probabilities must sum to one")
        brier = (
            sum(
                (
                    sum(((p - int(k == a)) ** 2 for k, p in enumerate(row)), Decimal("0"))
                    for row, a in zip(class_probabilities, a_class, strict=True)
                ),
                Decimal("0"),
            )
            / count
        )
        confidence_hits = [
            (max(row), max(range(3), key=row.__getitem__) == a)
            for row, a in zip(class_probabilities, a_class, strict=True)
        ]
        scope = "THREE_CLASS_SUM_SQUARED_ERROR"
    elif positive_probabilities is not None:
        if any(p < 0 or p > 1 for p in positive_probabilities):
            raise ValueError("positive probabilities must lie in [0, 1]")
        brier = (
            sum(
                (
                    (p - int(a == 2)) ** 2
                    for p, a in zip(positive_probabilities, a_class, strict=True)
                ),
                Decimal("0"),
            )
            / count
        )
        confidence_hits = [
            (p, a == 2) for p, a in zip(positive_probabilities, a_class, strict=True)
        ]
        scope = "LONG_VS_REST"
    if confidence_hits:
        calibration = Decimal("0")
        for bin_index in range(10):
            bucket = [(p, hit) for p, hit in confidence_hits if min(9, int(p * 10)) == bin_index]
            if bucket:
                calibration += (
                    abs(sum((p for p, _ in bucket), Decimal("0")) - sum(hit for _, hit in bucket))
                    / count
                )

    signed = [(p > 0, a > 0) for p, a in zip(predicted, actual, strict=True) if p != 0 and a != 0]
    size = len(signed)
    statistic = p_value = None
    if size >= 2:
        p_forecast = sum(p for p, _ in signed) / size
        p_actual = sum(a for _, a in signed) / size
        p_expected = p_forecast * p_actual + (1 - p_forecast) * (1 - p_actual)
        variance = p_expected * (1 - p_expected) / size
        estimated_variance = (
            (2 * p_forecast - 1) ** 2 * p_actual * (1 - p_actual)
            + (2 * p_actual - 1) ** 2 * p_forecast * (1 - p_forecast)
        ) / size + 4 * p_actual * p_forecast * (1 - p_actual) * (1 - p_forecast) / size**2
        if variance > estimated_variance:
            statistic = (sum(p == a for p, a in signed) / size - p_expected) / math.sqrt(
                variance - estimated_variance
            )
            p_value = 1 - NormalDist().cdf(statistic)
    p_float, a_float = tuple(map(float, predicted)), tuple(map(float, actual))
    return PredictionMetrics(
        mean_squared_error=sse / count,
        mean_absolute_error=sum(map(abs, errors), Decimal("0")) / count,
        r2_out_of_sample=1 - sse / benchmark_sse if benchmark_sse > 0 else None,
        pearson_ic=_finite(_correlation(p_float, a_float)),
        spearman_ic=_finite(_correlation(_ranks(p_float), _ranks(a_float))),
        direction_accuracy=Decimal(correct) / count,
        balanced_accuracy=sum(recalls, Decimal("0")) / len(recalls),
        macro_f1=sum(f1, Decimal("0")) / 3,
        matthews_correlation=Decimal(mcc_numerator) / mcc_denominator
        if mcc_denominator > 0
        else None,
        confusion_matrix=tuple(tuple(row) for row in matrix),  # type: ignore[arg-type]
        brier_score=brier,
        brier_scope=scope,
        calibration_error=calibration,
        abstention_coverage=Decimal(predicted_count[1]) / count,
        sign_test_statistic=_finite(statistic),
        sign_test_p_value=_finite(p_value),
        sign_test_observations=size,
        r2_benchmark="SUPPLIED_PAST_ONLY_FORECAST"
        if past_benchmark is not None
        else "UNAVAILABLE_UNLESS_SUPPLIED_FROM_PAST_DATA",
    )
