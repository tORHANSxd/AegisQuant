"""Randomized P11 proofs for portfolio constraints and risk non-amplification."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.values import Quantity
from aegisquant.risk.engine import create_paper_order_intent, evaluate_portfolio_proposal
from aegisquant.risk.models import PreTradeRequest, RiskState
from aegisquant.risk.state_machine import transition_risk_state
from tests.p11_helpers import (
    AS_OF,
    BTC,
    DECISION_TIME,
    ETH,
    construction_policy,
    proposal,
    signal,
    signed_policy,
    snapshot,
    trusted_public_keys,
)


@settings(max_examples=60, deadline=None)
@given(
    btc_score=st.decimals(min_value="-2", max_value="2", places=3),
    eth_score=st.decimals(min_value="-2", max_value="2", places=3),
    btc_confidence=st.decimals(min_value="0", max_value="1", places=3),
    eth_confidence=st.decimals(min_value="0", max_value="1", places=3),
    adv=st.decimals(min_value="100000", max_value="2000000", places=0),
    impact=st.decimals(min_value="1", max_value="80", places=2),
)
def test_randomized_portfolio_outputs_satisfy_every_hard_constraint(
    btc_score: Decimal,
    eth_score: Decimal,
    btc_confidence: Decimal,
    eth_confidence: Decimal,
    adv: Decimal,
    impact: Decimal,
) -> None:
    portfolio = proposal(
        custom_signals=(
            signal(
                asset=BTC,
                instrument="BTC-USDT-PERP",
                raw_score=btc_score,
                confidence=btc_confidence,
                adv=adv,
                impact_bps=impact,
            ),
            signal(
                asset=ETH,
                instrument="ETH-USDT-PERP",
                raw_score=eth_score,
                confidence=eth_confidence,
                adv=adv,
                impact_bps=impact,
            ),
        )
    )
    policy = construction_policy()
    assert portfolio.gross_weight <= policy.maximum_gross_weight
    assert portfolio.turnover <= policy.maximum_turnover
    assert portfolio.expected_volatility <= policy.volatility_target
    assert all(abs(leg.delta_weight) <= leg.capacity_weight for leg in portfolio.legs)
    assert all(leg.estimated_impact_bps <= policy.maximum_impact_bps for leg in portfolio.legs)
    by_instrument = {str(leg.instrument_id): abs(leg.target_weight) for leg in portfolio.legs}
    assert by_instrument["BTC-USDT-PERP"] <= Decimal("0.25")
    assert sum(abs(leg.target_weight) for leg in portfolio.legs) <= Decimal("0.45")


@settings(max_examples=40, deadline=None)
@given(multiplier=st.decimals(min_value="1.001", max_value="5", places=3))
def test_strategy_cannot_amplify_risk_approved_delta(multiplier: Decimal) -> None:
    portfolio = proposal()
    risk_snapshot = snapshot(portfolio=portfolio)
    decision = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=risk_snapshot,
        signed_policy=signed_policy(),
        trusted_public_keys=trusted_public_keys(),
        decision_time=DECISION_TIME,
    )
    target = next(item for item in decision.approved_targets if item.approved_delta_weight != 0)
    requested = target.approved_delta_weight * multiplier
    request = PreTradeRequest(
        request_id="property-amplification-attempt",
        proposal_id=portfolio.proposal_id,
        risk_decision_id=decision.risk_decision_id,
        instrument_id=target.instrument_id,
        asset_id=target.asset_id,
        strategy_id=target.strategy_id,
        account_id=target.account_id,
        requested_delta_weight=requested,
        side=OrderSide.BUY if requested > 0 else OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Quantity(amount=Decimal("0.01"), asset_id=target.asset_id),
        time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
        created_at=DECISION_TIME + timedelta(seconds=1),
        valid_until=DECISION_TIME + timedelta(seconds=10),
    )
    with pytest.raises(ValueError, match="AMPLIFIES-APPROVED-TARGET"):
        create_paper_order_intent(
            request=request,
            proposal=portfolio,
            decision=decision,
            snapshot=risk_snapshot,
            signed_policy=signed_policy(),
            trusted_public_keys=trusted_public_keys(),
        )


@settings(max_examples=40, deadline=None)
@given(
    current=st.sampled_from(
        [RiskState.NORMAL, RiskState.CAUTION, RiskState.REDUCE_ONLY, RiskState.HALTED]
    ),
    target=st.sampled_from(
        [RiskState.NORMAL, RiskState.CAUTION, RiskState.REDUCE_ONLY, RiskState.HALTED]
    ),
)
def test_automatic_state_transition_never_becomes_less_safe(
    current: RiskState, target: RiskState
) -> None:
    rank = {
        RiskState.NORMAL: 0,
        RiskState.CAUTION: 1,
        RiskState.REDUCE_ONLY: 2,
        RiskState.HALTED: 3,
    }
    if rank[target] < rank[current]:
        with pytest.raises(ValueError, match="UNSAFE-TRANSITION"):
            transition_risk_state(
                sequence=1,
                current=current,
                target=target,
                automatic=True,
                actor="independent-risk-engine",
                reason_code="property-transition",
                occurred_at=AS_OF,
            )
    else:
        record = transition_risk_state(
            sequence=1,
            current=current,
            target=target,
            automatic=True,
            actor="independent-risk-engine",
            reason_code="property-transition",
            occurred_at=AS_OF,
        )
        assert rank[record.target_state] >= rank[record.previous_state]
