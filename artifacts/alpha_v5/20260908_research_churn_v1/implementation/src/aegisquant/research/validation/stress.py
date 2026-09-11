"""Cost, latency, engagement, parameter, and point-in-time regime stresses."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import EngagementSnapshot
from aegisquant.domain.time import UtcDateTime, assert_point_in_time
from aegisquant.domain.values import FiniteDecimal, PositiveDecimal, canonical_result


class Regime(StrEnum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    HIGH_LIQUIDITY = "HIGH_LIQUIDITY"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    POSITIVE_FUNDING_CROWDING = "POSITIVE_FUNDING_CROWDING"
    NEGATIVE_FUNDING_CROWDING = "NEGATIVE_FUNDING_CROWDING"
    WEEKEND = "WEEKEND"
    WEEKDAY = "WEEKDAY"
    MAJOR_EVENT = "MAJOR_EVENT"
    NORMAL_PERIOD = "NORMAL_PERIOD"
    VENUE_INCIDENT = "VENUE_INCIDENT"
    STABLECOIN_STRESS = "STABLECOIN_STRESS"


class EconomicPeriod(DomainModel):
    period_id: str
    decision_time: UtcDateTime
    gross_return: FiniteDecimal
    base_cost: FiniteDecimal
    net_return: FiniteDecimal

    @model_validator(mode="after")
    def validate_economics(self) -> EconomicPeriod:
        if self.net_return != canonical_result(self.gross_return - self.base_cost):
            raise ValueError("period net return must conserve gross minus cost")
        return self


class CostStressResult(DomainModel):
    multiplier: PositiveDecimal
    gross_return: FiniteDecimal
    stressed_cost: FiniteDecimal
    net_return: FiniteDecimal


def apply_cost_stress(
    periods: Iterable[EconomicPeriod],
    *,
    multipliers: tuple[Decimal, ...] = (Decimal("1"), Decimal("1.5"), Decimal("2")),
) -> tuple[CostStressResult, ...]:
    values = tuple(periods)
    if not values:
        raise ValueError("cost stress requires economic periods")
    gross = sum((item.gross_return for item in values), Decimal("0"))
    cost = sum((item.base_cost for item in values), Decimal("0"))
    return tuple(
        CostStressResult(
            multiplier=multiplier,
            gross_return=canonical_result(gross),
            stressed_cost=canonical_result(cost * multiplier),
            net_return=canonical_result(gross - cost * multiplier),
        )
        for multiplier in multipliers
    )


class EventLatencyScenario(DomainModel):
    delay_seconds: int
    original_available_time: UtcDateTime
    stressed_available_time: UtcDateTime


def event_latency_scenarios(
    available_time: UtcDateTime,
    *,
    delays: tuple[int, ...] = (0, 5, 30, 120, 600),
) -> tuple[EventLatencyScenario, ...]:
    if any(value < 0 for value in delays) or tuple(sorted(set(delays))) != delays:
        raise ValueError("event latency delays must be unique, sorted, and non-negative")
    return tuple(
        EventLatencyScenario(
            delay_seconds=delay,
            original_available_time=available_time,
            stressed_available_time=available_time + timedelta(seconds=delay),
        )
        for delay in delays
    )


def engagement_as_of_with_delay(
    snapshots: Iterable[EngagementSnapshot],
    *,
    decision_time: UtcDateTime,
    delay_seconds: int,
) -> EngagementSnapshot | None:
    if delay_seconds < 0:
        raise ValueError("engagement delay cannot be negative")
    candidates = tuple(
        item
        for item in snapshots
        if item.observed_time <= decision_time
        and item.available_time + timedelta(seconds=delay_seconds) <= decision_time
    )
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: (item.available_time, item.observed_time))
    assert_point_in_time(
        available_time=selected.available_time + timedelta(seconds=delay_seconds),
        decision_time=decision_time,
    )
    return selected


def parameter_perturbations(
    parameters: dict[str, Decimal],
    *,
    fractions: tuple[Decimal, ...] = (
        Decimal("-0.1"),
        Decimal("-0.05"),
        Decimal("0.05"),
        Decimal("0.1"),
    ),
) -> tuple[dict[str, Decimal], ...]:
    if not parameters or any(abs(value) >= 1 for value in fractions):
        raise ValueError(
            "parameter perturbation requires parameters and fractional changes below 100%"
        )
    output: list[dict[str, Decimal]] = []
    for name in sorted(parameters):
        for fraction in fractions:
            candidate = dict(parameters)
            candidate[name] = canonical_result(parameters[name] * (Decimal("1") + fraction))
            output.append(candidate)
    return tuple(output)


class RegimeObservation(DomainModel):
    regime: Regime
    event_time: UtcDateTime
    available_time: UtcDateTime

    @model_validator(mode="after")
    def validate_time(self) -> RegimeObservation:
        if self.available_time < self.event_time:
            raise ValueError("regime cannot be available before observation")
        return self


class RegimeSlice(DomainModel):
    regime: Regime
    observations: int
    gross_return: FiniteDecimal
    cost: FiniteDecimal
    net_return: FiniteDecimal


def point_in_time_regime_slices(
    periods: Iterable[EconomicPeriod], regimes: Iterable[RegimeObservation]
) -> tuple[RegimeSlice, ...]:
    period_values = tuple(periods)
    regime_values = tuple(regimes)
    grouped: dict[Regime, list[EconomicPeriod]] = {}
    for period in period_values:
        candidates = tuple(
            item for item in regime_values if item.available_time <= period.decision_time
        )
        if not candidates:
            continue
        selected = max(candidates, key=lambda item: (item.available_time, item.event_time))
        assert_point_in_time(
            available_time=selected.available_time, decision_time=period.decision_time
        )
        grouped.setdefault(selected.regime, []).append(period)
    return tuple(
        RegimeSlice(
            regime=regime,
            observations=len(grouped[regime]),
            gross_return=canonical_result(
                sum((item.gross_return for item in grouped[regime]), Decimal("0"))
            ),
            cost=canonical_result(sum((item.base_cost for item in grouped[regime]), Decimal("0"))),
            net_return=canonical_result(
                sum((item.net_return for item in grouped[regime]), Decimal("0"))
            ),
        )
        for regime in sorted(grouped, key=lambda item: item.value)
    )
