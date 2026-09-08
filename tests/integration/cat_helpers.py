from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aegisquant.backtest.models import BacktestRunSpec, BarEvent, EngineKind
from aegisquant.domain.identifiers import BacktestEventId, RunId, StrategyId, StrategyVersionId
from aegisquant.domain.values import Money
from aegisquant.research.strategies.cost_aware_trend import TrendFeatures, build_trend_features
from aegisquant.research.validation.cat_replay import BTC, INSTRUMENT, USDT, VENUE

ROOT = Path(__file__).resolve().parents[2]


def fixture() -> tuple[BacktestRunSpec, tuple[BarEvent, ...], TrendFeatures]:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    bars: list[BarEvent] = []
    for i in range(340):
        price = Decimal("100") + Decimal(i) / 10
        time = start + timedelta(hours=4 * i)
        bars.append(
            BarEvent(
                event_id=BacktestEventId(f"cat-test-{i}"),
                instrument_id=INSTRUMENT,
                venue_id=VENUE,
                base_asset_id=BTC,
                quote_asset_id=USDT,
                event_time=time,
                available_time=time + timedelta(hours=4, milliseconds=-1),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price + Decimal("0.02"),
                volume=Decimal("100000"),
            )
        )
    all_bars = tuple(bars)
    selected = all_bars[280:]
    spec = BacktestRunSpec(
        run_id=RunId("cat-integration"),
        engine_kind=EngineKind.EVENT,
        strategy_id=StrategyId("cat"),
        strategy_version_id=StrategyVersionId("cat-v1"),
        dataset_sha256="1" * 64,
        config_sha256="2" * 64,
        code_sha256="3" * 64,
        seed=1,
        reporting_asset_id=USDT,
        initial_cash=Money(amount=Decimal("10000"), asset_id=USDT),
        start_time=selected[0].event_time,
        end_time=selected[-1].available_time,
        created_at=start,
        accounting_policy_version="accounting-v1",
        cost_policy_version="cat-v1",
        rule_policy_version="cat-v1",
        reproduction_command="synthetic integration fixture",
        metric_frequency_seconds=14400,
    )
    return spec, selected, build_trend_features(all_bars)
