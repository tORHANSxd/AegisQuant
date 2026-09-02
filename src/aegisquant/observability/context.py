"""Correlation context shared by logs and traces, never by metric identifiers."""

from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final
from uuid import uuid4

SAFE_IDENTIFIER: Final = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _checked(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded opaque identifier")
    return value


@dataclass(frozen=True, slots=True)
class TelemetryContext:
    """Request or event identity retained only in logs and spans."""

    correlation_id: str
    event_type: str
    account_scope: str | None = None
    strategy_id: str | None = None
    model_version_id: str | None = None
    order_intent_id: str | None = None

    def __post_init__(self) -> None:
        _checked(self.correlation_id, "correlation_id")
        _checked(self.event_type, "event_type")
        _checked(self.account_scope, "account_scope")
        _checked(self.strategy_id, "strategy_id")
        _checked(self.model_version_id, "model_version_id")
        _checked(self.order_intent_id, "order_intent_id")

    @classmethod
    def create(cls, *, event_type: str, correlation_id: str | None = None) -> TelemetryContext:
        return cls(correlation_id=correlation_id or uuid4().hex, event_type=event_type)


_CURRENT: ContextVar[TelemetryContext | None] = ContextVar(
    "aegisquant_telemetry_context", default=None
)


def current_context() -> TelemetryContext | None:
    """Return the active context without creating an implicit identity."""
    return _CURRENT.get()


@contextmanager
def correlation_scope(context: TelemetryContext) -> Generator[TelemetryContext]:
    """Bind one context for a bounded operation and always restore the prior value."""
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)
