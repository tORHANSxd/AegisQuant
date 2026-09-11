"""Deterministic portfolio stress scenarios mapped to independent risk actions."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import VenueId
from aegisquant.domain.values import FiniteDecimal, PositiveDecimal, UnitInterval, canonical_result
from aegisquant.portfolio.models import PortfolioProposal
from aegisquant.risk.models import RiskAction, RiskSnapshot, RiskState
from aegisquant.risk.policy import RiskPolicy

ZERO = Decimal("0")
ONE = Decimal("1")


class PortfolioStressScenario(DomainModel):
    scenario_id: str = Field(min_length=1, max_length=255)
    asset_return_shocks: dict[str, FiniteDecimal]
    stablecoin_return_shocks: dict[str, FiniteDecimal]
    correlation_multiplier: PositiveDecimal
    liquidity_multiplier: UnitInterval
    margin_multiplier: PositiveDecimal
    unavailable_venues: tuple[VenueId, ...] = ()

    @model_validator(mode="after")
    def validate_shocks(self) -> PortfolioStressScenario:
        if not self.asset_return_shocks:
            raise ValueError("stress scenario requires asset shocks")
        if any(value < Decimal("-1") for value in self.asset_return_shocks.values()):
            raise ValueError("asset return shock cannot lose more than 100 percent")
        if any(value < Decimal("-1") for value in self.stablecoin_return_shocks.values()):
            raise ValueError("stablecoin shock cannot lose more than 100 percent")
        return self


class PortfolioStressResult(DomainModel):
    scenario_id: str
    projected_loss_fraction: Decimal
    stressed_volatility: Decimal
    stressed_margin_utilization: Decimal
    stressed_liquidity_score: Decimal
    affected_venues: tuple[VenueId, ...]
    state: RiskState
    action: RiskAction
    reason_codes: tuple[str, ...]


def run_portfolio_stress(
    *,
    proposal: PortfolioProposal,
    snapshot: RiskSnapshot,
    policy: RiskPolicy,
    scenario: PortfolioStressScenario,
) -> PortfolioStressResult:
    loss = ZERO
    affected_venues: set[VenueId] = set()
    for leg in proposal.legs:
        shock = scenario.asset_return_shocks.get(str(leg.asset_id), ZERO)
        if leg.stablecoin_id is not None:
            shock += scenario.stablecoin_return_shocks.get(str(leg.stablecoin_id), ZERO)
        loss += abs(leg.target_weight) * max(ZERO, -shock)
        if leg.venue_id in scenario.unavailable_venues and leg.target_weight != ZERO:
            affected_venues.add(leg.venue_id)
    stressed_volatility = canonical_result(
        proposal.expected_volatility * scenario.correlation_multiplier.sqrt()
    )
    stressed_margin = canonical_result(snapshot.margin_utilization * scenario.margin_multiplier)
    stressed_liquidity = canonical_result(snapshot.liquidity_score * scenario.liquidity_multiplier)
    reasons: list[str] = []
    state = RiskState.NORMAL
    action = RiskAction.MONITOR
    if affected_venues or stressed_margin >= ONE:
        state = RiskState.HALTED
        action = RiskAction.HALT
        reasons.append("AQ-RISK-STRESS-KILL-SWITCH")
    elif (
        loss >= policy.maximum_drawdown_fraction
        or stressed_margin >= policy.maximum_margin_utilization
        or stressed_liquidity <= policy.minimum_liquidity_score
    ):
        state = RiskState.REDUCE_ONLY
        action = RiskAction.REDUCE
        reasons.append("AQ-RISK-STRESS-REDUCE-ONLY")
    elif stressed_volatility > proposal.expected_volatility:
        state = RiskState.CAUTION
        action = RiskAction.TIGHTEN_LIMITS
        reasons.append("AQ-RISK-STRESS-CAUTION")
    else:
        reasons.append("AQ-RISK-STRESS-WITHIN-LIMITS")
    return PortfolioStressResult(
        scenario_id=scenario.scenario_id,
        projected_loss_fraction=canonical_result(loss),
        stressed_volatility=stressed_volatility,
        stressed_margin_utilization=stressed_margin,
        stressed_liquidity_score=stressed_liquidity,
        affected_venues=tuple(sorted(affected_venues, key=str)),
        state=state,
        action=action,
        reason_codes=tuple(reasons),
    )
