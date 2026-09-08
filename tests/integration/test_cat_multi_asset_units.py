from decimal import Decimal

import pytest

from aegisquant.domain.identifiers import AssetId
from aegisquant.research.validation.cat_replay import CatMarket, replay_cat
from tests.integration.cat_helpers import ROOT, fixture


def test_default_btc_replay_preserves_frozen_pre_expansion_result() -> None:
    spec, bars, features = fixture()
    result, _ = replay_cat(
        root=ROOT,
        spec=spec,
        bars=bars,
        features=features,
        feature_indices={time: i for i, time in enumerate(features.available_times)},
        trend_by_time={bar.available_time: True for bar in bars},
        forecasts={},
        level="B3",
    )
    # Captured from commit 1e1a2e6 before introducing per-asset market specifications.
    assert (
        result.economic_event_hash
        == "90803b88eb97f6b0534a2ddeb7cd33e07e92fc8d32e31c3d746077d8798c4a61"
    )
    assert result.forced_close_final_equity == Decimal("10417.02425998389978027438270")


@pytest.mark.parametrize(("asset", "step"), [("ETH", "0.0001"), ("SOL", "0.001"), ("XRP", "0.1")])
def test_asset_units_precision_and_cash_identity_survive_replay(asset: str, step: str) -> None:
    spec, bars, features = fixture()
    market = CatMarket(base_asset=AssetId(asset), quantity_step=Decimal(step))
    mapped = tuple(
        bar.model_copy(
            update={"instrument_id": market.instrument_id, "base_asset_id": market.base_asset}
        )
        for bar in bars
    )
    result, _ = replay_cat(
        root=ROOT,
        spec=spec,
        bars=mapped,
        features=features,
        feature_indices={time: i for i, time in enumerate(features.available_times)},
        trend_by_time={bar.available_time: True for bar in bars},
        forecasts={},
        level="B3",
        market_spec=market,
    )
    assert len(result.fills) == 2
    assert all(fill.quantity.asset_id == market.base_asset for fill in result.fills)
    assert all(fill.quantity.amount % market.quantity_step == 0 for fill in result.fills)
    assert abs(result.cost_identity_residual) < Decimal("1E-8")
    assert result.forced_close_status == "NO_POSITION"
    with pytest.raises(ValueError, match="asset units differ"):
        replay_cat(
            root=ROOT,
            spec=spec,
            bars=bars,
            features=features,
            feature_indices={time: i for i, time in enumerate(features.available_times)},
            trend_by_time={},
            forecasts={},
            level="B3",
            market_spec=market,
        )
