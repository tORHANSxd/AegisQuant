"""Append-only source-compromise state with point-in-time replay."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from aegisquant.domain.identifiers import SourceId
from aegisquant.domain.time import ensure_utc
from aegisquant.truth.contracts import SourceCompromiseEvent, SourceCompromiseStatus


class SourceCompromiseStore:
    """Track authentic-but-compromised sources without rewriting identity history."""

    def __init__(self) -> None:
        self._history: dict[str, list[SourceCompromiseEvent]] = defaultdict(list)
        self._events: dict[str, SourceCompromiseEvent] = {}

    def apply(self, event: SourceCompromiseEvent) -> None:
        existing = self._events.get(str(event.event_id))
        if existing is not None:
            if existing != event:
                raise ValueError("AQ-TRUTH-SOURCE-COMPROMISE-EVENT-ID-CONFLICT")
            return
        history = self._history[str(event.source_id)]
        expected_version = len(history) + 1
        if event.version != expected_version:
            raise ValueError("AQ-TRUTH-SOURCE-COMPROMISE-VERSION-GAP")
        expected_predecessor = history[-1].event_id if history else None
        if event.previous_event_id != expected_predecessor:
            raise ValueError("AQ-TRUTH-SOURCE-COMPROMISE-PREDECESSOR-MISMATCH")
        if history and event.available_at < history[-1].available_at:
            raise ValueError("AQ-TRUTH-SOURCE-COMPROMISE-TIME-REGRESSION")
        if event.status is SourceCompromiseStatus.RECOVERED and (
            not history
            or history[-1].status
            not in {SourceCompromiseStatus.SUSPECTED, SourceCompromiseStatus.COMPROMISED}
        ):
            raise ValueError("AQ-TRUTH-SOURCE-RECOVERY-WITHOUT-COMPROMISE")
        if (
            history
            and event.status is SourceCompromiseStatus.NORMAL
            and history[-1].status
            in {SourceCompromiseStatus.SUSPECTED, SourceCompromiseStatus.COMPROMISED}
        ):
            raise ValueError("AQ-TRUTH-SOURCE-COMPROMISE-MUST-RECOVER-BEFORE-NORMAL")
        history.append(event)
        self._events[str(event.event_id)] = event

    def history(self, source_id: SourceId) -> tuple[SourceCompromiseEvent, ...]:
        return tuple(self._history.get(str(source_id), ()))

    def as_of(
        self, source_id: SourceId, *, decision_time: datetime
    ) -> SourceCompromiseEvent | None:
        decision = ensure_utc(decision_time)
        visible = [
            event
            for event in self._history.get(str(source_id), ())
            if event.effective_at <= decision
            and event.observed_at <= decision
            and event.available_at <= decision
        ]
        return (
            max(visible, key=lambda event: (event.available_at, event.version)) if visible else None
        )
