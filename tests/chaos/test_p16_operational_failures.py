from __future__ import annotations

from datetime import UTC, datetime

from aegisquant.observability.alerts import (
    AlertDispatcher,
    AlertEvent,
    Severity,
    WebhookChannel,
)
from aegisquant.observability.tracing import TracingRuntime


def test_alert_channel_timeout_fails_closed_and_remains_retryable() -> None:
    attempts = 0

    def timeout_sender(url: str, payload: dict[str, str], timeout: float) -> int:
        nonlocal attempts
        del url, payload, timeout
        attempts += 1
        raise TimeoutError("injected channel timeout")

    now = datetime(2026, 9, 2, tzinfo=UTC)
    dispatcher = AlertDispatcher(
        channels={
            "operator": WebhookChannel(
                name="operator",
                url="https://alerts.example.test/hook",
                sender=timeout_sender,
            )
        },
        routes={Severity.SEV0: ("operator",)},
        clock=lambda: now,
    )
    alert = AlertEvent(
        rule_name="LEDGER_IMBALANCE",
        severity=Severity.SEV0,
        environment="paper",
        scope="accounting",
        summary="injected ledger alert",
        correlation_id="corr-chaos-alert",
        starts_at=now,
    )
    assert dispatcher.dispatch(alert).outcome == "failed"
    assert dispatcher.dispatch(alert).outcome == "failed"
    assert attempts == 2


def test_trace_exporter_configuration_failure_cannot_enable_network_fallback() -> None:
    try:
        TracingRuntime(endpoint="http://169.254.169.254/v1/traces")
    except ValueError as error:
        assert "restricted" in str(error)
    else:
        raise AssertionError("metadata-service OTLP endpoint was accepted")
