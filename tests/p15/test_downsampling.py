"""Server-side downsampling keeps boundaries, events, and extrema."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.api.downsampling import downsample_candles, downsample_time_values
from aegisquant.readmodels.models import CandlePoint, TimeValuePoint


def test_time_value_downsampling_preserves_boundaries_event_and_global_extrema() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = tuple(
        TimeValuePoint(time=start + timedelta(seconds=index), value=Decimal(index % 37))
        for index in range(100_000)
    )
    points = (
        *points[:12_345],
        TimeValuePoint(time=points[12_345].time, value=Decimal("-999")),
        *points[12_346:87_654],
        TimeValuePoint(time=points[87_654].time, value=Decimal("999")),
        *points[87_655:],
    )
    sampled = downsample_time_values(points, max_points=200, protected_indices=frozenset({50_000}))
    assert len(sampled) <= 200
    assert sampled[0] == points[0] and sampled[-1] == points[-1]
    assert points[50_000] in sampled
    assert min(item.value for item in sampled) == Decimal("-999")
    assert max(item.value for item in sampled) == Decimal("999")


def test_candle_downsampling_preserves_high_and_low() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = tuple(
        CandlePoint(
            time=start + timedelta(minutes=index),
            open=Decimal("100"),
            high=Decimal("100") + Decimal(index % 19),
            low=Decimal("100") - Decimal(index % 17),
            close=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(10_000)
    )
    sampled = downsample_candles(candles, max_points=128)
    assert len(sampled) <= 128
    assert max(item.high for item in sampled) == max(item.high for item in candles)
    assert min(item.low for item in sampled) == min(item.low for item in candles)


def test_downsampling_rejects_unsafe_limits() -> None:
    with pytest.raises(ValueError, match="AQ-API-DOWNSAMPLE-LIMIT"):
        downsample_time_values((), max_points=3)
