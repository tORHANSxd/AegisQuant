"""A fixed, causal funding baseline; no fitted model or access to future settlements."""

from __future__ import annotations

from statistics import median

from pydantic import Field

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal


class FundingObservation(DomainModel):
    settlement_time: UtcDateTime
    available_time: UtcDateTime
    rate: FiniteDecimal
    calendar_version: str = Field(min_length=1)


class FundingForecast(DomainModel):
    available_time: UtcDateTime
    expected_received_by_short: FiniteDecimal
    conservative_received_by_short: FiniteDecimal
    uncertainty: NonNegativeDecimal
    payments: int = Field(ge=1, le=12)
    observation_count: int = Field(ge=21)
    calendar_version: str
    history_sha256: str


def forecast_funding(
    observations: tuple[FundingObservation, ...],
    *,
    as_of: UtcDateTime,
    calendar_version: str,
    payments: int = 6,
) -> FundingForecast:
    if any(o.available_time > as_of or o.settlement_time > as_of for o in observations):
        raise ValueError("funding forecast cannot consume future settlements or availability")
    if any(o.available_time < o.settlement_time for o in observations):
        raise ValueError("realized funding cannot be known before settlement")
    selected = tuple(
        sorted(
            (o for o in observations if o.calendar_version == calendar_version),
            key=lambda o: o.settlement_time,
        )
    )[-21:]
    if len(selected) < 21 or len({o.settlement_time for o in selected}) != len(selected):
        raise ValueError(
            "funding forecast requires 21 distinct settled observations of one calendar"
        )
    rates = sorted(o.rate for o in selected)
    return FundingForecast(
        available_time=as_of,
        expected_received_by_short=median(rates) * payments,
        conservative_received_by_short=rates[2] * payments,
        uncertainty=(rates[18] - rates[2]) * payments / 2,
        payments=payments,
        observation_count=len(selected),
        calendar_version=calendar_version,
        history_sha256=canonical_sha256([o.model_dump(mode="json") for o in selected]),
    )
