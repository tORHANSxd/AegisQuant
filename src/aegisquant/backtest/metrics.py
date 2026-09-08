"""Deterministic Decimal performance and execution metrics."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_CEILING, Decimal
from itertools import pairwise

from aegisquant.backtest.models import (
    BacktestFill,
    BacktestMetrics,
    BacktestOrderResult,
    EquityPoint,
    LiquidityRole,
    MultiLegExposure,
)
from aegisquant.domain.execution import VenueOrderStatus
from aegisquant.domain.values import canonical_result

SECONDS_PER_YEAR = Decimal("31557600")
BPS = Decimal("10000")


def resample_equity(
    points: tuple[EquityPoint, ...],
    frequency_seconds: int,
) -> tuple[EquityPoint, ...]:
    """Last available mark at a declared grid; never interpolate from future marks."""
    if frequency_seconds <= 0:
        raise ValueError("metric frequency must be positive")
    if not points:
        return ()
    ordered = tuple(
        {point.time: point for point in sorted(points, key=lambda point: point.time)}.values()
    )
    step = timedelta(seconds=frequency_seconds)
    at_time = ordered[0].time
    cursor = 0
    output: list[EquityPoint] = []
    while at_time <= ordered[-1].time:
        while cursor + 1 < len(ordered) and ordered[cursor + 1].time <= at_time:
            cursor += 1
        output.append(ordered[cursor].model_copy(update={"time": at_time}))
        at_time += step
    return tuple(output)


def _seconds(start: object, end: object) -> Decimal:
    from datetime import datetime

    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise TypeError("metric timestamps must be datetime")
    delta = end - start
    return Decimal(delta.days * 86_400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(
        "1000000"
    )


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else Decimal("0")


def _population_std(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    mean = _mean(values)
    variance = _mean([(value - mean) ** 2 for value in values])
    return variance.sqrt()


def _maximum_drawdown(points: tuple[EquityPoint, ...]) -> tuple[Decimal, int]:
    peak = points[0].equity
    maximum = Decimal("0")
    underwater_started = None
    longest_seconds = 0
    for point in points:
        if point.equity >= peak:
            peak = point.equity
            if underwater_started is not None:
                longest_seconds = max(
                    longest_seconds,
                    (point.time - underwater_started).days * 86_400
                    + (point.time - underwater_started).seconds,
                )
                underwater_started = None
            continue
        if underwater_started is None:
            underwater_started = point.time
        if peak > 0:
            maximum = max(maximum, canonical_result((peak - point.equity) / peak))
    if underwater_started is not None:
        longest_seconds = max(
            longest_seconds,
            (points[-1].time - underwater_started).days * 86_400
            + (points[-1].time - underwater_started).seconds,
        )
    return maximum, longest_seconds


def calculate_metrics(
    *,
    equity_curve: tuple[EquityPoint, ...],
    fills: tuple[BacktestFill, ...],
    orders: tuple[BacktestOrderResult, ...],
    multi_leg_exposures: tuple[MultiLegExposure, ...] = (),
    frequency_seconds: int = 3600,
    initial_equity: Decimal | None = None,
) -> BacktestMetrics:
    if not equity_curve:
        raise ValueError("metrics require an equity curve")
    initial = equity_curve[0].equity if initial_equity is None else initial_equity
    final = equity_curve[-1].equity
    regular_curve = resample_equity(equity_curve, frequency_seconds)
    total_return = Decimal("0") if initial == 0 else canonical_result(final / initial - 1)
    returns = [
        canonical_result(current.equity / previous.equity - 1)
        for previous, current in pairwise(regular_curve)
        if previous.equity != 0
    ]
    elapsed_seconds = max(Decimal("0"), _seconds(equity_curve[0].time, equity_curve[-1].time))
    periods_per_year = SECONDS_PER_YEAR / Decimal(frequency_seconds) if returns else Decimal("0")
    standard_deviation = _population_std(returns)
    annualized_volatility = canonical_result(
        standard_deviation * periods_per_year.sqrt() if periods_per_year > 0 else Decimal("0")
    )
    mean_return = _mean(returns)
    annualized_mean = canonical_result(mean_return * periods_per_year)
    sharpe = (
        canonical_result(annualized_mean / annualized_volatility)
        if annualized_volatility > 0
        else None
    )
    downside = [min(value, Decimal("0")) for value in returns]
    downside_std = _mean([value * value for value in downside]).sqrt()
    annualized_downside = canonical_result(
        downside_std * periods_per_year.sqrt() if periods_per_year > 0 else Decimal("0")
    )
    sortino = (
        canonical_result(annualized_mean / annualized_downside) if annualized_downside > 0 else None
    )
    annualized_return = None
    if initial > 0 and final > 0 and elapsed_seconds >= Decimal("86400"):
        years = elapsed_seconds / SECONDS_PER_YEAR
        annualized_return = canonical_result(((final / initial).ln() / years).exp() - 1)
    # Include the observed terminal mark for drawdown, without annualizing a partial bin.
    drawdown_curve = (
        regular_curve
        if regular_curve[-1].time == equity_curve[-1].time
        else (*regular_curve, equity_curve[-1])
    )
    maximum_drawdown, underwater_seconds = _maximum_drawdown(drawdown_curve)
    calmar = (
        canonical_result(annualized_return / maximum_drawdown)
        if annualized_return is not None and maximum_drawdown > 0
        else None
    )
    tail_count = (
        int((Decimal(len(returns)) * Decimal("0.05")).to_integral_value(rounding=ROUND_CEILING))
        if returns
        else 0
    )
    expected_shortfall = _mean(sorted(returns)[:tail_count]) if tail_count else Decimal("0")
    skewness = None
    excess_kurtosis = None
    if returns and standard_deviation > 0:
        centered = [value - mean_return for value in returns]
        skewness = canonical_result(_mean([value**3 for value in centered]) / standard_deviation**3)
        excess_kurtosis = canonical_result(
            _mean([value**4 for value in centered]) / standard_deviation**4 - Decimal("3")
        )
    positive = [value for value in returns if value > 0]
    negative = [value for value in returns if value < 0]
    hit_rate = (
        Decimal(len(positive)) / Decimal(len(positive) + len(negative))
        if positive or negative
        else Decimal("0")
    )
    payoff_ratio = (
        canonical_result(_mean(positive) / abs(_mean(negative))) if positive and negative else None
    )
    gross_turnover = sum(
        (fill.quantity.amount * fill.execution_price.amount for fill in fills),
        Decimal("0"),
    )
    average_equity = _mean([abs(point.equity) for point in drawdown_curve])
    turnover = (
        canonical_result(gross_turnover / average_equity) if average_equity > 0 else Decimal("0")
    )
    maker_count = sum(fill.liquidity_role is LiquidityRole.MAKER for fill in fills)
    maker_ratio = Decimal(maker_count) / Decimal(len(fills)) if fills else Decimal("0")
    requested = sum((order.order.quantity.amount for order in orders), Decimal("0"))
    executed = sum((fill.quantity.amount for fill in fills), Decimal("0"))
    fill_rate = min(Decimal("1"), executed / requested) if requested > 0 else Decimal("0")
    slippage_values = [
        abs(fill.execution_price.amount - fill.reference_price.amount)
        / fill.reference_price.amount
        * BPS
        for fill in fills
    ]
    average_slippage_bps = canonical_result(_mean(slippage_values))
    participation_values = [
        min(Decimal("1"), fill.quantity.amount / fill.available_liquidity)
        for fill in fills
        if fill.available_liquidity > 0
    ]
    participation_rate = canonical_result(_mean(participation_values))
    cancelled = sum(order.status is VenueOrderStatus.CANCELED for order in orders)
    cancel_rate = Decimal(cancelled) / Decimal(len(orders)) if orders else Decimal("0")
    average_latency_ns = _mean([Decimal(fill.latency_ns) for fill in fills])
    maximum_exposure = max(
        (item.exposed_notional for item in multi_leg_exposures), default=Decimal("0")
    )
    return BacktestMetrics(
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        maximum_drawdown=min(Decimal("1"), maximum_drawdown),
        expected_shortfall=expected_shortfall,
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
        underwater_seconds=underwater_seconds,
        hit_rate=hit_rate,
        payoff_ratio=payoff_ratio,
        turnover=turnover,
        maker_ratio=maker_ratio,
        fill_rate=fill_rate,
        average_slippage_bps=average_slippage_bps,
        participation_rate=participation_rate,
        cancel_rate=cancel_rate,
        average_latency_ns=average_latency_ns,
        maximum_multi_leg_exposure=maximum_exposure,
    )
