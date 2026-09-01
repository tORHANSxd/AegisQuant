"""Deterministic generators for return, execution, and event-impact labels."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, localcontext

from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.labels.models import (
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
    if horizon_steps < 1:
        raise ValueError("label horizon must be positive")
    if decision_index < 0 or decision_index + horizon_steps >= len(values):
        raise IndexError("label horizon exceeds price path")
    if overlap_count < 1:
        raise ValueError("overlap count must be positive")
    if risk_flat_threshold < 0:
        raise ValueError("risk flat threshold must be non-negative")
    entry = values[decision_index]
    future = values[decision_index + 1 : decision_index + horizon_steps + 1]
    if any(item.instrument_id != entry.instrument_id for item in future):
        raise ValueError("label path cannot mix instruments")
    if any(
        future[index].available_time
        <= (entry.available_time if index == 0 else future[index - 1].available_time)
        for index in range(len(future))
    ):
        raise ValueError("label observations must be strictly increasing and future available")

    path_returns = tuple(
        canonical_result(item.executable_price / entry.executable_price - Decimal("1"))
        for item in future
    )
    gross = path_returns[-1]
    net = canonical_result(gross - cost.total_rate)
    flat_band = abs(cost.total_rate) + risk_flat_threshold
    direction = (
        DirectionClass.UP
        if net > flat_band
        else DirectionClass.DOWN
        if net < -flat_band
        else DirectionClass.FLAT
    )
    one_step_returns = tuple(
        _log_return(
            future[index].executable_price,
            entry.executable_price if index == 0 else future[index - 1].executable_price,
        )
        for index in range(len(future))
    )
    return ReturnPathLabel(
        label_id=f"net-return:{entry.instrument_id}:{entry.available_time.isoformat()}:{horizon_steps}",
        instrument_id=entry.instrument_id,
        decision_time=entry.available_time,
        label_start_time=future[0].available_time,
        label_end_time=future[-1].available_time,
        horizon_steps=horizon_steps,
        gross_return=gross,
        total_cost_rate=cost.total_rate,
        net_return=net,
        direction=direction,
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
