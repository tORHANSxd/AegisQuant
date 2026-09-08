from decimal import Decimal

from aegisquant.backtest.models import BacktestOrder, BacktestResult
from aegisquant.research.validation.cat_replay import replay_cat
from tests.integration.cat_helpers import ROOT, fixture


def test_fixed_orders_cost_stress_preserves_fill_path_and_decreases_net_equity() -> None:
    spec, bars, features = fixture()

    def replay(multiplier: str, orders: tuple[BacktestOrder, ...] | None = None) -> BacktestResult:
        result, _ = replay_cat(
            root=ROOT,
            spec=spec,
            bars=bars,
            features=features,
            feature_indices={time: i for i, time in enumerate(features.available_times)},
            trend_by_time={b.available_time: True for b in bars},
            forecasts={},
            level="B3",
            cost_multiplier=Decimal(multiplier),
            fixed_orders=orders,
        )
        return result

    base = replay("1")
    equities: list[Decimal] = []
    for multiplier in ("0", "0.5", "1", "1.5", "2"):
        result = replay(multiplier, tuple(row.order for row in base.orders))
        assert [(f.event_time, f.quantity) for f in result.fills] == [
            (f.event_time, f.quantity) for f in base.fills
        ]
        assert abs(result.cost_identity_residual) < result.cost_identity_tolerance
        assert result.forced_close_final_equity is not None
        equities.append(result.forced_close_final_equity)
    assert equities == sorted(equities, reverse=True)
    assert equities[0] > equities[-1]
