from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.features import (
    MarketFeatureCalculator,
    MarketFeatureConfig,
    MarketObservation,
    assert_batch_incremental_parity,
    cross_sectional_rank,
    market_feature_definitions,
    values_by_key,
)

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)


def observations() -> tuple[MarketObservation, ...]:
    closes = ("100", "101", "99", "102", "104")
    return tuple(
        MarketObservation(
            instrument_id="BINANCE:SPOT:BTCUSDT",
            event_time=NOW + timedelta(minutes=index),
            available_time=NOW + timedelta(minutes=index, seconds=2),
            close=Decimal(close),
            high=Decimal(close) + Decimal("1"),
            low=Decimal(close) - Decimal("1"),
            quote_volume=Decimal("1000"),
            bid=Decimal(close) - Decimal("0.1"),
            ask=Decimal(close) + Decimal("0.1"),
            funding_rate=Decimal(index) / Decimal("10000"),
            spot_price=Decimal(close),
            perpetual_price=Decimal(close) + Decimal("0.5"),
            source_dataset_id="market-v1",
        )
        for index, close in enumerate(closes)
    )


def test_market_features_have_golden_economics_and_batch_incremental_parity() -> None:
    config = MarketFeatureConfig()
    vectors = assert_batch_incremental_parity(observations(), config)
    assert len(vectors) == 5
    values = values_by_key(vectors[-1])
    definitions = {
        item.feature_id: item.qualified_id for item in market_feature_definitions(config)
    }
    assert values[definitions["trend.return"]] == Decimal("0.050505050505050505050505051")
    assert values[definitions["derivatives.funding_change"]] == Decimal("0.0001")
    assert values[definitions["derivatives.basis"]] == Decimal("0.004807692307692307692307692")
    expected_spread = Decimal("0.2") / Decimal("104") * Decimal("10000")
    assert values[definitions["liquidity.spread_bps"]] == pytest.approx(expected_spread)
    assert vectors[0].missing_flags
    assert not vectors[-1].missing_flags


def test_incremental_rejects_non_monotonic_availability() -> None:
    calculator = MarketFeatureCalculator(MarketFeatureConfig())
    first = observations()[0]
    calculator.update(first)
    with pytest.raises(ValueError, match="increasing available_time"):
        calculator.update(first)


def test_cross_sectional_rank_is_point_in_time_and_tie_stable() -> None:
    definition = next(
        item
        for item in market_feature_definitions(MarketFeatureConfig())
        if item.feature_id == "cross_section.rank"
    )
    vectors = cross_sectional_rank(
        as_of_time=NOW,
        signals={"BTC": Decimal("2"), "ETH": Decimal("1"), "SOL": Decimal("2")},
        source_dataset_ids=("cross-v1",),
        definition=definition,
    )
    values = {item.entity_id: item.values[0].value for item in vectors}
    assert values == {"BTC": Decimal("1"), "ETH": Decimal("0"), "SOL": Decimal("1")}
