"""Simple strategy candidates with explicit screening-only economic attribution."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import QualityState
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    UnitInterval,
    canonical_result,
)


class BaselineStrategyKind(StrEnum):
    CASH = "CASH"
    BUY_AND_HOLD = "BUY_AND_HOLD"
    SIMPLE_TREND = "SIMPLE_TREND"
    CROSS_SECTIONAL = "CROSS_SECTIONAL"
    FUNDING_BASIS = "FUNDING_BASIS"
    OFFICIAL_EVENT_RISK_OVERLAY = "OFFICIAL_EVENT_RISK_OVERLAY"
    CONSERVATIVE_EVENT = "CONSERVATIVE_EVENT"


class BaselineObservation(DomainModel):
    sample_id: str
    instrument_id: str
    decision_time: UtcDateTime
    realized_next_return: FiniteDecimal
    trend_score: FiniteDecimal = Decimal("0")
    cross_sectional_rank: UnitInterval = Decimal("0.5")
    funding_rate: FiniteDecimal = Decimal("0")
    basis: FiniteDecimal = Decimal("0")
    official_event: bool = False
    independent_source_count: int = 0
    event_novelty: UnitInterval = Decimal("0")
    event_stance: FiniteDecimal = Decimal("0")
    manipulation_risk: UnitInterval = Decimal("0")
    market_reflection: UnitInterval = Decimal("0")
    quality_state: QualityState = QualityState.GOOD
    cost_rate: NonNegativeDecimal = Decimal("0")


class StrategyTarget(DomainModel):
    sample_id: str
    instrument_id: str
    decision_time: UtcDateTime
    target_fraction: FiniteDecimal
    monitor_only: bool
    reason_code: str

    @model_validator(mode="after")
    def validate_target(self) -> StrategyTarget:
        if abs(self.target_fraction) > 1:
            raise ValueError("baseline target fraction must be within [-1, 1]")
        if self.monitor_only and self.target_fraction != 0:
            raise ValueError("monitor-only target cannot carry exposure")
        return self


class StrategyPeriodResult(DomainModel):
    sample_id: str
    target_fraction: FiniteDecimal
    gross_return: FiniteDecimal
    transaction_cost: NonNegativeDecimal
    net_return: FiniteDecimal

    @model_validator(mode="after")
    def validate_economics(self) -> StrategyPeriodResult:
        if self.net_return != canonical_result(self.gross_return - self.transaction_cost):
            raise ValueError("strategy period net return must conserve")
        return self


class StrategyScreeningResult(DomainModel):
    strategy: BaselineStrategyKind
    periods: tuple[StrategyPeriodResult, ...]
    gross_return: FiniteDecimal
    transaction_cost: NonNegativeDecimal
    net_return: FiniteDecimal
    turnover: NonNegativeDecimal
    authoritative_backtest_required: bool = True

    @model_validator(mode="after")
    def validate_totals(self) -> StrategyScreeningResult:
        if not self.periods:
            raise ValueError("strategy screening requires periods")
        if self.gross_return != canonical_result(
            sum((item.gross_return for item in self.periods), Decimal("0"))
        ):
            raise ValueError("strategy gross total differs from periods")
        if self.transaction_cost != canonical_result(
            sum((item.transaction_cost for item in self.periods), Decimal("0"))
        ):
            raise ValueError("strategy cost total differs from periods")
        if self.net_return != canonical_result(self.gross_return - self.transaction_cost):
            raise ValueError("strategy net total must conserve")
        return self


def _target(
    observation: BaselineObservation,
    *,
    fraction: Decimal,
    reason: str,
    monitor_only: bool = False,
) -> StrategyTarget:
    return StrategyTarget(
        sample_id=observation.sample_id,
        instrument_id=observation.instrument_id,
        decision_time=observation.decision_time,
        target_fraction=fraction,
        monitor_only=monitor_only,
        reason_code=reason,
    )


def generate_strategy_targets(
    strategy: BaselineStrategyKind,
    observations: Iterable[BaselineObservation],
    *,
    minimum_edge: Decimal = Decimal("0.001"),
) -> tuple[StrategyTarget, ...]:
    values = tuple(observations)
    output: list[StrategyTarget] = []
    for observation in values:
        if strategy is BaselineStrategyKind.CASH:
            output.append(_target(observation, fraction=Decimal("0"), reason="CASH"))
        elif strategy is BaselineStrategyKind.BUY_AND_HOLD:
            output.append(_target(observation, fraction=Decimal("1"), reason="HOLD"))
        elif strategy is BaselineStrategyKind.SIMPLE_TREND:
            fraction = (
                Decimal("1")
                if observation.trend_score > 0
                else Decimal("-1")
                if observation.trend_score < 0
                else Decimal("0")
            )
            output.append(_target(observation, fraction=fraction, reason="TREND_SIGN"))
        elif strategy is BaselineStrategyKind.CROSS_SECTIONAL:
            fraction = (
                Decimal("1")
                if observation.cross_sectional_rank >= Decimal("0.8")
                else Decimal("-1")
                if observation.cross_sectional_rank <= Decimal("0.2")
                else Decimal("0")
            )
            output.append(_target(observation, fraction=fraction, reason="ROBUST_RANK"))
        elif strategy is BaselineStrategyKind.FUNDING_BASIS:
            carry_edge = observation.funding_rate + observation.basis
            fraction = (
                Decimal("-1")
                if carry_edge > minimum_edge + observation.cost_rate
                else Decimal("1")
                if carry_edge < -(minimum_edge + observation.cost_rate)
                else Decimal("0")
            )
            output.append(_target(observation, fraction=fraction, reason="DELTA_HEDGE_LEG"))
        elif strategy is BaselineStrategyKind.OFFICIAL_EVENT_RISK_OVERLAY:
            active = observation.official_event and observation.quality_state is QualityState.GOOD
            output.append(
                _target(
                    observation,
                    fraction=Decimal("0"),
                    reason="REDUCE_POSITION" if active else "MONITOR_ONLY",
                    monitor_only=not active,
                )
            )
        else:
            corroborated = observation.official_event or observation.independent_source_count >= 2
            safe = (
                observation.quality_state is QualityState.GOOD
                and observation.manipulation_risk <= Decimal("0.2")
                and observation.market_reflection <= Decimal("0.5")
            )
            edge = abs(observation.event_stance) * observation.event_novelty
            eligible = corroborated and safe and edge > minimum_edge + observation.cost_rate
            fraction = (
                Decimal("0.25")
                if eligible and observation.event_stance > 0
                else Decimal("-0.25")
                if eligible and observation.event_stance < 0
                else Decimal("0")
            )
            output.append(
                _target(
                    observation,
                    fraction=fraction,
                    reason="CORROBORATED_LOW_RISK_EVENT" if eligible else "MONITOR_ONLY",
                    monitor_only=not eligible,
                )
            )
    return tuple(output)


def screen_strategy(
    strategy: BaselineStrategyKind,
    observations: Iterable[BaselineObservation],
    *,
    minimum_edge: Decimal = Decimal("0.001"),
) -> StrategyScreeningResult:
    values = tuple(observations)
    targets = generate_strategy_targets(strategy, values, minimum_edge=minimum_edge)
    if len(targets) != len(values) or not values:
        raise ValueError("strategy screening requires aligned observations")
    previous = Decimal("0")
    turnover = Decimal("0")
    periods: list[StrategyPeriodResult] = []
    for observation, target in zip(values, targets, strict=True):
        change = abs(target.target_fraction - previous)
        gross = canonical_result(target.target_fraction * observation.realized_next_return)
        cost = canonical_result(change * observation.cost_rate)
        periods.append(
            StrategyPeriodResult(
                sample_id=observation.sample_id,
                target_fraction=target.target_fraction,
                gross_return=gross,
                transaction_cost=cost,
                net_return=canonical_result(gross - cost),
            )
        )
        turnover += change
        previous = target.target_fraction
    gross_total = canonical_result(sum((item.gross_return for item in periods), Decimal("0")))
    cost_total = canonical_result(sum((item.transaction_cost for item in periods), Decimal("0")))
    return StrategyScreeningResult(
        strategy=strategy,
        periods=tuple(periods),
        gross_return=gross_total,
        transaction_cost=cost_total,
        net_return=canonical_result(gross_total - cost_total),
        turnover=canonical_result(turnover),
    )
