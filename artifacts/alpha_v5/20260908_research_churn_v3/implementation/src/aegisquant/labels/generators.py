"""Deterministic generators for return, execution, and event-impact labels."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, localcontext

from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.labels.models import (
    ActionValueLabel,
    CostAssumption,
    DirectionClass,
    EventImpactLabel,
    ExecutionLabel,
    PricePathObservation,
    ReturnPathLabel,
)


def _quantile(values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
    if not values:
        raise ValueError("quantile requires observations")
    ordered = tuple(sorted(values))
    if len(ordered) == 1:
        return ordered[0]
    position = probability * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return canonical_result(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _sample_std(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(
        len(values) - 1
    )
    with localcontext() as context:
        context.prec = 34
        return canonical_result(variance.sqrt())


def _log_return(current: Decimal, previous: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 34
        return canonical_result((current / previous).ln())


def _executable_path(
    values: tuple[PricePathObservation, ...],
    decision_index: int,
    horizon_steps: int,
) -> tuple[PricePathObservation, tuple[PricePathObservation, ...]]:
    if horizon_steps < 1:
        raise ValueError("label horizon must be positive")
    if decision_index < 0 or decision_index + horizon_steps >= len(values):
        raise IndexError("label horizon exceeds price path")
    decision = values[decision_index]
    future = values[decision_index + 1 : decision_index + horizon_steps + 1]
    if any(item.instrument_id != decision.instrument_id for item in future):
        raise ValueError("label path cannot mix instruments")
    previous = decision
    for item in future:
        if item.available_time <= previous.available_time or item.event_time <= previous.event_time:
            raise ValueError("label observations must be strictly increasing and future available")
        previous = item
    if future[0].event_time <= decision.available_time:
        raise ValueError("entry event occurred before the decision became available")
    return decision, future


def generate_action_value_label(
    *,
    observations: Iterable[PricePathObservation],
    decision_index: int,
    horizon_steps: int,
    cost: CostAssumption,
    long_risk_buffer: Decimal = Decimal("0"),
    short_tail_risk_buffer: Decimal = Decimal("0"),
    uncertainty_buffer: Decimal = Decimal("0"),
    minimum_economic_margin: Decimal = Decimal("0"),
) -> ActionValueLabel:
    """Compare executable LONG/SHORT opportunities with cash, with signed funding.

    Horizon end is decision index + horizon_steps, matching the v4 t+h convention;
    entry is t+1. A one-step horizon has the same entry/exit price and no price gain.
    """
    decision, future = _executable_path(tuple(observations), decision_index, horizon_steps)
    gross = canonical_result(future[-1].executable_price / future[0].executable_price - 1)
    half_execution = cost.execution_rate / 2
    long_entry = cost.long_entry_cost if cost.long_entry_cost is not None else half_execution
    long_exit = cost.long_exit_cost if cost.long_exit_cost is not None else half_execution
    short_entry = cost.short_entry_cost if cost.short_entry_cost is not None else half_execution
    short_exit = cost.short_exit_cost if cost.short_exit_cost is not None else half_execution
    long_funding = (
        cost.expected_funding_long if cost.expected_funding_long is not None else cost.funding_rate
    )
    short_funding = (
        cost.expected_funding_short
        if cost.expected_funding_short is not None
        else -cost.funding_rate
    )
    long_value = canonical_result(gross - long_entry - long_exit - long_funding - long_risk_buffer)
    short_value = canonical_result(
        -gross
        - short_entry
        - short_exit
        - short_funding
        - cost.borrow_rate
        - short_tail_risk_buffer
    )
    margin = canonical_result(max(long_value, short_value))
    action = DirectionClass.FLAT
    if margin > uncertainty_buffer + minimum_economic_margin and long_value != short_value:
        action = DirectionClass.UP if long_value > short_value else DirectionClass.DOWN
    return ActionValueLabel(
        decision_time=decision.available_time,
        earliest_execution_time=future[0].event_time,
        horizon_end_time=future[-1].event_time,
        gross_long_return=gross,
        gross_short_return=-gross,
        long_entry_cost=long_entry,
        long_exit_cost=long_exit,
        short_entry_cost=short_entry,
        short_exit_cost=short_exit,
        expected_funding_long=long_funding,
        expected_funding_short=short_funding,
        expected_borrow_short=cost.borrow_rate,
        long_risk_buffer=long_risk_buffer,
        short_tail_risk_buffer=short_tail_risk_buffer,
        uncertainty_buffer=uncertainty_buffer,
        minimum_economic_margin=minimum_economic_margin,
        net_value_long=long_value,
        net_value_short=short_value,
        best_action=action,
        action_margin=margin,
    )


def generate_return_path_label(
    *,
    observations: Iterable[PricePathObservation],
    decision_index: int,
    horizon_steps: int,
    cost: CostAssumption,
    risk_flat_threshold: Decimal,
    overlap_count: int = 1,
) -> ReturnPathLabel:
    values = tuple(observations)
    decision, future = _executable_path(values, decision_index, horizon_steps)
    if overlap_count < 1:
        raise ValueError("overlap count must be positive")
    if risk_flat_threshold < 0:
        raise ValueError("risk flat threshold must be non-negative")
    entry = future[0]
    action_values = generate_action_value_label(
        observations=values,
        decision_index=decision_index,
        horizon_steps=horizon_steps,
        cost=cost,
        long_risk_buffer=risk_flat_threshold,
        short_tail_risk_buffer=risk_flat_threshold,
    )
    path_returns = tuple(
        canonical_result(item.executable_price / entry.executable_price - Decimal("1"))
        for item in future
    )
    gross = path_returns[-1]
    total_cost = canonical_result(
        action_values.long_entry_cost
        + action_values.long_exit_cost
        + action_values.expected_funding_long
    )
    net = canonical_result(gross - total_cost)
    one_step_returns = tuple(
        _log_return(
            future[index].executable_price,
            entry.executable_price if index == 0 else future[index - 1].executable_price,
        )
        for index in range(1, len(future))
    )
    return ReturnPathLabel(
        label_id=f"action-return-v4:{entry.instrument_id}:{decision.available_time.isoformat()}:{horizon_steps}",
        instrument_id=entry.instrument_id,
        decision_time=decision.available_time,
        label_start_time=future[0].event_time,
        label_end_time=future[-1].event_time,
        horizon_steps=horizon_steps,
        gross_return=gross,
        total_cost_rate=total_cost,
        net_return=net,
        direction=action_values.best_action,
        q10_return=_quantile(path_returns, Decimal("0.1")),
        q50_return=_quantile(path_returns, Decimal("0.5")),
        q90_return=_quantile(path_returns, Decimal("0.9")),
        realized_volatility=_sample_std(one_step_returns),
        maximum_adverse_excursion=min(path_returns),
        maximum_favorable_excursion=max(path_returns),
        overlap_weight=canonical_result(Decimal("1") / Decimal(overlap_count)),
        cost_policy_version=cost.policy_version,
        source_dataset_ids=tuple(
            sorted({entry.source_dataset_id, *(item.source_dataset_id for item in future)})
        ),
    )


def generate_return_labels(
    *,
    observations: Iterable[PricePathObservation],
    horizon_steps: int,
    cost: CostAssumption,
    risk_flat_threshold: Decimal,
) -> tuple[ReturnPathLabel, ...]:
    values = tuple(observations)
    overlap_count = horizon_steps
    return tuple(
        generate_return_path_label(
            observations=values,
            decision_index=index,
            horizon_steps=horizon_steps,
            cost=cost,
            risk_flat_threshold=risk_flat_threshold,
            overlap_count=overlap_count,
        )
        for index in range(0, len(values) - horizon_steps)
    )


def generate_execution_label(
    *,
    label_id: str,
    decision_time: UtcDateTime,
    label_end_time: UtcDateTime,
    attempts: int,
    fills: int,
    requested_quantity: Decimal,
    filled_quantity: Decimal,
    slippage_bps: Decimal,
    adverse_selection_bps: Decimal,
    post_cancel_fill: bool,
    impact_bps: Decimal,
    recovery_seconds: Decimal,
    multi_leg_exposure_seconds: Decimal,
) -> ExecutionLabel:
    if attempts < 1 or fills < 0 or fills > attempts:
        raise ValueError("execution attempts/fills are inconsistent")
    if requested_quantity <= 0 or not Decimal("0") <= filled_quantity <= requested_quantity:
        raise ValueError("execution quantities are inconsistent")
    return ExecutionLabel(
        label_id=label_id,
        decision_time=decision_time,
        label_end_time=label_end_time,
        fill_probability=Decimal(fills) / Decimal(attempts),
        fill_ratio=filled_quantity / requested_quantity,
        slippage_bps=slippage_bps,
        adverse_selection_bps=adverse_selection_bps,
        post_cancel_fill=post_cancel_fill,
        impact_bps=impact_bps,
        recovery_seconds=recovery_seconds,
        multi_leg_exposure_seconds=multi_leg_exposure_seconds,
    )


def generate_event_impact_label(
    *,
    label_id: str,
    event_id: str,
    instrument_id: str,
    first_observed_time: UtcDateTime,
    label_end_time: UtcDateTime,
    gross_return: Decimal,
    cost: CostAssumption,
    pre_volatility: Decimal,
    post_volatility: Decimal,
    downside_return: Decimal,
    spread_before_bps: Decimal,
    spread_after_bps: Decimal,
    funding_before: Decimal,
    funding_after: Decimal,
    event_persisted: bool,
) -> EventImpactLabel:
    if pre_volatility < 0 or post_volatility < 0:
        raise ValueError("event volatility must be non-negative")
    return EventImpactLabel(
        label_id=label_id,
        event_id=event_id,
        instrument_id=instrument_id,
        first_observed_time=first_observed_time,
        label_end_time=label_end_time,
        net_return=canonical_result(gross_return - cost.total_rate),
        volatility_change=canonical_result(post_volatility - pre_volatility),
        downside_return=downside_return,
        spread_change_bps=canonical_result(spread_after_bps - spread_before_bps),
        funding_change=canonical_result(funding_after - funding_before),
        event_persisted=event_persisted,
    )
