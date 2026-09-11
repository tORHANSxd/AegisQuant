"""Liquidity/history eligibility on the existing point-in-time membership snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal
from aegisquant.research.datasets.universe import PointInTimeUniverse, UniverseSnapshot


class LiquidityObservation(DomainModel):
    instrument_id: str
    window_start: UtcDateTime
    window_end: UtcDateTime
    available_time: UtcDateTime
    complete_history_4h_bars: int = Field(ge=0)
    trailing_quote_volume: NonNegativeDecimal
    source_sha256: str

    @model_validator(mode="after")
    def valid_window(self) -> LiquidityObservation:
        from aegisquant.data.hashing import ensure_sha256

        ensure_sha256(self.source_sha256, field_name="liquidity source hash")
        if self.window_end - self.window_start != timedelta(days=30):
            raise ValueError("liquidity requires an explicit trailing 30-day window")
        if self.available_time < self.window_end:
            raise ValueError("liquidity cannot be available before its window ends")
        return self


def eligible_universe_at(
    universe: PointInTimeUniverse,
    observations: Iterable[LiquidityObservation],
    *,
    decision_time: UtcDateTime,
    minimum_quote_volume: Decimal,
    minimum_history_bars: int = 240,
    maximum_age: timedelta = timedelta(hours=4),
) -> tuple[UniverseSnapshot, tuple[str, ...]]:
    """Absent/stale liquidity fails closed; future delisting revisions stay invisible."""
    if (
        not minimum_quote_volume.is_finite()
        or minimum_quote_volume < 0
        or minimum_history_bars < 1
        or maximum_age <= timedelta(0)
    ):
        raise ValueError("invalid preregistered universe eligibility limits")
    snapshot = universe.snapshot(as_of_time=decision_time)
    latest: dict[str, LiquidityObservation] = {}
    for row in observations:
        if row.available_time > decision_time or row.window_end > decision_time:
            continue
        previous = latest.get(row.instrument_id)
        if (
            previous is not None
            and (row.window_end, row.available_time)
            == (previous.window_end, previous.available_time)
            and row != previous
        ):
            raise ValueError("conflicting point-in-time liquidity observations")
        if previous is None or (row.window_end, row.available_time) > (
            previous.window_end,
            previous.available_time,
        ):
            latest[row.instrument_id] = row
    eligible = tuple(
        instrument
        for instrument in snapshot.instrument_ids
        if (row := latest.get(instrument)) is not None
        and decision_time - row.window_end <= maximum_age
        and row.complete_history_4h_bars >= minimum_history_bars
        and row.trailing_quote_volume >= minimum_quote_volume
    )
    return snapshot, eligible
