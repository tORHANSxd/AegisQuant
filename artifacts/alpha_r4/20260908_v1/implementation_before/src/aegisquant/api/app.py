"""FastAPI application factory for the loopback-only operational read service."""
# pyright: reportUnusedFunction=false

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from aegisquant.api.models import ErrorBody, ErrorResponse
from aegisquant.api.routes import APIContractError, create_router, create_websocket_router
from aegisquant.api.stream import SequencedStream
from aegisquant.data.hashing import canonical_sha256
from aegisquant.observability.context import TelemetryContext, correlation_scope
from aegisquant.observability.metrics import AegisMetrics
from aegisquant.observability.tracing import TracingRuntime
from aegisquant.readmodels.engine import ReadModelQuery
from aegisquant.readmodels.models import ProjectionSnapshot
from aegisquant.readmodels.p15_bootstrap import build_p15_snapshot
from aegisquant.security.auth import AuthenticationError, OIDCBearerVerifier

PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH: Final = PROJECT_ROOT / "reports/read_models/P15_SNAPSHOT.json"
CORRELATION_PATTERN: Final = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
LOOPBACK_ORIGINS: Final = ("http://127.0.0.1:3000", "http://localhost:3000")
LOGGER: Final = logging.getLogger("aegisquant.api")


def load_snapshot(path: Path = SNAPSHOT_PATH) -> ProjectionSnapshot:
    """Load the immutable artifact, or deterministically rebuild it from audited inputs."""
    if path.is_file():
        return ProjectionSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    return build_p15_snapshot(PROJECT_ROOT)


def _correlation_id(request: Request) -> str:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, str) else uuid4().hex


def _error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    response = ErrorResponse(
        error=ErrorBody(code=code, message=message, correlation_id=_correlation_id(request))
    )
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def create_app(
    snapshot: ProjectionSnapshot | None = None,
    *,
    metrics: AegisMetrics | None = None,
    tracing: TracingRuntime | None = None,
    token_verifier: OIDCBearerVerifier | None = None,
) -> FastAPI:
    """Create a read-only API bound to one validated snapshot."""
    selected = snapshot if snapshot is not None else load_snapshot()
    query = ReadModelQuery(selected)
    stream = SequencedStream(query)
    selected_metrics = metrics or AegisMetrics(service="api", environment="paper")
    selected_tracing = tracing or TracingRuntime(service="api", environment="paper")
    app = FastAPI(
        title="AegisQuant Read API",
        summary="Loopback-only, read-only operational workbench API",
        description=(
            "Versioned Read Model API. It exposes no trading writes, no credential input, "
            "and no LIVE_TRADING unlock capability."
        ),
        version="3.1.0.dev0",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        contact={"name": "Local operator"},
        license_info={"name": "Private local project"},
    )
    app.state.read_model_query = query
    app.state.sequenced_stream = stream
    app.state.metrics = selected_metrics
    app.state.tracing = selected_tracing
    app.state.authentication_required = token_verifier is not None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOOPBACK_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID", "X-Trace-ID"],
        max_age=600,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        supplied = request.headers.get("x-correlation-id", "")
        request.state.correlation_id = (
            supplied if CORRELATION_PATTERN.fullmatch(supplied) else uuid4().hex
        )
        telemetry_context = TelemetryContext(
            correlation_id=request.state.correlation_id,
            event_type="http_request",
        )
        cacheable = (
            request.method == "GET"
            and request.url.path
            not in {"/api/v1/health", "/api/v1/stream/snapshot", "/api/v1/openapi.json"}
            and not request.url.path.startswith("/api/v1/docs")
        )
        etag = (
            '"'
            + canonical_sha256(
                {
                    "snapshot": selected.content_sha256,
                    "path": request.url.path,
                    "query": request.url.query,
                }
            )
            + '"'
        )
        with (
            correlation_scope(telemetry_context),
            selected_tracing.span(
                "http.request",
                telemetry_context,
                attributes={
                    "http.request.method": request.method,
                    "url.path": request.url.path,
                },
            ) as span,
        ):
            response: Response | None = None
            if token_verifier is not None and request.url.path not in {
                "/api/v1/health",
                "/metrics",
            }:
                try:
                    principal = token_verifier.authenticate(request.headers.get("authorization"))
                    request.state.principal = principal
                except AuthenticationError:
                    response = _error(
                        request,
                        401,
                        "AQ-API-AUTHENTICATION",
                        "Authentication is required.",
                    )
                    response.headers["WWW-Authenticate"] = "Bearer"
            if response is None:
                if cacheable and request.headers.get("if-none-match") == etag:
                    response = Response(status_code=304)
                else:
                    response = await call_next(request)
            span.set_attribute("http.response.status_code", response.status_code)
            span_context = span.get_span_context()
            trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else ""
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        if trace_id:
            response.headers["X-Trace-ID"] = trace_id
        if cacheable and response.status_code < 400:
            response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
            response.headers["ETag"] = etag
            response.headers["Vary"] = "If-None-Match"
        else:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        route = request.scope.get("route")
        candidate_route = getattr(route, "path", request.url.path)
        route_path = candidate_route if isinstance(candidate_route, str) else "other"
        selected_metrics.observe_api(
            route=route_path,
            method=request.method,
            status_code=response.status_code,
            seconds=time.perf_counter() - started,
        )
        selected_metrics.record_event(
            "http_request", "ok" if response.status_code < 400 else "error"
        )
        LOGGER.info(
            "read API request completed",
            extra={
                "event_type": "http_request",
                "details": {
                    "route": route_path,
                    "method": request.method,
                    "status_code": response.status_code,
                },
            },
        )
        return response

    @app.exception_handler(APIContractError)
    async def contract_error(request: Request, error: APIContractError) -> JSONResponse:
        return _error(request, error.status_code, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, _error_value: RequestValidationError
    ) -> JSONResponse:
        return _error(
            request, 422, "AQ-API-VALIDATION", "The request did not match the API contract."
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = "AQ-API-NOT-FOUND" if error.status_code == 404 else "AQ-API-HTTP-ERROR"
        message = (
            "The requested resource was not found."
            if error.status_code == 404
            else "HTTP request failed."
        )
        return _error(request, error.status_code, code, message)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, _error_value: Exception) -> JSONResponse:
        return _error(request, 500, "AQ-API-INTERNAL", "The read service failed safely.")

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(
            content=selected_metrics.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    app.include_router(create_router(query, stream))
    app.include_router(create_websocket_router(stream))
    return app
