from decimal import Decimal

from aegisquant.research.models.baselines import ResearchModality, evaluate_predictions
from aegisquant.research.return_evaluation import evaluate_return_path
from tests.unit.research.test_no_zero_threshold_default import NOW, calibration, prediction


def test_compounding_and_full_terminal_exit_cost() -> None:
    cost = Decimal("0.001")
    result = evaluate_predictions(
        predictions=prediction(("0.1", "0.1")),
        modality=ResearchModality.MARKET_ONLY,
        realized_returns=(Decimal("0.1"), Decimal("-0.1")),
        cost_rates=(cost, cost),
        calibration=calibration(),
        evaluation_start=NOW,
        frequency_seconds=86400,
    )
    expected = Decimal("1.1") * Decimal("0.9") / (1 + cost) * (1 - cost)
    assert result.gross_return == Decimal("-0.01")
    assert abs(result.net_return - (expected - 1)) < Decimal("1e-25")
    assert result.account.forced_close_equity < result.account.final_mtm_equity
    assert result.account.account_metrics.trade_statistics.closed_trade_count == 1
    assert result.account.account_metrics.trade_statistics.win_rate == 0
    assert abs(result.account.cost_identity_residual) < Decimal("1e-25")


def test_reversal_pays_both_legs_and_trades_are_flat_to_flat() -> None:
    result = evaluate_return_path(
        positions=(Decimal("1"), Decimal("-1")),
        realized_returns=(Decimal("0"), Decimal("0")),
        one_way_cost_rates=(Decimal("0.01"),) * 2,
        start=NOW,
        frequency_seconds=3600,
    )
    assert result.net_return < Decimal("-0.039")
    assert result.account_metrics.trade_statistics.reversal_count == 1
    assert result.account_metrics.trade_statistics.closed_trade_count == 2
    assert result.account_metrics.trade_statistics.win_rate == 0
    assert abs(
        sum((t.net_pnl for t in result.closed_trades), Decimal("0")) - result.net_return
    ) < Decimal("1e-25")


def test_more_costs_reduce_fixed_path_net_equity() -> None:
    equities = [
        evaluate_return_path(
            positions=(Decimal("-1"), Decimal("1"), Decimal("0")),
            realized_returns=(Decimal("-0.05"), Decimal("0.04"), Decimal("-0.02")),
            one_way_cost_rates=(Decimal(cost),) * 3,
            start=NOW,
            frequency_seconds=3600,
        ).forced_close_equity
        for cost in ("0", "0.001", "0.002")
    ]
    assert equities[0] > equities[1] > equities[2]
