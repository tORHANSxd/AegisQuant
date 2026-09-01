"""FastAPI application factory for the loopback-only P14 read service."""
# pyright: reportUnusedFunction=false

from __future__ import annotations

import re
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
from aegisquant.readmodels.bootstrap import build_snapshot
from aegisquant.readmodels.engine import ReadModelQuery
from aegisquant.readmodels.models import ProjectionSnapshot

PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH: Final = PROJECT_ROOT / "reports/read_models/P14_SNAPSHOT.json"
CORRELATION_PATTERN: Final = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
LOOPBACK_ORIGINS: Final = ("http://127.0.0.1:3000", "http://localhost:3000")


def load_snapshot(path: Path = SNAPSHOT_PATH) -> ProjectionSnapshot:
    """Load the immutable artifact, or deterministically rebuild it from audited inputs."""
    if path.is_file():
        return ProjectionSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    return build_snapshot(PROJECT_ROOT)


def _correlation_id(request: Request) -> str:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, str) else uuid4().hex


def _error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    response = ErrorResponse(
        error=ErrorBody(code=code, message=message, correlation_id=_correlation_id(request))
    )
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def create_app(snapshot: ProjectionSnapshot | None = None) -> FastAPI:
    """Create a read-only API bound to one validated snapshot."""
    selected = snapshot if snapshot is not None else load_snapshot()
    query = ReadModelQuery(selected)
    stream = SequencedStream(query)
    app = FastAPI(
        title="AegisQuant Read API",
        summary="Loopback-only, read-only P14 dashboard API",
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOOPBACK_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
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
        supplied = request.headers.get("x-correlation-id", "")
        request.state.correlation_id = (
            supplied if CORRELATION_PATTERN.fullmatch(supplied) else uuid4().hex
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
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

    app.include_router(create_router(query, stream))
    app.include_router(create_websocket_router(stream))
    return app
