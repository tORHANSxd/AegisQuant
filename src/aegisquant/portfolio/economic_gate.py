"""Long/flat action-value gate; uncertainty and transaction costs create hysteresis."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    PositiveDecimal,
    UnitInterval,
)
from aegisquant.portfolio.transition_costs import TransitionCostEstimate
from aegisquant.research.models.economic_gate import CalibrationStatus, EconomicForecast


class EconomicAction(StrEnum):
    NO_TRADE = "NO_TRADE"
    ENTER_LONG = "ENTER_LONG"
    HOLD_CURRENT = "HOLD_CURRENT"
    REDUCE = "REDUCE"
    EXIT_LONG = "EXIT_LONG"


class EconomicGatePolicy(DomainModel):
    lambda_cost: PositiveDecimal = Decimal("2")
    p_enter: UnitInterval = Decimal("0.55")
    p_full_size: UnitInterval = Decimal("0.70")
    uncertainty_weight: NonNegativeDecimal = Decimal("0.25")
    model_uncertainty_buffer: NonNegativeDecimal = Decimal("0")
    execution_uncertainty_buffer: NonNegativeDecimal = Decimal("0.0002")
    target_volatility: PositiveDecimal = Decimal("0.20")
    maximum_weight: UnitInterval = Decimal("1")

    @model_validator(mode="after")
    def validate_budget(self) -> EconomicGatePolicy:
        if self.lambda_cost not in {Decimal("1.5"), Decimal("2"), Decimal("2.5")}:
            raise ValueError("lambda_cost is outside the preregistered neighborhood")
        if self.target_volatility not in {Decimal("0.15"), Decimal("0.20"), Decimal("0.25")}:
            raise ValueError("target volatility is outside the preregistered neighborhood")
        if self.p_full_size <= self.p_enter:
            raise ValueError("full-size confidence must exceed entry confidence")
        return self


class EconomicGateDecision(DomainModel):
    action: EconomicAction
    target_weight: UnitInterval
    q_long: FiniteDecimal
    entry_hurdle: NonNegativeDecimal
    exit_hurdle: NonNegativeDecimal
    reason: str


def decide_economic_transition(
    *,
    policy: EconomicGatePolicy,
    forecast: EconomicForecast,
    costs: TransitionCostEstimate,
    decision_time: UtcDateTime,
    current_weight: Decimal,
    trend_candidate: bool,
    trend_exit_confirmed: bool,
    data_quality_passed: bool,
    risk_allows_entry: bool,
    hard_risk_veto: bool = False,
    downside_risk_penalty: Decimal = Decimal("0"),
    annualized_volatility: Decimal = Decimal("1"),
    probability_filter: bool = True,
    uncertainty_filter: bool = True,
    volatility_sizing: bool = True,
    resize_permitted: bool = False,
) -> EconomicGateDecision:
    if not 0 <= current_weight <= 1 or downside_risk_penalty < 0 or annualized_volatility <= 0:
        raise ValueError("CAT requires long/flat weights and positive volatility")
    if forecast.available_time > decision_time or costs.available_time > decision_time:
        raise ValueError("economic gate cannot consume future forecasts or costs")
    conservative = (
        forecast.conservative_return(policy.uncertainty_weight)
        if uncertainty_filter
        else forecast.expected_gross_return
    )
    q_long = conservative - costs.holding - downside_risk_penalty
    buffer = policy.model_uncertainty_buffer + policy.execution_uncertainty_buffer
    entry_hurdle = policy.lambda_cost * costs.round_trip + buffer
    exit_hurdle = policy.lambda_cost * costs.exit.total + buffer

    def decision(action: EconomicAction, weight: Decimal, reason: str) -> EconomicGateDecision:
        return EconomicGateDecision(
            action=action,
            target_weight=weight,
            q_long=q_long,
            entry_hurdle=entry_hurdle,
            exit_hurdle=exit_hurdle,
            reason=reason,
        )

    if hard_risk_veto or not data_quality_passed:
        return decision(
            EconomicAction.EXIT_LONG if current_weight > 0 else EconomicAction.NO_TRADE,
            Decimal("0"),
            "RISK_OR_DATA_VETO",
        )
    if current_weight > 0 and trend_exit_confirmed:
        return decision(EconomicAction.EXIT_LONG, Decimal("0"), "CONFIRMED_TREND_EXIT")
    if forecast.calibration_status is not CalibrationStatus.VALIDATION_CALIBRATED:
        return decision(
            EconomicAction.HOLD_CURRENT if current_weight else EconomicAction.NO_TRADE,
            current_weight,
            "NO_VALIDATION_CALIBRATION",
        )
    if current_weight > 0:
        if -q_long > exit_hurdle:
            return decision(
                EconomicAction.EXIT_LONG, Decimal("0"), "ECONOMIC_VALUE_LOST_AFTER_EXIT_COST"
            )
        volatility_cap = min(
            policy.maximum_weight, policy.target_volatility / annualized_volatility
        )
        if volatility_sizing and resize_permitted and volatility_cap < current_weight:
            return decision(EconomicAction.REDUCE, volatility_cap, "DAILY_VOLATILITY_CAP")
        return decision(
            EconomicAction.HOLD_CURRENT, current_weight, "INSIDE_ECONOMIC_NO_TRADE_REGION"
        )
    if not trend_candidate or not risk_allows_entry:
        return decision(
            EconomicAction.NO_TRADE, Decimal("0"), "NO_PRIMARY_TREND_OR_ENTRY_RISK_PERMISSION"
        )
    if (probability_filter and forecast.p_net_positive < policy.p_enter) or q_long <= entry_hurdle:
        return decision(EconomicAction.NO_TRADE, Decimal("0"), "INSUFFICIENT_ROUND_TRIP_VALUE")
    weight = policy.maximum_weight
    if volatility_sizing:
        confidence = min(
            Decimal("1"),
            max(
                Decimal("0"),
                (forecast.p_net_positive - policy.p_enter) / (policy.p_full_size - policy.p_enter),
            ),
        )
        weight = min(weight, policy.target_volatility / annualized_volatility) * confidence
    return decision(
        EconomicAction.ENTER_LONG if weight > 0 else EconomicAction.NO_TRADE,
        weight,
        "CALIBRATED_TREND_VALUE_EXCEEDS_FULL_COST",
    )
