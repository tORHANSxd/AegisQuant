"""Independent RiskSnapshot and RiskDecision tests."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.risk.engine import evaluate_portfolio_proposal
from aegisquant.risk.models import RiskDecisionStatus, RiskState
from tests.p11_helpers import DECISION_TIME, proposal, signed_policy, snapshot, trusted_public_keys


def test_healthy_independent_snapshot_approves_without_amplifying_proposal() -> None:
    portfolio = proposal()
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=snapshot(portfolio=portfolio),
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    assert decision.status is RiskDecisionStatus.APPROVED
    assert decision.state is RiskState.NORMAL
    assert decision.snapshot_sha256 != portfolio.proposal_sha256
    proposed = {leg.instrument_id: leg.target_weight for leg in portfolio.legs}
    assert all(
        abs(target.approved_target_weight) <= abs(proposed[target.instrument_id])
        for target in decision.approved_targets
    )


def test_stale_risk_data_rejects_new_risk() -> None:
    portfolio = proposal()
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=snapshot(portfolio=portfolio, stale_seconds=31),
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    assert decision.status is RiskDecisionStatus.REJECTED
    assert decision.new_risk_allowed is False
    assert "AQ-RISK-DATA-STALE" in decision.reason_codes
    assert "AQ-RISK-MODEL-STALE" in decision.reason_codes


def test_loss_or_margin_breach_moves_to_reduce_only() -> None:
    portfolio = proposal()
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=snapshot(
            portfolio=portfolio,
            daily_pnl=Decimal("-0.06"),
            margin=Decimal("0.85"),
        ),
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    assert decision.status is RiskDecisionStatus.REDUCE_ONLY
    assert decision.state is RiskState.REDUCE_ONLY
    assert decision.new_risk_allowed is False
