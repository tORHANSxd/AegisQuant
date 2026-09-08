from datetime import UTC, datetime
from decimal import Decimal

import numpy as np

from aegisquant.research.return_evaluation import evaluate_return_path
from aegisquant.research.validation.failure_attribution import (
    long_flat_path,
    matched_random_offsets,
)
from aegisquant.research.validation.public_market_backtest import return_path


def test_identical_frozen_signal_measures_cost_timing_without_retraining() -> None:
    returns = np.asarray([0.1, -0.1, 0.05, 0.02], dtype=np.float64)
    signal = np.asarray([1.0, 1.0, 0.0, 1.0], dtype=np.float64)
    old = return_path(returns, signal, 0.0013)
    fixed = long_flat_path(returns, signal, 0.0013)
    decimal = evaluate_return_path(
        positions=tuple(Decimal(str(v)) for v in signal),
        realized_returns=tuple(Decimal(str(v)) for v in returns),
        one_way_cost_rates=(Decimal("0.0013"),) * 4,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        frequency_seconds=3600,
    )
    assert abs(fixed.equity[-1] - float(decimal.forced_close_equity)) < 1e-12
    assert abs(sum(fixed.cash_costs) - float(decimal.cash_cost_paid)) < 1e-12
    assert abs(fixed.equity[-1] - np.prod(1 + old.net)) > 1e-6
    assert signal.tolist() == [1, 1, 0, 1]


def test_random_shifts_preserve_complete_holding_durations_and_transition_units() -> None:
    signal = np.asarray([0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0], dtype=np.float64)
    original = long_flat_path(np.zeros(len(signal)), signal, 0.001)
    for offset in matched_random_offsets((signal,), count=4, seed=42):
        random = long_flat_path(np.zeros(len(signal)), np.roll(signal, -offset), 0.001)
        assert sorted(random.holding_bars) == sorted(original.holding_bars)
        assert np.sum(random.transition_units) == np.sum(original.transition_units)
