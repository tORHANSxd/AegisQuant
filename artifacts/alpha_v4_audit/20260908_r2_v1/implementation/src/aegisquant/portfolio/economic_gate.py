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
from aegisquant.portfolio.event_risk_overlay import EventRiskOverlay
from aegisquant.portfolio.transition_costs import ExecutionLegCost, TransitionCostEstimate
from aegisquant.research.models.economic_gate import CalibrationStatus, EconomicForecast
from aegisquant.research.validation.cat_contract import CatAuditPolicy


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
    risk_target_weight: UnitInterval = Decimal("0")
    alpha_confidence_multiplier: UnitInterval = Decimal("1")
    signal_filter_pass: bool | None = None
    cost_filter_pass: bool | None = None
    probability_filter_pass: bool | None = None
    uncertainty_filter_pass: bool | None = None
    decision_value_kind: str = "MEAN_GROSS_RETURN"
    distribution_penalty: NonNegativeDecimal = Decimal("0")
    mean_estimation_uncertainty: NonNegativeDecimal | None = None


def decide_economic_transition(
    *,
    policy: EconomicGatePolicy,
    forecast: EconomicForecast | None,
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
    event_overlay: EventRiskOverlay | None = None,
    audit_policy: CatAuditPolicy | None = None,
    rebalance_cost: ExecutionLegCost | None = None,
) -> EconomicGateDecision:
    if not 0 <= current_weight <= 1 or downside_risk_penalty < 0 or annualized_volatility <= 0:
        raise ValueError("CAT requires long/flat weights and positive volatility")
    if (
        forecast is not None and forecast.available_time > decision_time
    ) or costs.available_time > decision_time:
        raise ValueError("economic gate cannot consume future forecasts or costs")
    switches = audit_policy.switches if audit_policy else None
    if switches is not None:
        probability_filter = switches.use_probability_entry_gate
        uncertainty_filter = switches.use_uncertainty_entry_gate
        volatility_sizing = switches.use_risk_sizing
    entry_multiplier = scale = Decimal("1")
    if event_overlay is not None:
        if event_overlay.available_time > decision_time:
            raise ValueError("event risk evidence is not yet available")
        data_quality_passed &= event_overlay.valid_until >= decision_time
        hard_risk_veto |= event_overlay.risk_veto
        risk_allows_entry &= event_overlay.data_confidence > 0
        entry_multiplier = event_overlay.entry_hurdle_multiplier
        scale = event_overlay.position_scale * event_overlay.data_confidence
        costs = costs.model_copy(
            update={
                "entry": costs.entry.model_copy(
                    update={
                        "slippage": costs.entry.slippage
                        * event_overlay.expected_slippage_multiplier
                    }
                ),
                "exit": costs.exit.model_copy(
                    update={
                        "slippage": costs.exit.slippage * event_overlay.expected_slippage_multiplier
                    }
                ),
            }
        )
    conservative = (
        Decimal("0")
        if forecast is None
        else (
            forecast.conservative_return(policy.uncertainty_weight)
            if uncertainty_filter
            else forecast.expected_gross_return
        )
    )
    q_long = conservative - costs.holding - downside_risk_penalty
    buffer = policy.model_uncertainty_buffer + policy.execution_uncertainty_buffer
    entry_hurdle = policy.lambda_cost * costs.round_trip * entry_multiplier + buffer
    exit_hurdle = policy.lambda_cost * costs.exit.total + buffer
    risk_target = (
        min(policy.maximum_weight, policy.target_volatility / annualized_volatility)
        if volatility_sizing
        else policy.maximum_weight
    )
    confidence = Decimal("1")
    if (switches.use_confidence_sizing if switches else volatility_sizing) and forecast is not None:
        confidence = min(
            Decimal("1"),
            max(
                Decimal("0"),
                (forecast.p_net_positive - policy.p_enter) / (policy.p_full_size - policy.p_enter),
            ),
        )
    signal_pass = None if forecast is None else forecast.expected_gross_return > 0
    cost_pass = (
        None if forecast is None else forecast.expected_gross_return - costs.holding > entry_hurdle
    )
    probability_pass = None if forecast is None else forecast.p_net_positive >= policy.p_enter
    uncertainty_pass = (
        None
        if forecast is None
        else forecast.conservative_return(policy.uncertainty_weight) - costs.holding
        > (entry_hurdle if switches is None or switches.use_cost_entry_gate else 0)
    )

    def decision(action: EconomicAction, weight: Decimal, reason: str) -> EconomicGateDecision:
        if action is EconomicAction.ENTER_LONG:
            weight *= scale
            if weight == 0:
                action, reason = EconomicAction.NO_TRADE, "EVENT_CONFIDENCE_OR_POSITION_SCALE_ZERO"
        elif action in {EconomicAction.HOLD_CURRENT, EconomicAction.REDUCE}:
            cap = policy.maximum_weight * scale
            if weight > cap:
                action, weight, reason = EconomicAction.REDUCE, cap, "EVENT_RISK_POSITION_CAP"
        return EconomicGateDecision(
            action=action,
            target_weight=weight,
            q_long=q_long,
            entry_hurdle=entry_hurdle,
            exit_hurdle=exit_hurdle,
            reason=reason,
            risk_target_weight=risk_target,
            alpha_confidence_multiplier=confidence,
            signal_filter_pass=signal_pass,
            cost_filter_pass=cost_pass,
            probability_filter_pass=probability_pass,
            uncertainty_filter_pass=uncertainty_pass,
            decision_value_kind="MEDIAN_MINUS_PREDICTIVE_WIDTH"
            if uncertainty_filter
            else "MEAN_GROSS_RETURN",
            distribution_penalty=policy.uncertainty_weight
            * (forecast.q90_return - forecast.q10_return)
            if uncertainty_filter and forecast is not None
            else Decimal("0"),
        )

    if hard_risk_veto or not data_quality_passed:
        return decision(
            EconomicAction.EXIT_LONG if current_weight > 0 else EconomicAction.NO_TRADE,
            Decimal("0"),
            "RISK_OR_DATA_VETO",
        )
    if current_weight > 0 and trend_exit_confirmed:
        return decision(EconomicAction.EXIT_LONG, Decimal("0"), "CONFIRMED_TREND_EXIT")
    needs_forecast = switches is None or any(
        (
            switches.use_model_entry_filter,
            switches.use_cost_entry_gate,
            switches.use_probability_entry_gate,
            switches.use_uncertainty_entry_gate,
            switches.use_confidence_sizing,
            switches.use_model_economic_exit,
        )
    )
    forecast_valid = (
        forecast is not None
        and forecast.calibration_status is CalibrationStatus.VALIDATION_CALIBRATED
    )
    r2 = audit_policy is not None and audit_policy.version == "cat-audit-r2"
    component_failure = None
    exit_forecast_valid = forecast_valid
    if r2 and audit_policy is not None:
        component_failure = (
            "MODEL_MISSING"
            if forecast is None
            else forecast.component_failure(
                probability_required=probability_filter
                or bool(switches and switches.use_confidence_sizing),
                decision_time=decision_time,
                maximum_age_days=audit_policy.maximum_calibration_age_days,
            )
        )
        forecast_valid = component_failure is None
        exit_forecast_valid = (
            forecast is not None
            and forecast.component_failure(
                probability_required=False,
                decision_time=decision_time,
                maximum_age_days=audit_policy.maximum_calibration_age_days,
            )
            is None
        )
    # In v2 an unavailable entry model never vetoes the independent trend/risk exit.
    if needs_forecast and not forecast_valid and (switches is None or current_weight == 0):
        return decision(
            EconomicAction.HOLD_CURRENT if current_weight else EconomicAction.NO_TRADE,
            current_weight,
            component_failure
            if r2 and component_failure
            else "MISSING_FORECAST"
            if forecast is None
            else "NO_VALIDATION_CALIBRATION",
        )
    if current_weight > 0:
        if (
            (switches is None or switches.use_model_economic_exit)
            and exit_forecast_valid
            and -q_long > exit_hurdle
        ):
            return decision(
                EconomicAction.EXIT_LONG, Decimal("0"), "ECONOMIC_VALUE_LOST_AFTER_EXIT_COST"
            )
        volatility_cap = risk_target
        if (
            audit_policy is not None
            and switches is not None
            and switches.use_rebalancing_band
            and resize_permitted
        ):
            target = (
                risk_target * confidence
                if forecast_valid or not needs_forecast
                else min(current_weight, risk_target)
            )
            band = max(
                audit_policy.rebalance_weight_band,
                policy.lambda_cost
                * (
                    rebalance_cost.total
                    if r2 and rebalance_cost is not None
                    else max(costs.entry.total, costs.exit.total)
                ),
            )
            if abs(target - current_weight) > band:
                if target > current_weight and not risk_allows_entry:
                    return decision(
                        EconomicAction.HOLD_CURRENT, current_weight, "REBALANCE_ENTRY_RISK_BLOCKED"
                    )
                return decision(
                    EconomicAction.REDUCE if target < current_weight else EconomicAction.ENTER_LONG,
                    target,
                    "COST_AWARE_RISK_REBALANCE",
                )
            return decision(
                EconomicAction.HOLD_CURRENT, current_weight, "INSIDE_RISK_REBALANCE_BAND"
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
    if switches is not None:
        for enabled, passed, reason in (
            (switches.use_model_entry_filter, signal_pass, "MODEL_ENTRY_REJECTED"),
            (switches.use_cost_entry_gate, cost_pass, "COST_ENTRY_REJECTED"),
            (switches.use_probability_entry_gate, probability_pass, "PROBABILITY_ENTRY_REJECTED"),
            (switches.use_uncertainty_entry_gate, uncertainty_pass, "UNCERTAINTY_ENTRY_REJECTED"),
        ):
            if enabled and not passed:
                return decision(EconomicAction.NO_TRADE, Decimal("0"), reason)
        return decision(
            EconomicAction.ENTER_LONG if risk_target * confidence > 0 else EconomicAction.NO_TRADE,
            risk_target * confidence,
            "TREND_ENTRY_PASSED_ENABLED_GATES",
        )
    if (probability_filter and not probability_pass) or q_long <= entry_hurdle:
        return decision(EconomicAction.NO_TRADE, Decimal("0"), "INSUFFICIENT_ROUND_TRIP_VALUE")
    weight = policy.maximum_weight
    if volatility_sizing and forecast is not None:
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
