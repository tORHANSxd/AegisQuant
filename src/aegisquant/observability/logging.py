"""Structured JSON logs with mandatory fields and defensive redaction."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from opentelemetry import trace

from aegisquant.observability.context import current_context

SENSITIVE_KEY: Final = re.compile(
    r"(?i)(authorization|api[_-]?key|secret|cookie|session|password|passcode|token|otp)"
)
INLINE_SECRET: Final = re.compile(
    r"(?i)\b(authorization|api[_-]?key|secret|cookie|session|password|token)"
    r"\s*[:=]\s*([^\s,;]+)"
)
BEARER: Final = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")
REDACTED: Final = "[REDACTED]"


def redact(value: object) -> object:
    """Recursively remove values under credential-shaped keys."""
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        return {
            str(key): REDACTED if SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in mapping.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in cast("Sequence[object]", value)]
    if isinstance(value, str):
        without_bearer = BEARER.sub(f"Bearer {REDACTED}", value)
        return INLINE_SECRET.sub(lambda match: f"{match.group(1)}={REDACTED}", without_bearer)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


class StructuredJsonFormatter(logging.Formatter):
    """Emit one stable JSON object per log record."""

    def __init__(self, *, service: str, version: str) -> None:
        super().__init__()
        self._service = service
        self._version = version
        self._host = socket.gethostname()

    def format(self, record: logging.LogRecord) -> str:
        context = current_context()
        span_context = trace.get_current_span().get_span_context()
        trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else None
        span_id = f"{span_context.span_id:016x}" if span_context.is_valid else None
        details = redact(getattr(record, "details", {}))
        payload: dict[str, object] = {
            "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self._service,
            "version": self._version,
            "host": self._host,
            "process_id": os.getpid(),
            "trace_id": trace_id,
            "span_id": span_id,
            "correlation_id": None if context is None else context.correlation_id,
            "event_type": getattr(record, "event_type", None)
            or (None if context is None else context.event_type),
            "account_scope": None if context is None else context.account_scope,
            "strategy_id": None if context is None else context.strategy_id,
            "model_version_id": None if context is None else context.model_version_id,
            "order_intent_id": None if context is None else context.order_intent_id,
            "error_code": getattr(record, "error_code", None),
            "message": redact(record.getMessage()),
        }
        if isinstance(details, dict) and details:
            payload["details"] = details
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def configure_json_logger(
    name: str,
    *,
    service: str,
    version: str,
    destination: Path | None = None,
) -> logging.Logger:
    """Configure one named logger without changing the process root logger."""
    logger = logging.getLogger(name)
    logger.handlers.clear()
    handler: logging.Handler
    if destination is None:
        handler = logging.StreamHandler()
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(destination, encoding="utf-8")
    handler.setFormatter(StructuredJsonFormatter(service=service, version=version))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
