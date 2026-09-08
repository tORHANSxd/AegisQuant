from decimal import Decimal

from aegisquant.domain.execution import OrderSide
from aegisquant.research.models.economic_gate import CalibrationStatus, EconomicForecast
from aegisquant.research.validation.cat_replay import replay_cat
from tests.integration.cat_helpers import ROOT, fixture


def test_completed_features_gate_quantity_next_open_ledger_and_terminal_exit() -> None:
    spec, bars, features = fixture()
    forecast = {
        b.available_time: EconomicForecast(
            expected_gross_return=Decimal("0.1"),
            q10_return=Decimal("0.08"),
            q50_return=Decimal("0.1"),
            q90_return=Decimal("0.12"),
            p_net_positive=Decimal("0.8"),
            prediction_uncertainty=Decimal("0.02"),
            available_time=b.available_time,
            calibration_status=CalibrationStatus.VALIDATION_CALIBRATED,
            calibrated_through=features.available_times[270],
            calibration_sha256="a" * 64,
        )
        for b in bars
    }
    result, decisions = replay_cat(
        root=ROOT,
        spec=spec,
        bars=bars,
        features=features,
        feature_indices={time: i for i, time in enumerate(features.available_times)},
        trend_by_time={b.available_time: True for b in bars},
        forecasts=forecast,
        level="B6",
    )
    assert len(result.fills) == 2
    assert result.fills[0].side is OrderSide.BUY
    assert result.fills[0].event_time == bars[1].event_time
    assert result.fills[0].quantity.amount == Decimal("77.331666")
    assert result.fills[-1].side is OrderSide.SELL
    assert result.positions[-1].quantity == 0
    assert abs(result.cost_identity_residual) < result.cost_identity_tolerance
    assert result.metrics.trade_statistics.closed_trade_count == 1
    assert all(Decimal(row["cash"]) >= 0 for row in decisions)
    assert len(decisions) == len(bars)
    assert result.forced_close_final_equity == result.mark_to_market_final_equity
