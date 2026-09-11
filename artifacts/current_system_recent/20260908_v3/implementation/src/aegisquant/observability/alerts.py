"""Deterministic alert routing, deduplication, maintenance, and incident lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final
from urllib.parse import urlparse

import httpx

RULE_NAME: Final = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
SCOPE: Final = re.compile(r"^[a-z0-9._:-]{1,64}$")


class Severity(StrEnum):
    SEV0 = "SEV0"
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"


class IncidentState(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    MITIGATING = "MITIGATING"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    POSTMORTEM_REQUIRED = "POSTMORTEM_REQUIRED"
    CLOSED = "CLOSED"


ALLOWED_TRANSITIONS: Final[dict[IncidentState, frozenset[IncidentState]]] = {
    IncidentState.OPEN: frozenset({IncidentState.ACKNOWLEDGED}),
    IncidentState.ACKNOWLEDGED: frozenset({IncidentState.MITIGATING}),
    IncidentState.MITIGATING: frozenset({IncidentState.MONITORING}),
    IncidentState.MONITORING: frozenset({IncidentState.MITIGATING, IncidentState.RESOLVED}),
    IncidentState.RESOLVED: frozenset({IncidentState.POSTMORTEM_REQUIRED, IncidentState.CLOSED}),
    IncidentState.POSTMORTEM_REQUIRED: frozenset({IncidentState.CLOSED}),
    IncidentState.CLOSED: frozenset[IncidentState](),
}


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AlertEvent:
    rule_name: str
    severity: Severity
    environment: str
    scope: str
    summary: str
    correlation_id: str
    starts_at: datetime

    def __post_init__(self) -> None:
        if RULE_NAME.fullmatch(self.rule_name) is None:
            raise ValueError("alert rule_name must be a bounded constant")
        if self.environment not in {"paper", "shadow", "testnet", "canary"}:
            raise ValueError("alert environment must be non-Live")
        if SCOPE.fullmatch(self.scope) is None:
            raise ValueError("alert scope must be a bounded aggregate")
        if not self.summary or len(self.summary) > 512:
            raise ValueError("alert summary must be present and bounded")
        if SCOPE.fullmatch(self.correlation_id) is None:
            raise ValueError("correlation_id must be a bounded opaque identifier")
        object.__setattr__(self, "starts_at", _utc(self.starts_at, "starts_at"))

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "rule_name": self.rule_name,
                "severity": self.severity.value,
                "environment": self.environment,
                "scope": self.scope,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    def notification_payload(self) -> dict[str, str]:
        return {
            "schema_version": "aegisquant-alert-v1",
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "environment": self.environment,
            "scope": self.scope,
            "summary": self.summary,
            "correlation_id": self.correlation_id,
            "starts_at": self.starts_at.isoformat().replace("+00:00", "Z"),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    name: str
    starts_at: datetime
    ends_at: datetime
    scopes: frozenset[str]

    def __post_init__(self) -> None:
        starts = _utc(self.starts_at, "starts_at")
        ends = _utc(self.ends_at, "ends_at")
        if starts >= ends or ends - starts > timedelta(days=7):
            raise ValueError("maintenance window must be positive and no longer than seven days")
        if not self.scopes or any(SCOPE.fullmatch(item) is None for item in self.scopes):
            raise ValueError("maintenance window requires bounded scopes")
        object.__setattr__(self, "starts_at", starts)
        object.__setattr__(self, "ends_at", ends)

    def suppresses(self, event: AlertEvent, at: datetime) -> bool:
        now = _utc(at, "at")
        return (
            event.severity in {Severity.SEV2, Severity.SEV3}
            and event.scope in self.scopes
            and self.starts_at <= now < self.ends_at
        )


Sender = Callable[[str, dict[str, str], float], int]


def _http_sender(url: str, payload: dict[str, str], timeout_seconds: float) -> int:
    with httpx.Client(follow_redirects=False, timeout=timeout_seconds, trust_env=False) as client:
        response = client.post(url, json=payload, headers={"User-Agent": "AegisQuant-Alert/3.1"})
    return response.status_code


@dataclass(frozen=True, slots=True)
class WebhookChannel:
    name: str
    url: str
    timeout_seconds: float = 2.0
    sender: Sender = field(default=_http_sender, repr=False, compare=False)

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("webhook URL cannot contain credentials, query, or fragment")
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("webhook must use HTTPS, except for a loopback contract receiver")
        if not parsed.hostname or not 0.1 <= self.timeout_seconds <= 10.0:
            raise ValueError("invalid webhook host or timeout")

    def send(self, event: AlertEvent) -> bool:
        try:
            status = self.sender(self.url, event.notification_payload(), self.timeout_seconds)
        except (httpx.HTTPError, OSError, TimeoutError):
            return False
        return 200 <= status < 300


@dataclass(frozen=True, slots=True)
class DispatchResult:
    fingerprint: str
    outcome: str
    attempted_channels: tuple[str, ...]
    delivered_channels: tuple[str, ...]


class AlertDispatcher:
    """Worker-side delivery with bounded in-memory deduplication."""

    def __init__(
        self,
        *,
        channels: Mapping[str, WebhookChannel],
        routes: Mapping[Severity, tuple[str, ...]],
        deduplication_window: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not timedelta(seconds=1) <= deduplication_window <= timedelta(hours=24):
            raise ValueError("deduplication window is outside the safe range")
        for severity, names in routes.items():
            if severity in {Severity.SEV0, Severity.SEV1} and not names:
                raise ValueError(f"{severity.value} must have at least one configured channel")
            missing = set(names) - set(channels)
            if missing:
                raise ValueError(f"alert route references unknown channels: {sorted(missing)}")
        self._channels = dict(channels)
        self._routes = dict(routes)
        self._window = deduplication_window
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_delivery: dict[str, datetime] = {}
        self._maintenance: tuple[MaintenanceWindow, ...] = ()

    def set_maintenance(self, windows: tuple[MaintenanceWindow, ...]) -> None:
        self._maintenance = windows

    def dispatch(self, event: AlertEvent) -> DispatchResult:
        now = _utc(self._clock(), "clock")
        if any(window.suppresses(event, now) for window in self._maintenance):
            return DispatchResult(event.fingerprint, "maintenance_suppressed", (), ())
        previous = self._last_delivery.get(event.fingerprint)
        if previous is not None and now - previous < self._window:
            return DispatchResult(event.fingerprint, "deduplicated", (), ())
        channel_names = self._routes.get(event.severity, ())
        delivered = tuple(name for name in channel_names if self._channels[name].send(event))
        if delivered:
            self._last_delivery[event.fingerprint] = now
        outcome = "delivered" if len(delivered) == len(channel_names) and delivered else "failed"
        return DispatchResult(event.fingerprint, outcome, channel_names, delivered)


def _empty_history() -> list[tuple[str, str, str]]:
    return []


@dataclass(slots=True)
class Incident:
    incident_id: str
    severity: Severity
    state: IncidentState = IncidentState.OPEN
    history: list[tuple[str, str, str]] = field(default_factory=_empty_history)

    def transition(self, target: IncidentState, *, actor: str, at: datetime) -> None:
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid incident transition: {self.state.value} -> {target.value}")
        if SCOPE.fullmatch(actor) is None:
            raise ValueError("incident actor must be a bounded identifier")
        occurred = _utc(at, "at").isoformat().replace("+00:00", "Z")
        self.history.append((occurred, actor, target.value))
        self.state = target
