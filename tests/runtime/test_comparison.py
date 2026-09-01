"""Three-mode semantic equality and execution-error scorecards."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aegisquant.runtime.comparison import (
    build_scorecard,
    compare_mode_semantics,
    execution_error_point,
)
from aegisquant.runtime.models import MarketModeLimitations, RuntimeMode
from aegisquant.runtime.runner import run_all_modes
from tests.p13_helpers import bundle, market, paper_policy


def test_three_modes_preserve_risk_bound_semantics() -> None:
    results = run_all_modes(bundle=bundle(), market=market(), paper_policy=paper_policy())
    comparison = compare_mode_semantics(tuple(item.trace for item in results))
    assert comparison.semantic_identity_equal is True
    assert comparison.mismatch_fields == ()
    assert set(comparison.modes) == set(RuntimeMode)
    assert results[-1].trace.filled_quantity.amount == 0
    assert results[0].trace.filled_quantity.amount > 0


def test_execution_error_decomposes_quote_fill_latency_and_fee() -> None:
    result = run_all_modes(bundle=bundle(), market=market(), paper_policy=paper_policy())[1]
    point = execution_error_point(result.trace)
    assert point.target_order_gap == 0
    assert point.expected_to_executable_bps is not None
    assert point.executable_to_fill_bps == 2
    assert point.decision_latency_ms == 1000
    assert point.fill_ratio > 0
    assert point.fee_amount > 0


def test_scorecard_keeps_testnet_pnl_and_capacity_out() -> None:
    results = run_all_modes(bundle=bundle(), market=market(), paper_policy=paper_policy())
    scorecard = build_scorecard(tuple(item.trace for item in results), restart_count=1)
    assert scorecard.testnet_pnl_included is False
    assert scorecard.production_capacity_claimed is False
    assert scorecard.restart_count == 1
    with pytest.raises(ValidationError, match="Testnet PnL"):
        scorecard.model_copy(update={"testnet_pnl_included": True}).model_validate(
            {**scorecard.model_dump(), "testnet_pnl_included": True}
        )


def test_market_mode_limitations_fail_closed() -> None:
    limitations = MarketModeLimitations(
        reason_codes=("AQ-RUNTIME-NONPRODUCTION",),
    )
    assert limitations.venue_network_requests_performed == 0
    with pytest.raises(ValidationError, match="production evidence"):
        MarketModeLimitations(
            testnet_pnl_is_strategy_evidence=True,
            reason_codes=("unsafe",),
        )
