"""Self-financing normalized return screening; not an exchange fill simulator."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from aegisquant.backtest.metrics import calculate_metrics
from aegisquant.backtest.models import BacktestMetrics, ClosedTrade, EquityPoint
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import AssetId
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, canonical_result


class ReturnEvaluation(DomainModel):
    scope: str = "NORMALIZED_SIGNAL_SCREEN_NOT_EXECUTION_PROOF"
    gross_return: FiniteDecimal
    net_return: FiniteDecimal
    cost_drag: FiniteDecimal
    cash_cost_paid: NonNegativeDecimal
    gross_pnl_on_net_capital: FiniteDecimal
    cost_identity_residual: FiniteDecimal
    final_mtm_equity: FiniteDecimal
    forced_close_equity: FiniteDecimal
    forced_close_cost: NonNegativeDecimal
    turnover: NonNegativeDecimal
    bankrupt: bool
    equity_curve: tuple[EquityPoint, ...]
    closed_trades: tuple[ClosedTrade, ...]
    account_metrics: BacktestMetrics


def evaluate_return_path(
    *,
    positions: tuple[Decimal, ...],
    realized_returns: tuple[Decimal, ...],
    one_way_cost_rates: tuple[Decimal, ...],
    start: datetime,
    frequency_seconds: int,
) -> ReturnEvaluation:
    count = len(positions)
    if not count or len(realized_returns) != count or len(one_way_cost_rates) != count:
        raise ValueError("return evaluation dimensions differ")
    if frequency_seconds <= 0 or start.tzinfo is None:
        raise ValueError("return evaluation requires UTC time and fixed positive frequency")
    if any(not v.is_finite() or abs(v) > 1 for v in positions):
        raise ValueError("normalized positions must be finite and no larger than 1x")
    if any(not v.is_finite() or v <= -1 for v in realized_returns):
        raise ValueError("underlying returns must exceed -100%")
    if any(not c.is_finite() or c < 0 or c >= 1 for c in one_way_cost_rates):
        raise ValueError("one-way cost rates must lie in [0, 1)")
    equity = gross_equity = Decimal("1")
    exposure = costs = gross_pnl = turnover = Decimal("0")
    previous_weight = Decimal("0")
    opened_equity = opened_gross = Decimal("0")
    opened_at = start
    reversals = 0
    closed: list[ClosedTrade] = []
    points: list[EquityPoint] = []
    step = timedelta(seconds=frequency_seconds)

    def point(at: datetime) -> EquityPoint:
        # Capital one is a reporting normalization, never an actual cash balance.
        return EquityPoint(
            time=at,
            cash=equity,
            position_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            equity=equity,
            reporting_asset_id=AssetId("NAV"),
        )

    def close_trade(at: datetime) -> None:
        closed.append(
            ClosedTrade(
                opened_at=opened_at,
                closed_at=at,
                side=OrderSide.BUY if previous_weight > 0 else OrderSide.SELL,
                gross_pnl=canonical_result(gross_pnl - opened_gross),
                net_pnl=canonical_result(equity - opened_equity),
                holding_seconds=Decimal(str((at - opened_at).total_seconds())),
            )
        )

    points.append(point(start))
    for index, (weight, realized, cost) in enumerate(
        zip(positions, realized_returns, one_way_cost_rates, strict=True)
    ):
        at = start + index * step
        if previous_weight != 0 and previous_weight * weight <= 0:
            exit_cost = abs(exposure) * cost
            turnover += abs(exposure)
            equity -= exit_cost
            costs += exit_cost
            exposure = Decimal("0")
            close_trade(at)
            if weight != 0:
                reversals += 1
        if weight != 0 and previous_weight * weight <= 0:
            opened_equity, opened_gross, opened_at = equity, gross_pnl, at
        # Solve the target against equity AFTER paying this rebalance's cost.
        difference = weight * equity - exposure
        direction = Decimal("1") if difference >= 0 else Decimal("-1")
        delta = difference / (1 + weight * cost * direction)
        cash_cost = abs(delta) * cost
        turnover += abs(delta)
        costs += cash_cost
        equity -= cash_cost
        exposure += delta
        profit = exposure * realized
        equity += profit
        gross_pnl += profit
        exposure *= 1 + realized
        gross_equity *= 1 + weight * realized
        previous_weight = weight
        if equity <= 0:
            raise ValueError("normalized screen is insolvent; use the margin-aware event engine")
        points.append(point(at + step))
    mtm = equity
    exit_cost = abs(exposure) * one_way_cost_rates[-1]
    if exposure:
        equity -= exit_cost
        costs += exit_cost
        turnover += abs(exposure)
        close_trade(start + count * step)
    if equity <= 0:
        raise ValueError("normalized exit is insolvent; use the margin-aware event engine")
    points[-1] = point(start + count * step)
    gross_profit = sum((max(t.gross_pnl, Decimal("0")) for t in closed), Decimal("0"))
    account = calculate_metrics(
        equity_curve=tuple(points),
        fills=(),
        orders=(),
        initial_equity=Decimal("1"),
        frequency_seconds=frequency_seconds,
        closed_trades=tuple(closed),
        reversal_count=reversals,
    )
    account = account.model_copy(
        update={
            "turnover": turnover,
            "cost_to_gross_profit_ratio": costs / gross_profit if gross_profit > 0 else None,
        }
    )
    return ReturnEvaluation(
        gross_return=canonical_result(gross_equity - 1),
        net_return=canonical_result(equity - 1),
        cost_drag=canonical_result(gross_equity - equity),
        cash_cost_paid=canonical_result(costs),
        gross_pnl_on_net_capital=canonical_result(gross_pnl),
        cost_identity_residual=canonical_result(equity - 1 - (gross_pnl - costs)),
        final_mtm_equity=canonical_result(mtm),
        forced_close_equity=canonical_result(equity),
        forced_close_cost=canonical_result(exit_cost),
        turnover=canonical_result(turnover),
        bankrupt=False,
        equity_curve=tuple(points),
        closed_trades=tuple(closed),
        account_metrics=account,
    )
