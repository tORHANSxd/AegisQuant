"""OpenTelemetry traces whose exporter can never block a risk decision."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Final
from urllib.parse import urlparse

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span, Tracer

from aegisquant.observability.context import TelemetryContext

INTERNAL_COLLECTORS: Final = frozenset({"127.0.0.1", "localhost", "alloy"})


class SafeSpanExporter(SpanExporter):
    """Convert exporter failures to a telemetry failure result, never an exception."""

    def __init__(self, wrapped: SpanExporter) -> None:
        self._wrapped = wrapped

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            return self._wrapped.export(spans)
        except Exception:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        try:
            self._wrapped.shutdown()
        except Exception:
            return

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            return bool(self._wrapped.force_flush(timeout_millis))
        except Exception:
            return False


def validate_otlp_endpoint(endpoint: str) -> str:
    """Allow only an internal HTTP collector or a TLS endpoint without credentials."""
    parsed = urlparse(endpoint)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("OTLP endpoint cannot contain credentials, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname not in INTERNAL_COLLECTORS:
        raise ValueError("plain HTTP OTLP is restricted to loopback or the internal Alloy service")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("OTLP endpoint must be an absolute HTTP(S) URL")
    if not parsed.path.endswith("/v1/traces"):
        raise ValueError("OTLP/HTTP trace endpoint must end with /v1/traces")
    return endpoint


class TracingRuntime:
    """Owned tracer provider with explicit lifecycle and no global mutation."""

    def __init__(
        self,
        *,
        service: str = "api",
        version: str = "3.1.0.dev0",
        environment: str = "paper",
        exporter: SpanExporter | None = None,
        endpoint: str | None = None,
        synchronous: bool = False,
    ) -> None:
        if exporter is not None and endpoint is not None:
            raise ValueError("provide exporter or endpoint, not both")
        resource = Resource.create(
            {
                "service.name": f"aegisquant-{service}",
                "service.version": version,
                "deployment.environment.name": environment,
            }
        )
        self.provider = TracerProvider(resource=resource)
        selected = exporter
        if endpoint is not None:
            selected = OTLPSpanExporter(endpoint=validate_otlp_endpoint(endpoint), timeout=2.0)
        if selected is not None:
            safe = SafeSpanExporter(selected)
            processor = SimpleSpanProcessor(safe) if synchronous else BatchSpanProcessor(safe)
            self.provider.add_span_processor(processor)
        self.tracer: Tracer = self.provider.get_tracer(
            "aegisquant.observability", instrumenting_library_version=version
        )

    @contextmanager
    def span(
        self,
        name: str,
        context: TelemetryContext,
        *,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> Generator[Span]:
        with self.tracer.start_as_current_span(name) as span:
            span.set_attribute("aegisquant.correlation_id", context.correlation_id)
            span.set_attribute("aegisquant.event_type", context.event_type)
            for key, value in (attributes or {}).items():
                span.set_attribute(key, value)
            yield span

    def shutdown(self) -> None:
        self.provider.shutdown()
