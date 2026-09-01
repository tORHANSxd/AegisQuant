"""PortfolioProposal → RiskDecision → Paper OrderIntent pre-trade gates."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import AssetId, InstrumentId, StrategyId
from aegisquant.domain.values import Quantity
from aegisquant.risk.engine import (
    build_risk_snapshot,
    create_paper_order_intent,
    evaluate_portfolio_proposal,
)
from aegisquant.risk.models import PreTradeRequest, RiskDecision, RiskPosition
from tests.p11_helpers import (
    BTC,
    DECISION_TIME,
    proposal,
    signal,
    signed_policy,
    snapshot,
    trusted_public_keys,
)


def request_for(
    decision: RiskDecision,
    *,
    delta_fraction: Decimal = Decimal("0.5"),
) -> PreTradeRequest:
    target = next(item for item in decision.approved_targets if item.approved_delta_weight != 0)
    requested_delta = target.approved_delta_weight * delta_fraction
    return PreTradeRequest(
        request_id="paper-pretrade-request",
        proposal_id=decision.proposal_id,
        risk_decision_id=decision.risk_decision_id,
        instrument_id=target.instrument_id,
        asset_id=target.asset_id,
        strategy_id=target.strategy_id,
        account_id=target.account_id,
        requested_delta_weight=requested_delta,
        side=OrderSide.BUY if requested_delta > 0 else OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Quantity(amount=Decimal("0.01"), asset_id=target.asset_id),
        time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
        created_at=DECISION_TIME + timedelta(seconds=1),
        valid_until=DECISION_TIME + timedelta(seconds=10),
    )


def test_only_fresh_approved_decision_can_create_paper_order_intent() -> None:
    portfolio = proposal()
    risk_snapshot = snapshot(portfolio=portfolio)
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=risk_snapshot,
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    intent = create_paper_order_intent(
        request=request_for(decision),
        proposal=portfolio,
        decision=decision,
        snapshot=risk_snapshot,
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
    )
    assert intent.risk_decision_id == decision.risk_decision_id
    assert intent.reduce_only is False


def test_strategy_request_cannot_amplify_approved_target() -> None:
    portfolio = proposal()
    risk_snapshot = snapshot(portfolio=portfolio)
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=risk_snapshot,
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    with pytest.raises(ValueError, match="AMPLIFIES-APPROVED-TARGET"):
        create_paper_order_intent(
            request=request_for(decision, delta_fraction=Decimal("1.01")),
            proposal=portfolio,
            decision=decision,
            snapshot=risk_snapshot,
            signed_policy=signed_policy(),
            trusted_public_keys=trusted_public_keys(),
        )


def test_account_level_limit_includes_existing_nonproposal_positions() -> None:
    portfolio = proposal()
    base = snapshot(portfolio=portfolio)
    extra = RiskPosition(
        instrument_id=InstrumentId("SOL-USDT-PERP"),
        asset_id=AssetId("SOL"),
        strategy_id=StrategyId("strategy-other"),
        account_id=portfolio.legs[0].account_id,
        signed_weight=Decimal("0.59"),
    )
    crowded = build_risk_snapshot(
        snapshot_id="snapshot-crowded-account",
        as_of_time=base.as_of_time,
        available_at=base.available_at,
        data_last_available_at=base.data_last_available_at,
        model_last_available_at=base.model_last_available_at,
        positions=(*base.positions, extra),
        daily_pnl_fraction=base.daily_pnl_fraction,
        drawdown_fraction=base.drawdown_fraction,
        margin_utilization=base.margin_utilization,
        liquidity_score=base.liquidity_score,
        venue_operational=True,
        security_clear=True,
        major_event_clear=True,
        ledger_reconciled=True,
    )
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=crowded,
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    with pytest.raises(ValueError, match="ACCOUNT-LIMIT"):
        create_paper_order_intent(
            request=request_for(decision),
            proposal=portfolio,
            decision=decision,
            snapshot=crowded,
            signed_policy=signed_policy(),
            trusted_public_keys=trusted_public_keys(),
        )


def test_reduce_only_decision_can_only_move_toward_zero() -> None:
    reduce_signal = signal(
        asset=BTC,
        instrument="BTC-USDT-PERP",
        raw_score=Decimal("0.10"),
        confidence=Decimal("1"),
        current_weight=Decimal("0.20"),
    )
    portfolio = proposal(custom_signals=(reduce_signal,))
    risk_snapshot = snapshot(
        portfolio=portfolio,
        daily_pnl=Decimal("-0.06"),
    )
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=risk_snapshot,
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    intent = create_paper_order_intent(
        request=request_for(decision),
        proposal=portfolio,
        decision=decision,
        snapshot=risk_snapshot,
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
    )
    assert intent.reduce_only is True
    assert intent.side is OrderSide.SELL


def test_missing_or_mismatched_risk_decision_is_rejected() -> None:
    portfolio = proposal()
    risk_snapshot = snapshot(portfolio=portfolio)
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=risk_snapshot,
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    mismatched = request_for(decision).model_copy(
        update={"proposal_id": portfolio.proposal_id.__class__("different-proposal")}
    )
    with pytest.raises(ValueError, match="PROPOSAL-MISMATCH"):
        create_paper_order_intent(
            request=mismatched,
            proposal=portfolio,
            decision=decision,
            snapshot=risk_snapshot,
            signed_policy=signed_policy(),
            trusted_public_keys=trusted_public_keys(),
        )
