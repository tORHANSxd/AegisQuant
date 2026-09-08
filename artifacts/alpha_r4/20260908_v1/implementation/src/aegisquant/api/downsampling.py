"""Deterministic extrema-preserving server-side downsampling."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from math import ceil

from aegisquant.readmodels.models import CandlePoint, TimeValuePoint


def downsample_extrema[T](
    items: Sequence[T],
    *,
    max_points: int,
    low: Callable[[T], Decimal],
    high: Callable[[T], Decimal],
    protected_indices: frozenset[int] = frozenset(),
) -> tuple[T, ...]:
    """Keep boundaries, protected events, and bucket extrema in source order."""
    if max_points < 4:
        raise ValueError("AQ-API-DOWNSAMPLE-LIMIT")
    if len(items) <= max_points:
        return tuple(items)
    mandatory = {0, len(items) - 1, *protected_indices}
    if any(index < 0 or index >= len(items) for index in mandatory):
        raise ValueError("AQ-API-DOWNSAMPLE-PROTECTED-INDEX")
    if len(mandatory) > max_points:
        raise ValueError("AQ-API-DOWNSAMPLE-PROTECTED-OVERFLOW")

    candidates = [index for index in range(1, len(items) - 1) if index not in mandatory]
    remaining = max_points - len(mandatory)
    if remaining:
        bucket_count = max(1, remaining // 2)
        bucket_size = max(1, ceil(len(candidates) / bucket_count))
        extrema: list[int] = []
        for offset in range(0, len(candidates), bucket_size):
            bucket = candidates[offset : offset + bucket_size]
            if not bucket:
                continue
            extrema.extend(
                (
                    min(bucket, key=lambda index: low(items[index])),
                    max(bucket, key=lambda index: high(items[index])),
                )
            )
        for index in extrema:
            if len(mandatory) >= max_points:
                break
            mandatory.add(index)

    if len(mandatory) < max_points:
        for index in candidates:
            if len(mandatory) >= max_points:
                break
            mandatory.add(index)
    return tuple(items[index] for index in sorted(mandatory))


def downsample_time_values(
    points: Sequence[TimeValuePoint],
    *,
    max_points: int,
    protected_indices: frozenset[int] = frozenset(),
) -> tuple[TimeValuePoint, ...]:
    return downsample_extrema(
        points,
        max_points=max_points,
        low=lambda point: point.value,
        high=lambda point: point.value,
        protected_indices=protected_indices,
    )


def downsample_candles(
    candles: Sequence[CandlePoint],
    *,
    max_points: int,
    protected_indices: frozenset[int] = frozenset(),
) -> tuple[CandlePoint, ...]:
    return downsample_extrema(
        candles,
        max_points=max_points,
        low=lambda candle: candle.low,
        high=lambda candle: candle.high,
        protected_indices=protected_indices,
    )
