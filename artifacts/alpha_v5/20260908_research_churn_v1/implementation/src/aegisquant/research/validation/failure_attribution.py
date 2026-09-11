"""Frozen-signal attribution on funded long/flat NAV, with no fitting capability."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class LongFlatPath:
    equity: FloatArray
    gross_equity: FloatArray
    cash_costs: FloatArray
    turnover_notional: FloatArray
    transition_units: FloatArray
    final_mtm: float
    forced_exit_cost: float
    trade_returns: tuple[float, ...]
    gross_trade_pnl: tuple[float, ...]
    holding_bars: tuple[int, ...]


def long_flat_path(returns: FloatArray, weights: FloatArray, cost: float) -> LongFlatPath:
    """Fast statistical replica of the Decimal self-financing 0/1 return screen.

    Arrays include every declared clock period; missing quotes must already have
    a last-known mark and unchanged target. Costs are a declared all-in proxy.
    This cannot prove liquidity, financing or an actual executable order size.
    """
    if len(returns) != len(weights) or not len(returns):
        raise ValueError("long/flat attribution requires aligned nonempty arrays")
    if not np.all(np.isfinite(returns)) or np.any(returns <= -1):
        raise ValueError("invalid underlying returns")
    if not np.all(np.isin(weights, (0.0, 1.0))) or not 0 <= cost < 1:
        raise ValueError("long/flat weights and cost are invalid")
    previous: FloatArray = np.r_[0.0, weights[:-1]]
    entries, exits = (weights > previous), (weights < previous)
    factors: FloatArray = (
        (1 + weights * returns)
        * np.where(entries, 1 / (1 + cost), 1)
        * np.where(exits, 1 - cost, 1)
    )
    equity: FloatArray = np.cumprod(factors)
    before: FloatArray = np.r_[1.0, equity[:-1]]
    traded = np.where(entries, before / (1 + cost), 0) + np.where(exits, before, 0)
    cash_costs = traded * cost
    final_mtm = float(equity[-1])
    terminal = final_mtm * cost if weights[-1] else 0.0
    equity[-1] -= terminal
    traded[-1] += final_mtm if weights[-1] else 0
    cash_costs[-1] += terminal
    units = np.abs(weights - previous)
    units[-1] += weights[-1]
    profit: FloatArray = before * np.where(entries, 1 / (1 + cost), 1) * weights * returns
    opened = np.flatnonzero(entries)
    ended = [int(v) for v in np.flatnonzero(exits)]
    if weights[-1]:
        ended.append(len(weights))
    net_trades: list[float] = []
    gross_trades: list[float] = []
    holding: list[int] = []
    for enter, leave in zip(opened, ended, strict=True):
        starting = float(before[enter])
        final = float(equity[-1]) if leave == len(weights) else float(before[leave] * (1 - cost))
        net_trades.append(final - starting)
        gross_trades.append(float(np.sum(profit[enter:leave])))
        holding.append(int(leave - enter))
    residual = float(equity[-1] - 1 - (np.sum(profit) - np.sum(cash_costs)))
    if abs(residual) > 1e-10:
        raise ValueError("funded NAV cost identity failed")
    return LongFlatPath(
        equity,
        np.cumprod(1 + weights * returns),
        cash_costs,
        traded,
        units,
        final_mtm,
        terminal,
        tuple(net_trades),
        tuple(gross_trades),
        tuple(holding),
    )


def path_summary(
    paths: tuple[LongFlatPath, ...], *, frequency_seconds: int = 3600
) -> dict[str, float | int | None]:
    # Each account receives equal initial capital; no uncharged cross-asset rebalancing.
    nav: FloatArray = np.mean(np.stack([p.equity for p in paths]), axis=0)
    gross: FloatArray = np.mean(np.stack([p.gross_equity for p in paths]), axis=0)
    changes: FloatArray = np.diff(np.r_[1.0, nav]) / np.r_[1.0, nav[:-1]]
    periods = 31557600 / frequency_seconds
    deviation = float(np.std(changes))
    downside = math.sqrt(float(np.mean(np.minimum(changes, 0) ** 2)))
    mean = float(np.mean(changes))
    peak: FloatArray = np.maximum.accumulate(np.r_[1.0, nav])
    drawdowns: FloatArray = 1 - np.r_[1.0, nav] / peak
    drawdown = float(np.max(drawdowns))
    cagr = float(nav[-1] ** (periods / len(nav)) - 1)
    trades = [value / len(paths) for p in paths for value in p.trade_returns]
    wins, losses = [v for v in trades if v > 0], [-v for v in trades if v < 0]
    cash_cost = sum(float(np.sum(p.cash_costs)) for p in paths) / len(paths)
    gross_profit = sum(sum(max(v, 0) for v in p.gross_trade_pnl) for p in paths) / len(paths)
    return {
        "observations": len(nav),
        "gross_compound_return": float(gross[-1] - 1),
        "net_compound_return": float(nav[-1] - 1),
        "final_mtm_equity": sum(p.final_mtm for p in paths) / len(paths),
        "forced_close_equity": float(nav[-1]),
        "forced_close_cost": sum(p.forced_exit_cost for p in paths) / len(paths),
        "cash_cost_paid": cash_cost,
        "cost_drag": float(gross[-1] - nav[-1]),
        "maximum_drawdown": drawdown,
        "cagr": cagr,
        "sharpe": mean / deviation * math.sqrt(periods) if deviation else None,
        "sortino": mean / downside * math.sqrt(periods) if downside else None,
        "calmar": cagr / drawdown if drawdown else None,
        "cvar_5pct": float(np.mean(np.sort(changes)[: max(1, math.ceil(len(changes) * 0.05))])),
        "turnover_units": sum(float(np.sum(p.transition_units)) for p in paths) / len(paths),
        "turnover_notional_initial_nav": sum(float(np.sum(p.turnover_notional)) for p in paths)
        / len(paths),
        "closed_trade_count": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "average_win": float(np.mean(wins)) if wins else 0.0,
        "average_loss": float(np.mean(losses)) if losses else 0.0,
        "payoff_ratio": float(np.mean(wins) / np.mean(losses)) if wins and losses else None,
        "expectancy": float(np.mean(trades)) if trades else 0.0,
        "average_holding_hours": float(np.mean([n for p in paths for n in p.holding_bars]))
        * frequency_seconds
        / 3600
        if trades
        else 0.0,
        "cost_to_gross_profit_ratio": cash_cost / gross_profit if gross_profit > 0 else None,
    }


def matched_random_offsets(
    weights: tuple[FloatArray, ...], *, count: int, seed: int
) -> tuple[int, ...]:
    """Circular shifts cut only in flat regions, preserving complete holding runs.

    All assets use the same shift to retain contemporaneous exposure overlap.
    Exact match is in position-transition units and holding bars, not cash turnover.
    """
    if not weights or any(len(w) != len(weights[0]) for w in weights):
        raise ValueError("random baseline requires aligned weights")
    if any(w[0] != 0 or w[-1] != 0 for w in weights):
        raise ValueError("random baseline requires flat endpoints")
    flat = np.all(np.stack([w == 0 for w in weights]), axis=0)
    eligible = np.flatnonzero(flat & np.roll(flat, 1))
    eligible = eligible[eligible != 0]
    if len(eligible) < count:
        raise ValueError("insufficient distinct matched random shifts")
    return tuple(int(v) for v in np.random.default_rng(seed).choice(eligible, count, replace=False))
