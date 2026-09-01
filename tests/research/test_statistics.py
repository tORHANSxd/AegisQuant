from __future__ import annotations

import math
from decimal import Decimal
from statistics import NormalDist

import pytest

from aegisquant.research.validation import (
    benjamini_hochberg,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
)


def test_psr_matches_independent_reference_formula() -> None:
    result = probabilistic_sharpe_ratio(
        observed_sharpe=Decimal("1.2"),
        benchmark_sharpe=Decimal("0.4"),
        observations=100,
        skewness=Decimal("0.2"),
        kurtosis=Decimal("3.4"),
    )
    denominator = math.sqrt(1 - 0.2 * 1.2 + ((3.4 - 1) / 4) * 1.2**2)
    expected = NormalDist().cdf((1.2 - 0.4) * math.sqrt(99) / denominator)
    assert float(result.probability) == pytest.approx(expected, abs=1e-14)


def test_dsr_deflates_for_multiple_trials() -> None:
    psr = probabilistic_sharpe_ratio(
        observed_sharpe=Decimal("1"),
        benchmark_sharpe=Decimal("0"),
        observations=30,
        skewness=Decimal("0"),
        kurtosis=Decimal("3"),
    )
    dsr = deflated_sharpe_ratio(
        observed_sharpe=Decimal("1"),
        observations=30,
        skewness=Decimal("0"),
        kurtosis=Decimal("3"),
        trial_sharpes=(Decimal("0.1"), Decimal("0.4"), Decimal("0.8"), Decimal("1")),
    )
    assert dsr.benchmark_sharpe > 0
    assert dsr.probability < psr.probability


def test_pbo_and_benjamini_hochberg_are_auditable() -> None:
    matrix = (
        (Decimal("0.10"), Decimal("0.02"), Decimal("-0.01")),
        (Decimal("0.09"), Decimal("0.03"), Decimal("0.00")),
        (Decimal("-0.05"), Decimal("0.04"), Decimal("0.03")),
        (Decimal("-0.04"), Decimal("0.05"), Decimal("0.02")),
    )
    pbo = probability_of_backtest_overfitting(matrix)
    assert pbo.combinations == 6
    assert Decimal("0") <= pbo.probability <= Decimal("1")
    assert len(pbo.logits) == 6

    fdr = benjamini_hochberg(
        {"a": Decimal("0.01"), "b": Decimal("0.04"), "c": Decimal("0.03")},
        alpha=Decimal("0.05"),
    )
    adjusted = {item.hypothesis_id: item.adjusted_p_value for item in fdr.results}
    assert adjusted == {"a": Decimal("0.03"), "c": Decimal("0.04"), "b": Decimal("0.04")}
    assert all(item.rejected for item in fdr.results)


def test_statistics_reject_degenerate_inputs() -> None:
    with pytest.raises(ValueError, match="at least four"):
        probability_of_backtest_overfitting(((Decimal("1"), Decimal("0")),) * 3)
    with pytest.raises(ValueError, match="alpha"):
        benjamini_hochberg({"a": Decimal("0.1")}, alpha=Decimal("1"))
