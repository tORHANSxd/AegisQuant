"""Prometheus metrics with a deliberately small, validated label vocabulary."""

from __future__ import annotations

from typing import Final

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

ENVIRONMENTS: Final = frozenset({"research", "paper", "shadow", "testnet", "canary"})
SERVICES: Final = frozenset({"api", "runtime", "worker", "research", "web"})
EVENT_TYPES: Final = frozenset(
    {
        "market",
        "feature",
        "inference",
        "signal",
        "portfolio",
        "risk",
        "execution",
        "venue",
        "fill",
        "ledger",
        "read_model",
        "http_request",
        "alert",
        "backup",
        "restore",
        "deployment",
    }
)
STATUSES: Final = frozenset({"ok", "error", "timeout", "rejected", "unknown", "degraded"})
ROUTES: Final = frozenset(
    {
        "/api/v1/health",
        "/api/v1/summary",
        "/api/v1/records/{projection}",
        "/api/v1/records/{projection}/{entity_id}",
        "/api/v1/timeseries/{projection}/{entity_id}",
        "/api/v1/stream/snapshot",
        "/metrics",
        "other",
    }
)


def _one_of(value: str, allowed: frozenset[str], field: str) -> str:
    normalized = value.casefold()
    if normalized not in allowed:
        raise ValueError(f"unsupported low-cardinality {field}: {value}")
    return normalized


class AegisMetrics:
    """Application metric registry; identifiers and free text are never labels."""

    def __init__(
        self,
        *,
        service: str = "api",
        environment: str = "paper",
        registry: CollectorRegistry | None = None,
    ) -> None:
        self.service = _one_of(service, SERVICES, "service")
        self.environment = _one_of(environment, ENVIRONMENTS, "environment")
        self.registry = registry or CollectorRegistry(auto_describe=True)
        common = ["service", "environment"]
        self.events = Counter(
            "aegisquant_events_total",
            "Bounded operational events.",
            [*common, "event_type", "status"],
            registry=self.registry,
        )
        self.api_requests = Counter(
            "aegisquant_api_requests_total",
            "Read API requests.",
            [*common, "route", "method", "status_class"],
            registry=self.registry,
        )
        self.api_latency = Histogram(
            "aegisquant_api_request_duration_seconds",
            "Read API latency.",
            [*common, "route", "method"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
            registry=self.registry,
        )
        self.provider_lag = Gauge(
            "aegisquant_provider_lag_seconds",
            "Provider available-time lag.",
            [*common, "provider_tier"],
            registry=self.registry,
        )
        self.sequence_gaps = Counter(
            "aegisquant_sequence_gaps_total",
            "Observed sequence gaps.",
            [*common, "provider_tier"],
            registry=self.registry,
        )
        self.quarantine_rows = Gauge(
            "aegisquant_quarantine_rows",
            "Rows held outside Gold.",
            [*common, "data_domain"],
            registry=self.registry,
        )
        self.model_latency = Histogram(
            "aegisquant_model_inference_duration_seconds",
            "Inference latency by bounded model family.",
            [*common, "model_family", "status"],
            registry=self.registry,
        )
        self.orders = Counter(
            "aegisquant_orders_total",
            "Order lifecycle observations.",
            [*common, "stage", "venue_tier"],
            registry=self.registry,
        )
        self.reconciliation_mismatches = Gauge(
            "aegisquant_reconciliation_mismatches",
            "Unresolved reconciliation differences.",
            common,
            registry=self.registry,
        )
        self.ledger_lag = Gauge(
            "aegisquant_ledger_lag_seconds",
            "Lag from fill to authoritative ledger.",
            common,
            registry=self.registry,
        )
        self.risk_state = Gauge(
            "aegisquant_risk_state",
            "One-hot risk state.",
            [*common, "state"],
            registry=self.registry,
        )
        self.kill_switch = Gauge(
            "aegisquant_kill_switch_active",
            "One when the kill switch is active.",
            common,
            registry=self.registry,
        )
        self.resource_utilization = Gauge(
            "aegisquant_resource_utilization_ratio",
            "CPU, memory, disk, or file descriptor utilization.",
            [*common, "resource"],
            registry=self.registry,
        )
        self.clock_skew = Gauge(
            "aegisquant_clock_skew_seconds",
            "Absolute host clock skew.",
            common,
            registry=self.registry,
        )
        self.process_restarts = Counter(
            "aegisquant_process_restarts_total",
            "Process restart count by bounded component.",
            [*common, "component"],
            registry=self.registry,
        )

    @property
    def _common(self) -> tuple[str, str]:
        return self.service, self.environment

    def record_event(self, event_type: str, status: str = "ok") -> None:
        event = _one_of(event_type, EVENT_TYPES, "event_type")
        outcome = _one_of(status, STATUSES, "status")
        self.events.labels(*self._common, event, outcome).inc()

    def observe_api(self, *, route: str, method: str, status_code: int, seconds: float) -> None:
        safe_route = route if route in ROUTES else "other"
        safe_method = method.upper()
        if safe_method not in {"GET", "OPTIONS"}:
            safe_method = "OTHER"
        status_class = f"{status_code // 100}xx" if 100 <= status_code <= 599 else "other"
        self.api_requests.labels(*self._common, safe_route, safe_method, status_class).inc()
        self.api_latency.labels(*self._common, safe_route, safe_method).observe(max(seconds, 0.0))

    def render(self) -> bytes:
        return generate_latest(self.registry)
