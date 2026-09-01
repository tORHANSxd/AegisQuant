"""Point-in-time market, derivative, liquidity, and cross-sectional features."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal, localcontext
from typing import Annotated

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    PositiveDecimal,
    canonical_result,
)
from aegisquant.features.models import (
    FeatureDefinition,
    FeatureDType,
    FeatureEntity,
    FeatureParameter,
    FeatureValueRecord,
    FeatureVector,
)


class MarketObservation(DomainModel):
    instrument_id: str
    event_time: UtcDateTime
    available_time: UtcDateTime
    close: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    quote_volume: NonNegativeDecimal
    bid: PositiveDecimal | None = None
    ask: PositiveDecimal | None = None
    funding_rate: FiniteDecimal | None = None
    spot_price: PositiveDecimal | None = None
    perpetual_price: PositiveDecimal | None = None
    source_dataset_id: str

    @model_validator(mode="after")
    def validate_observation(self) -> MarketObservation:
        if self.high < self.low or not self.low <= self.close <= self.high:
            raise ValueError("market OHLC bounds are inconsistent")
        if (self.bid is None) != (self.ask is None):
            raise ValueError("bid and ask must be supplied together")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")
        if (self.spot_price is None) != (self.perpetual_price is None):
            raise ValueError("spot and perpetual prices must be supplied together")
        if self.available_time < self.event_time:
            raise ValueError("observation cannot be available before event time")
        return self


class MarketFeatureConfig(DomainModel):
    return_window: Annotated[int, Field(ge=1)] = 1
    trend_window: Annotated[int, Field(ge=2)] = 3
    volatility_window: Annotated[int, Field(ge=3)] = 4
    amihud_window: Annotated[int, Field(ge=2)] = 3
    frequency_seconds: Annotated[int, Field(gt=0)] = 60


def _definition(
    feature_id: str,
    *,
    description: str,
    unit: str,
    inputs: tuple[str, ...],
    minimum_history: int,
    frequency_seconds: int,
    parameter: tuple[str, str] | None = None,
    entity: FeatureEntity = FeatureEntity.INSTRUMENT,
) -> FeatureDefinition:
    parameters = (
        () if parameter is None else (FeatureParameter(name=parameter[0], value=parameter[1]),)
    )
    return FeatureDefinition(
        feature_id=feature_id,
        version="1.0.0",
        description=description,
        entity=entity,
        dtype=FeatureDType.FLOAT64,
        unit=unit,
        inputs=inputs,
        formula_reference=f"AegisQuant P07 {feature_id} v1",
        parameters=parameters,
        lookback_seconds=max(0, (minimum_history - 1) * frequency_seconds),
        minimum_history=minimum_history,
        frequency_seconds=frequency_seconds,
        normalization="none",
        missing_policy="explicit_missing_indicator",
        online_compatible=True,
        owner="research",
        tests=("tests/unit/features/test_market_features.py",),
    )


def market_feature_definitions(config: MarketFeatureConfig) -> tuple[FeatureDefinition, ...]:
    frequency = config.frequency_seconds
    return (
        _definition(
            "returns.log",
            description="Point-in-time logarithmic return",
            unit="log_return",
            inputs=("close",),
            minimum_history=config.return_window + 1,
            frequency_seconds=frequency,
            parameter=("window", str(config.return_window)),
        ),
        _definition(
            "trend.return",
            description="Trailing simple return trend",
            unit="return",
            inputs=("close",),
            minimum_history=config.trend_window,
            frequency_seconds=frequency,
            parameter=("window", str(config.trend_window)),
        ),
        _definition(
            "volatility.realized",
            description="Trailing sample standard deviation of log returns",
            unit="log_return_std",
            inputs=("close",),
            minimum_history=config.volatility_window,
            frequency_seconds=frequency,
            parameter=("window", str(config.volatility_window)),
        ),
        _definition(
            "liquidity.spread_bps",
            description="Quoted bid-ask spread over mid",
            unit="bps",
            inputs=("bid", "ask"),
            minimum_history=1,
            frequency_seconds=frequency,
        ),
        _definition(
            "liquidity.amihud",
            description="Trailing absolute return per quote notional",
            unit="return_per_quote",
            inputs=("close", "quote_volume"),
            minimum_history=config.amihud_window,
            frequency_seconds=frequency,
            parameter=("window", str(config.amihud_window)),
        ),
        _definition(
            "derivatives.funding",
            description="Point-in-time funding rate",
            unit="rate",
            inputs=("funding_rate",),
            minimum_history=1,
            frequency_seconds=frequency,
        ),
        _definition(
            "derivatives.funding_change",
            description="Change in point-in-time funding rate",
            unit="rate",
            inputs=("funding_rate",),
            minimum_history=2,
            frequency_seconds=frequency,
        ),
        _definition(
            "derivatives.basis",
            description="Spot-perpetual relative basis",
            unit="return",
            inputs=("spot_price", "perpetual_price"),
            minimum_history=1,
            frequency_seconds=frequency,
        ),
        _definition(
            "cross_section.rank",
            description="Point-in-time cross-sectional percentile rank",
            unit="percentile",
            inputs=("signal",),
            minimum_history=1,
            frequency_seconds=frequency,
            entity=FeatureEntity.CROSS_SECTION,
        ),
    )


def _log_return(current: Decimal, previous: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 34
        return canonical_result((current / previous).ln())


def _sample_std(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        raise ValueError("sample standard deviation requires two values")
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(
        len(values) - 1
    )
    with localcontext() as context:
        context.prec = 34
        return canonical_result(variance.sqrt())


class MarketFeatureCalculator:
    def __init__(self, config: MarketFeatureConfig) -> None:
        self.config = config
        self.definitions = market_feature_definitions(config)
        self._keys = {item.feature_id: item.qualified_id for item in self.definitions}
        self._history: dict[str, list[MarketObservation]] = defaultdict(list)

    def _calculate_at(self, history: tuple[MarketObservation, ...], index: int) -> FeatureVector:
        observation = history[index]
        values: dict[str, Decimal] = {}
        missing: list[str] = []

        return_key = self._keys["returns.log"]
        if index >= self.config.return_window:
            values[return_key] = _log_return(
                observation.close, history[index - self.config.return_window].close
            )
        else:
            missing.append(return_key)

        trend_key = self._keys["trend.return"]
        if index + 1 >= self.config.trend_window:
            first = history[index - self.config.trend_window + 1].close
            values[trend_key] = canonical_result(observation.close / first - Decimal("1"))
        else:
            missing.append(trend_key)

        volatility_key = self._keys["volatility.realized"]
        if index + 1 >= self.config.volatility_window:
            start = index - self.config.volatility_window + 1
            returns = tuple(
                _log_return(history[position].close, history[position - 1].close)
                for position in range(start + 1, index + 1)
            )
            values[volatility_key] = _sample_std(returns)
        else:
            missing.append(volatility_key)

        spread_key = self._keys["liquidity.spread_bps"]
        if observation.bid is not None and observation.ask is not None:
            mid = (observation.bid + observation.ask) / Decimal("2")
            values[spread_key] = canonical_result(
                (observation.ask - observation.bid) / mid * Decimal("10000")
            )
        else:
            missing.append(spread_key)

        amihud_key = self._keys["liquidity.amihud"]
        if index + 1 >= self.config.amihud_window:
            start = index - self.config.amihud_window + 1
            components: list[Decimal] = []
            for position in range(start + 1, index + 1):
                current = history[position]
                quote_notional = current.quote_volume * current.close
                if quote_notional <= 0:
                    continue
                components.append(
                    abs(_log_return(current.close, history[position - 1].close)) / quote_notional
                )
            if components:
                values[amihud_key] = canonical_result(
                    sum(components, Decimal("0")) / Decimal(len(components))
                )
            else:
                missing.append(amihud_key)
        else:
            missing.append(amihud_key)

        funding_key = self._keys["derivatives.funding"]
        if observation.funding_rate is None:
            missing.append(funding_key)
        else:
            values[funding_key] = observation.funding_rate

        funding_change_key = self._keys["derivatives.funding_change"]
        prior_funding = next(
            (
                history[position].funding_rate
                for position in range(index - 1, -1, -1)
                if history[position].funding_rate is not None
            ),
            None,
        )
        if observation.funding_rate is None or prior_funding is None:
            missing.append(funding_change_key)
        else:
            values[funding_change_key] = canonical_result(observation.funding_rate - prior_funding)

        basis_key = self._keys["derivatives.basis"]
        if observation.spot_price is None or observation.perpetual_price is None:
            missing.append(basis_key)
        else:
            values[basis_key] = canonical_result(
                observation.perpetual_price / observation.spot_price - Decimal("1")
            )

        return FeatureVector(
            entity_id=observation.instrument_id,
            event_time=observation.event_time,
            available_time=observation.available_time,
            values=tuple(
                FeatureValueRecord(feature_key=key, value=values[key]) for key in sorted(values)
            ),
            missing_flags=tuple(sorted(missing)),
            source_dataset_ids=(observation.source_dataset_id,),
        )

    def calculate_batch(
        self, observations: Iterable[MarketObservation]
    ) -> tuple[FeatureVector, ...]:
        grouped: dict[str, list[MarketObservation]] = defaultdict(list)
        for observation in observations:
            grouped[observation.instrument_id].append(observation)
        output: list[FeatureVector] = []
        for instrument_id in sorted(grouped):
            history = tuple(sorted(grouped[instrument_id], key=lambda item: item.available_time))
            if len({item.available_time for item in history}) != len(history):
                raise ValueError("market observations require unique available_time per instrument")
            output.extend(self._calculate_at(history, index) for index in range(len(history)))
        return tuple(sorted(output, key=lambda item: (item.available_time, item.entity_id)))

    def update(self, observation: MarketObservation) -> FeatureVector:
        history = self._history[observation.instrument_id]
        if history and observation.available_time <= history[-1].available_time:
            raise ValueError("incremental observations must have increasing available_time")
        history.append(observation)
        return self._calculate_at(tuple(history), len(history) - 1)


def assert_batch_incremental_parity(
    observations: Iterable[MarketObservation], config: MarketFeatureConfig
) -> tuple[FeatureVector, ...]:
    values = tuple(observations)
    batch = MarketFeatureCalculator(config).calculate_batch(values)
    incremental_calculator = MarketFeatureCalculator(config)
    incremental = tuple(
        incremental_calculator.update(item)
        for item in sorted(values, key=lambda item: (item.available_time, item.instrument_id))
    )
    incremental = tuple(sorted(incremental, key=lambda item: (item.available_time, item.entity_id)))
    if batch != incremental:
        raise ValueError("AQ-FEATURE-BATCH-INCREMENTAL-DIVERGENCE")
    return batch


def cross_sectional_rank(
    *,
    as_of_time: UtcDateTime,
    signals: dict[str, Decimal],
    source_dataset_ids: tuple[str, ...],
    definition: FeatureDefinition,
) -> tuple[FeatureVector, ...]:
    if definition.feature_id != "cross_section.rank":
        raise ValueError("cross-sectional rank requires its registered definition")
    if len(signals) < 2:
        raise ValueError("cross-sectional rank requires at least two instruments")
    ordered_values = sorted(set(signals.values()))
    denominator = Decimal(len(ordered_values) - 1) if len(ordered_values) > 1 else Decimal("1")
    rank_by_value = {
        value: Decimal(index) / denominator for index, value in enumerate(ordered_values)
    }
    return tuple(
        FeatureVector(
            entity_id=instrument_id,
            event_time=as_of_time,
            available_time=as_of_time,
            values=(
                FeatureValueRecord(
                    feature_key=definition.qualified_id,
                    value=canonical_result(rank_by_value[signals[instrument_id]]),
                ),
            ),
            source_dataset_ids=tuple(sorted(set(source_dataset_ids))),
        )
        for instrument_id in sorted(signals)
    )
