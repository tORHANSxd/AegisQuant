"""Aggregate separately funded research accounts without implicit rebalancing."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from itertools import pairwise

from aegisquant.backtest.models import EquityPoint


def combine_independent_sleeves(
    curves: Mapping[str, tuple[EquityPoint, ...]],
) -> tuple[EquityPoint, ...]:
    """Sum cash and marked holdings on an already aligned, causal reporting clock."""
    if not curves or any(len(curve) < 2 for curve in curves.values()):
        raise ValueError("at least one complete sleeve curve is required")
    first = next(iter(curves.values()))
    clock = tuple(point.time for point in first)
    if any(left >= right for left, right in pairwise(clock)):
        raise ValueError("sleeve reporting clock must be strictly increasing")
    asset = first[0].reporting_asset_id
    for curve in curves.values():
        if tuple(point.time for point in curve) != clock:
            raise ValueError("sleeves must share the complete reporting clock")
        if any(point.reporting_asset_id != asset or point.equity <= 0 for point in curve):
            raise ValueError("sleeves require positive equity in a common reporting asset")
    result: list[EquityPoint] = []
    for index, time in enumerate(clock):
        points = [curve[index] for curve in curves.values()]
        cash = sum((point.cash for point in points), Decimal("0"))
        position = sum((point.position_value for point in points), Decimal("0"))
        result.append(
            EquityPoint(
                time=time,
                cash=cash,
                position_value=position,
                equity=cash + position,
                realized_pnl=sum((p.realized_pnl for p in points), Decimal("0")),
                unrealized_pnl=sum((p.unrealized_pnl for p in points), Decimal("0")),
                reporting_asset_id=asset,
            )
        )
    return tuple(result)
