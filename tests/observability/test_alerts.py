from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, cast

import pytest

from aegisquant.observability.alerts import (
    AlertDispatcher,
    AlertEvent,
    Incident,
    IncidentState,
    MaintenanceWindow,
    Severity,
    WebhookChannel,
)


class Receiver(BaseHTTPRequestHandler):
    payloads: ClassVar[list[dict[str, str]]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        payload = cast("dict[str, str]", json.loads(self.rfile.read(length)))
        type(self).payloads.append(payload)
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def event(severity: Severity, *, rule: str = "RECONCILIATION_FAILURE") -> AlertEvent:
    return AlertEvent(
        rule_name=rule,
        severity=severity,
        environment="paper",
        scope="accounting",
        summary="authoritative reconciliation mismatch",
        correlation_id="corr-alert-001",
        starts_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


def test_sev0_reaches_real_loopback_receiver_and_is_deduplicated() -> None:
    Receiver.payloads.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        now = datetime(2026, 9, 2, tzinfo=UTC)
        channel = WebhookChannel(
            name="operator",
            url=f"http://127.0.0.1:{server.server_port}/alert",
        )
        dispatcher = AlertDispatcher(
            channels={"operator": channel},
            routes={Severity.SEV0: ("operator",), Severity.SEV1: ("operator",)},
            clock=lambda: now,
        )
        first = dispatcher.dispatch(event(Severity.SEV0))
        second = dispatcher.dispatch(event(Severity.SEV0))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert first.outcome == "delivered"
    assert second.outcome == "deduplicated"
    assert len(Receiver.payloads) == 1
    assert Receiver.payloads[0]["severity"] == "SEV0"
    assert len(Receiver.payloads[0]["fingerprint"]) == 64


def test_maintenance_suppresses_low_severity_but_never_sev0() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    delivered: list[str] = []

    def sender(url: str, payload: dict[str, str], timeout: float) -> int:
        del url, timeout
        delivered.append(payload["severity"])
        return 204

    channel = WebhookChannel(name="operator", url="https://alerts.example.test/hook", sender=sender)
    dispatcher = AlertDispatcher(
        channels={"operator": channel},
        routes={Severity.SEV0: ("operator",), Severity.SEV2: ("operator",)},
        clock=lambda: now,
    )
    dispatcher.set_maintenance(
        (
            MaintenanceWindow(
                name="database maintenance",
                starts_at=now - timedelta(minutes=1),
                ends_at=now + timedelta(minutes=5),
                scopes=frozenset({"accounting"}),
            ),
        )
    )
    low = dispatcher.dispatch(event(Severity.SEV2, rule="DATABASE_FAILURE"))
    critical = dispatcher.dispatch(event(Severity.SEV0))
    assert low.outcome == "maintenance_suppressed"
    assert critical.outcome == "delivered"
    assert delivered == ["SEV0"]


def test_incident_lifecycle_is_strict_and_audited() -> None:
    incident = Incident("incident-p16-001", Severity.SEV1)
    at = datetime(2026, 9, 2, tzinfo=UTC)
    for target in (
        IncidentState.ACKNOWLEDGED,
        IncidentState.MITIGATING,
        IncidentState.MONITORING,
        IncidentState.RESOLVED,
        IncidentState.POSTMORTEM_REQUIRED,
        IncidentState.CLOSED,
    ):
        incident.transition(target, actor="operator-1", at=at)
    assert incident.state is IncidentState.CLOSED
    assert len(incident.history) == 6
    with pytest.raises(ValueError, match="invalid incident transition"):
        incident.transition(IncidentState.OPEN, actor="operator-1", at=at)


def test_webhook_rejects_plaintext_remote_and_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        WebhookChannel(name="bad", url="http://example.com/hook")
    credential_url = "https://user:" + "fixture-passphrase" + "@example.com/hook"
    with pytest.raises(ValueError, match="credentials"):
        WebhookChannel(name="bad", url=credential_url)
