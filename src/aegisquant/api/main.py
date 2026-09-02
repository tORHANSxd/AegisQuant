"""Strict production factory for the private Paper/Testnet read API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from aegisquant.api.app import create_app
from aegisquant.observability.logging import configure_json_logger
from aegisquant.observability.metrics import AegisMetrics
from aegisquant.observability.tracing import TracingRuntime

LOG_ROOT = Path("/var/log/aegisquant")


def _required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"required non-secret runtime setting is missing: {name}")
    return value.strip()


def create_production_app() -> FastAPI:
    """Build an authenticated app; absence of policy inputs fails startup."""
    environment = _required("AEGISQUANT_ENVIRONMENT").casefold()
    if environment not in {"paper", "testnet"}:
        raise RuntimeError("production read API supports only Paper or Testnet")
    if _required("AEGISQUANT_AUTH_MODE") != "mtls_proxy":
        raise RuntimeError("production read API requires the mTLS reverse-proxy boundary")
    log_path = Path(os.environ.get("AEGISQUANT_LOG_PATH", str(LOG_ROOT / "api.jsonl"))).resolve()
    allowed_log_root = LOG_ROOT.resolve()
    if log_path.parent != allowed_log_root or log_path.suffix != ".jsonl":
        raise RuntimeError("AEGISQUANT_LOG_PATH must be one JSONL file in /var/log/aegisquant")
    configure_json_logger(
        "aegisquant.api",
        service="api",
        version="3.1.0.dev0",
        destination=log_path,
    )
    tracing = TracingRuntime(
        service="api",
        environment=environment,
        endpoint=os.environ.get("AEGISQUANT_OTLP_TRACES_ENDPOINT", "http://alloy:4318/v1/traces"),
    )
    return create_app(
        metrics=AegisMetrics(service="api", environment=environment),
        tracing=tracing,
    )
