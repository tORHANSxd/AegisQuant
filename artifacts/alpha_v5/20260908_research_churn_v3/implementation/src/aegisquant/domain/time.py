"""UTC-only time semantics and injectable clocks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Protocol

from pydantic import AfterValidator


def ensure_utc(value: datetime) -> datetime:
    """Reject naive values and normalize aware values to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AQ-TIME-NAIVE: timezone-aware datetime required")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(ensure_utc)]


class Clock(Protocol):
    """Time source injected at processing boundaries."""

    def now(self) -> datetime:
        """Return a timezone-aware UTC instant."""
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Production clock with no import-time sampling."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Deterministic test and replay clock."""

    instant: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "instant", ensure_utc(self.instant))

    def now(self) -> datetime:
        return self.instant


def assert_point_in_time(*, available_time: datetime, decision_time: datetime) -> None:
    """Reject look-ahead access to facts unavailable at decision time."""
    available = ensure_utc(available_time)
    decision = ensure_utc(decision_time)
    if available > decision:
        raise ValueError("AQ-TIME-LOOKAHEAD: available_time exceeds decision_time")
