"""Signal discounting and robust portfolio proposal tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.identifiers import ProposalId
from aegisquant.portfolio.optimizer import build_portfolio_proposal, normalize_signal
from tests.p11_helpers import AS_OF, BTC, CREATED, construction_policy, covariance, proposal, signal


def test_signal_is_clipped_discounted_and_can_enter_no_trade_zone() -> None:
    policy = construction_policy()
    clipped = normalize_signal(
        signal(
            asset=BTC,
            instrument="BTC-CLIPPED",
            raw_score=Decimal("2"),
            confidence=Decimal("0.5"),
        ),
        policy,
    )
    quiet = normalize_signal(
        signal(
            asset=BTC,
            instrument="BTC-QUIET",
            raw_score=Decimal("0.04"),
            confidence=Decimal("0.5"),
        ),
        policy,
    )
    assert clipped.clipped_score == Decimal("1")
    assert clipped.robust_score < clipped.clipped_score
    assert "AQ-PORTFOLIO-SIGNAL-CLIPPED" in clipped.reason_codes
    assert quiet.in_no_trade_zone is True and quiet.robust_score == 0


def test_robust_optimizer_emits_explainable_proposal_only_output() -> None:
    result = proposal()
    assert result.order_capability is False
    assert result.gross_weight <= Decimal("0.60")
    assert result.turnover <= Decimal("0.40")
    assert result.expected_volatility <= Decimal("0.25")
    assert len(result.proposal_sha256) == 64
    assert all(leg.constraint_reasons for leg in result.legs)
    assert sum((leg.marginal_variance_contribution for leg in result.legs), start=0) >= 0


def test_optimizer_rejects_future_covariance() -> None:
    future = covariance().model_copy(update={"available_at": AS_OF + timedelta(seconds=1)})
    with pytest.raises(ValueError, match="FUTURE-COVARIANCE"):
        build_portfolio_proposal(
            proposal_id=ProposalId("future-covariance"),
            signals=(
                signal(
                    asset=BTC,
                    instrument="BTC-FUTURE-COV",
                    raw_score=Decimal("0.5"),
                    confidence=Decimal("1"),
                ),
            ),
            covariance=future,
            policy=construction_policy(),
            portfolio_nav=Decimal("100000"),
            as_of_time=AS_OF,
            created_at=CREATED,
        )
