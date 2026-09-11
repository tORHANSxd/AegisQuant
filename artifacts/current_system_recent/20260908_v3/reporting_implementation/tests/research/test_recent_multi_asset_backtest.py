"""Recent-data boundaries and accounting guards must reject misleading results."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from scripts.report_recent_multi_asset_backtest import period_slices
from scripts.run_recent_multi_asset_backtest import completed_cutoff, validate_result
from tests.alpha_v4.test_r4_contracts import run_case


@pytest.mark.parametrize("hour, expected", [(0, 0), (3, 0), (4, 4), (14, 12), (23, 20)])
def test_only_closed_four_hour_buckets_are_available(hour: int, expected: int):
    time = datetime(2026, 9, 8, hour, 59, 59, 999000, tzinfo=UTC)
    assert completed_cutoff(int(time.timestamp() * 1000)) == datetime(
        2026, 9, 8, expected, tzinfo=UTC
    )


def test_exact_close_boundary_includes_just_completed_bucket():
    time = datetime(2026, 9, 8, 12, tzinfo=UTC)
    millis = int(time.timestamp() * 1000)
    assert completed_cutoff(millis) == time
    assert completed_cutoff(millis - 1) == time - timedelta(hours=4)


def test_monthly_slices_preserve_funded_capital_and_compound():
    start = datetime(2026, 3, 31, 20, tzinfo=UTC)
    end = datetime(2026, 4, 1, 8, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "time": [start + timedelta(hours=4 * i) for i in range(4)],
            "equity": [10000.0, 11000.0, 10500.0, 12100.0],
            "position_value": [0.0] * 4,
        }
    )
    rows = period_slices(frame, start, end)
    assert rows[0]["end_equity"] == rows[1]["start_equity"] == 11000
    compounded = (1 + rows[0]["net_compound_return"]) * (1 + rows[1]["net_compound_return"])
    assert compounded == pytest.approx(1.21)
    assert all(row["partial_month"] for row in rows)


def test_accounting_guard_rejects_unliquidated_and_future_execution_results():
    result, _ = run_case(buffered=True)
    end = max(p.time for p in result.equity_curve) + timedelta(hours=4)
    validate_result(result, end)
    bad_position = result.positions[-1].model_copy(update={"quantity": Decimal("1")})
    broken = result.model_copy(update={"positions": (*result.positions[:-1], bad_position)})
    with pytest.raises(ValueError, match="terminal position"):
        validate_result(broken, end)
    with pytest.raises(ValueError, match="unavailable price"):
        validate_result(result, result.fills[-1].event_time)
    broken = result.model_copy(update={"cost_identity_residual": Decimal("0.01")})
    with pytest.raises(ValueError, match="cost identity"):
        validate_result(broken, end)
