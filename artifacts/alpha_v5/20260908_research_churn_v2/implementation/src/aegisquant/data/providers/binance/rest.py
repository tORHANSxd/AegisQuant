"""Unsigned Binance public REST client with bounded retries and no ambient credentials."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from aegisquant.data.providers.binance.contracts import RestEndpoint, build_rest_request
from aegisquant.data.providers.binance.models import RawResponseEnvelope
from aegisquant.domain.errors import DomainError, ErrorDisposition


def _utc_now() -> datetime:
    return datetime.now(UTC)


def decode_json(response: RawResponseEnvelope) -> object:
    """Decode one archived response without accepting non-standard JSON constants."""

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-standard JSON constant is forbidden: {value}")

    return json.loads(response.content.decode("utf-8"), parse_constant=reject_constant)


class BinancePublicRestClient:
    """Strict synchronous client for allow-listed market-data GET requests only."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
        maximum_attempts: int = 4,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if maximum_attempts < 1 or maximum_attempts > 8:
            raise ValueError("maximum_attempts must be between 1 and 8")
        self._maximum_attempts = maximum_attempts
        self._clock = clock
        self._sleep = sleep
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "User-Agent": "AegisQuant/3.1 public-market-data",
            },
        )

    def __enter__(self) -> BinancePublicRestClient:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(
        self, endpoint: RestEndpoint, parameters: dict[str, str | int] | None = None
    ) -> RawResponseEnvelope:
        url, safe_parameters, request_hash = build_rest_request(endpoint, parameters)
        last_error: Exception | None = None
        for attempt in range(1, self._maximum_attempts + 1):
            started_ns = time.perf_counter_ns()
            try:
                response = self._client.get(url, params=safe_parameters)
            except httpx.TransportError as error:
                last_error = error
                if attempt == self._maximum_attempts:
                    break
                self._sleep(min(0.5 * 2 ** (attempt - 1), 8.0))
                continue
            elapsed_ms = max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)
            if 300 <= response.status_code < 400:
                raise DomainError(
                    "AQ-PROVIDER-BINANCE-REDIRECT-DENIED",
                    ErrorDisposition.NO_RETRY,
                    response.headers.get("location", "missing-location"),
                )
            if response.status_code == 418:
                raise DomainError(
                    "AQ-PROVIDER-BINANCE-IP-BANNED",
                    ErrorDisposition.HALT,
                    response.headers.get("retry-after", "unspecified"),
                )
            if response.status_code == 429:
                retry_after = self._retry_after(response)
                if attempt == self._maximum_attempts:
                    raise DomainError(
                        "AQ-PROVIDER-BINANCE-RATE-LIMITED",
                        ErrorDisposition.RETRY,
                        str(retry_after),
                    )
                self._sleep(retry_after)
                continue
            if response.status_code in {500, 502, 503, 504}:
                if attempt == self._maximum_attempts:
                    response.raise_for_status()
                self._sleep(min(0.5 * 2 ** (attempt - 1), 8.0))
                continue
            response.raise_for_status()
            content = bytes(response.content)
            rate_headers = {
                key.casefold(): value
                for key, value in response.headers.items()
                if key.casefold().startswith("x-mbx-used-weight") or key.casefold() == "retry-after"
            }
            return RawResponseEnvelope(
                endpoint=endpoint.value,
                request_url=str(response.request.url),
                request_hash=request_hash,
                status_code=response.status_code,
                received_at=self._clock(),
                elapsed_ms=elapsed_ms,
                rate_limit_headers=rate_headers,
                content_sha256=hashlib.sha256(content).hexdigest(),
                content=content,
            )
        if last_error is None:
            raise RuntimeError("REST retry loop ended without a response or transport error")
        raise DomainError(
            "AQ-PROVIDER-BINANCE-TRANSPORT-FAILED",
            ErrorDisposition.RETRY,
            type(last_error).__name__,
        ) from last_error

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        raw = response.headers.get("retry-after")
        if raw is None:
            return 1.0
        try:
            value = float(raw)
        except ValueError:
            return 1.0
        if value < 0 or value > 86_400:
            return 1.0
        return value

    def get_json(
        self, endpoint: RestEndpoint, parameters: dict[str, str | int] | None = None
    ) -> tuple[RawResponseEnvelope, object]:
        response = self.get(endpoint, parameters)
        return response, decode_json(response)
