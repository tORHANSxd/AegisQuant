"""Independent long-spot/short-perpetual carry value and admission checks."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal
from aegisquant.research.models.funding_forecast import FundingForecast


class CarryCosts(DomainModel):
    spot_entry_exit: NonNegativeDecimal
    perp_entry_exit: NonNegativeDecimal
    borrow_financing: NonNegativeDecimal
    legging: NonNegativeDecimal
    capital_charge: NonNegativeDecimal
    tail_risk_buffer: NonNegativeDecimal
    uncertainty_buffer: NonNegativeDecimal

    @property
    def round_trip(self) -> Decimal:
        return self.spot_entry_exit + self.perp_entry_exit


class CarryAdmissionEvidence(DomainModel):
    multileg_margin_cost_invariants_passed: bool = False
    historical_fee_rule_margin_versions_verified: bool = False
    funding_calendar_verified: bool = False
    both_legs_capacity_passed: bool = False
    independent_sleeve_capital_available: bool = False
    liquidation_distance_passed: bool = False
    exchange_and_stablecoin_concentration_passed: bool = False
    evidence_reference: str = Field(min_length=1)

    @property
    def complete(self) -> bool:
        return all(
            (
                self.multileg_margin_cost_invariants_passed,
                self.historical_fee_rule_margin_versions_verified,
                self.funding_calendar_verified,
                self.both_legs_capacity_passed,
                self.independent_sleeve_capital_available,
                self.liquidation_distance_passed,
                self.exchange_and_stablecoin_concentration_passed,
            )
        )


class CarryDecision(DomainModel):
    action: Literal["NO_TRADE", "PAPER_CANDIDATE", "EXIT_AND_FLATTEN"]
    expected_net_carry: FiniteDecimal
    entry_hurdle: NonNegativeDecimal
    reasons: tuple[str, ...]
    allow_combination_with_trend: Literal[False] = False
    live_trading: Literal[False] = False


def evaluate_carry(
    *,
    forecast: FundingForecast,
    costs: CarryCosts,
    evidence: CarryAdmissionEvidence,
    expected_basis_convergence: Decimal,
    decision_time: UtcDateTime,
    holding: bool = False,
    basis_expansion: Decimal = Decimal("0"),
    maximum_basis_expansion: Decimal = Decimal("0.02"),
) -> CarryDecision:
    if forecast.available_time > decision_time or not expected_basis_convergence.is_finite():
        raise ValueError("carry inputs must be finite and known at decision time")
    if maximum_basis_expansion <= 0 or basis_expansion < 0:
        raise ValueError("invalid basis expansion stress limits")
    net = (
        forecast.expected_received_by_short
        + expected_basis_convergence
        - costs.round_trip
        - costs.borrow_financing
        - costs.legging
        - costs.capital_charge
        - costs.tail_risk_buffer
    )
    hurdle = 2 * costs.round_trip + costs.uncertainty_buffer + forecast.uncertainty
    reasons: list[str] = []
    if not evidence.complete:
        reasons.append("INCOMPLETE_INDEPENDENT_EXECUTION_AND_RULE_EVIDENCE")
    if basis_expansion >= maximum_basis_expansion:
        reasons.append("BASIS_EXPANSION_RISK")
    if holding and forecast.expected_received_by_short <= 0:
        reasons.append("FUNDING_REVERSAL")
    if net <= hurdle:
        reasons.append("NET_CARRY_DOES_NOT_CLEAR_TWO_TIMES_ALL_IN_COST")
    if holding and any(
        reason != "NET_CARRY_DOES_NOT_CLEAR_TWO_TIMES_ALL_IN_COST" for reason in reasons
    ):
        action = "EXIT_AND_FLATTEN"
    else:
        action = "NO_TRADE" if reasons else "PAPER_CANDIDATE"
    return CarryDecision(
        action=action, expected_net_carry=net, entry_hurdle=hurdle, reasons=tuple(reasons)
    )
