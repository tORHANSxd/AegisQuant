"""Unsigned REST transport, rate-limit, retry, and redirect contracts."""

from datetime import UTC, datetime

import httpx
import pytest

from aegisquant.data.providers.binance.contracts import RestEndpoint
from aegisquant.data.providers.binance.rest import BinancePublicRestClient, decode_json
from aegisquant.domain.errors import DomainError, ErrorDisposition


def test_public_rest_sends_no_credentials_and_captures_rate_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        folded = {key.casefold() for key in request.headers}
        assert "authorization" not in folded
        assert "cookie" not in folded
        assert "x-mbx-apikey" not in folded
        return httpx.Response(
            200,
            json={"serverTime": 1788184800000},
            headers={"X-MBX-USED-WEIGHT-1M": "7"},
            request=request,
        )

    with BinancePublicRestClient(
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime(2026, 8, 31, 14, tzinfo=UTC),
    ) as client:
        response = client.get(RestEndpoint.SPOT_TIME)
    assert decode_json(response) == {"serverTime": 1788184800000}
    assert response.rate_limit_headers == {"x-mbx-used-weight-1m": "7"}
    assert response.request_url == "https://data-api.binance.vision/api/v3/time"


def test_429_obeys_retry_after_then_succeeds() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json={"serverTime": 1}, request=request)

    with BinancePublicRestClient(
        transport=httpx.MockTransport(handler), sleep=sleeps.append
    ) as client:
        client.get(RestEndpoint.USDM_TIME)
    assert calls == 2
    assert sleeps == [0.0]


@pytest.mark.parametrize(
    ("status", "code", "disposition"),
    [
        (418, "IP-BANNED", ErrorDisposition.HALT),
        (429, "RATE-LIMITED", ErrorDisposition.RETRY),
    ],
)
def test_terminal_rate_errors_are_classified(
    status: int, code: str, disposition: ErrorDisposition
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, request=request))
    with (
        BinancePublicRestClient(transport=transport, maximum_attempts=1) as client,
        pytest.raises(DomainError, match=code) as captured,
    ):
        client.get(RestEndpoint.SPOT_TIME)
    assert captured.value.disposition is disposition


def test_redirect_is_not_followed() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302, headers={"Location": "https://example.invalid/private"}, request=request
        )
    )
    with (
        BinancePublicRestClient(transport=transport) as client,
        pytest.raises(DomainError, match="REDIRECT-DENIED"),
    ):
        client.get(RestEndpoint.SPOT_TIME)
