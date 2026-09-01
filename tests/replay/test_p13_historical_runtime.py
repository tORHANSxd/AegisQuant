"""Normalized historical morphology and shared runtime semantic tests."""

from __future__ import annotations

from aegisquant.runtime.comparison import compare_mode_semantics
from aegisquant.runtime.replay import (
    build_normalized_liquidity_scenario,
    replay_historical_scenario,
)
from aegisquant.runtime.runner import run_all_modes
from tests.p13_helpers import bundle, market, paper_policy


def test_normalized_major_event_morphology_is_disclosed_and_replayable() -> None:
    scenario = build_normalized_liquidity_scenario(anchor=market())
    result = replay_historical_scenario(
        bundle=bundle(), scenario=scenario, paper_policy=paper_policy()
    )
    assert scenario.normalized_fixture is True
    assert scenario.raw_tick_data_claimed is False
    assert result.observation_count == 4
    assert result.economic_order_count == 1
    assert result.duplicate_order_count == 0
    assert result.duplicate_fill_count == 0
    assert result.venue_network_requests_performed == 0


def test_historical_paper_shadow_share_one_command_identity() -> None:
    results = run_all_modes(bundle=bundle(), market=market(), paper_policy=paper_policy())
    comparison = compare_mode_semantics(tuple(item.trace for item in results))
    assert comparison.semantic_identity_equal is True
