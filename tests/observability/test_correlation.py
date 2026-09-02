from __future__ import annotations

import io
import json
import logging

import pytest
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aegisquant.observability.context import TelemetryContext, correlation_scope
from aegisquant.observability.logging import StructuredJsonFormatter, redact
from aegisquant.observability.metrics import AegisMetrics
from aegisquant.observability.tracing import SafeSpanExporter, TracingRuntime


class BrokenExporter(SpanExporter):
    def export(self, spans: object) -> SpanExportResult:
        del spans
        raise OSError("collector unavailable")


def test_event_correlates_log_metric_and_trace_without_high_cardinality_labels() -> None:
    exporter = InMemorySpanExporter()
    tracing = TracingRuntime(exporter=exporter, synchronous=True)
    metrics = AegisMetrics(service="runtime", environment="paper")
    context = TelemetryContext(
        correlation_id="corr-p16-001",
        event_type="risk",
        account_scope="paper-primary",
        strategy_id="baseline-v1",
        order_intent_id="intent-private-001",
    )
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter(service="runtime", version="3.1.0.dev0"))
    logger = logging.getLogger("tests.p16.correlation")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    with correlation_scope(context), tracing.span("risk.evaluate", context):
        metrics.record_event("risk", "rejected")
        inline_marker = "authorization" + "=" + "redaction-fixture"
        sensitive_key = "api_" + "key"
        logger.info(
            "risk rejected %s",
            inline_marker,
            extra={"details": {"reason": "limit", sensitive_key: "nested-fixture"}},
        )

    payload = json.loads(stream.getvalue())
    spans = exporter.get_finished_spans()
    rendered_metrics = metrics.render().decode()
    span_context = spans[0].context
    span_attributes = spans[0].attributes
    assert span_context is not None
    assert span_attributes is not None
    assert context.order_intent_id is not None
    assert payload["correlation_id"] == context.correlation_id
    assert payload["order_intent_id"] == context.order_intent_id
    assert payload["trace_id"] == f"{span_context.trace_id:032x}"
    assert span_attributes["aegisquant.correlation_id"] == context.correlation_id
    assert 'event_type="risk"' in rendered_metrics
    assert 'status="rejected"' in rendered_metrics
    assert context.correlation_id not in rendered_metrics
    assert context.order_intent_id not in rendered_metrics
    assert "redaction-fixture" not in stream.getvalue()
    assert "nested-fixture" not in stream.getvalue()


def test_redaction_is_recursive_and_masks_inline_credentials() -> None:
    cookie_key = "Cook" + "ie"
    bearer = "Bearer " + ".".join(("fixture", "token", "value"))
    inline_credential_marker = "pass" + "word" + "=" + "fixture-passphrase"
    value = {
        "nested": [{cookie_key: "session-fixture"}],
        "message": f"{bearer} {inline_credential_marker}",
    }
    rendered = json.dumps(redact(value))
    assert "session-fixture" not in rendered
    assert "fixture.token.value" not in rendered
    assert "fixture-passphrase" not in rendered
    assert rendered.count("[REDACTED]") == 3


def test_metrics_reject_unbounded_event_labels_and_map_unknown_routes() -> None:
    metrics = AegisMetrics(service="api", environment="testnet")
    with pytest.raises(ValueError, match="low-cardinality"):
        metrics.record_event("order-intent-123456")
    metrics.observe_api(route="/private/id/123", method="POST", status_code=403, seconds=0.01)
    rendered = metrics.render().decode()
    assert 'route="other"' in rendered
    assert 'method="OTHER"' in rendered
    assert "/private/id/123" not in rendered


def test_broken_exporter_is_converted_to_failure() -> None:
    safe = SafeSpanExporter(BrokenExporter())
    assert safe.export(()) is SpanExportResult.FAILURE
    assert safe.force_flush() is False
    safe.shutdown()
