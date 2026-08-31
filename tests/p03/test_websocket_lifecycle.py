"""Offline WebSocket reconnect, shutdown, attempt-limit, and forced-outage contracts."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from aegisquant.data.providers.binance.contracts import (
    Product,
    StreamKind,
    build_ws_url,
)
from aegisquant.data.providers.binance.websocket import (
    ConnectionAttemptLimiter,
    PublicStreamRunner,
)


class FakeSocket:
    def __init__(self, messages: list[bytes]) -> None:
        self._messages = messages
        self.closed_reasons: list[str] = []

    async def recv(self, decode: bool | None = None) -> str | bytes:
        del decode
        if self._messages:
            return self._messages.pop(0)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def close(self, code: int = 1000, reason: str = "") -> None:
        assert code == 1000
        self.closed_reasons.append(reason)


@pytest.mark.asyncio
async def test_direct_public_stream_stops_cleanly_without_subscription_messages() -> None:
    socket = FakeSocket([b'{"e":"bookTicker","u":1}', b'{"e":"bookTicker","u":2}'])

    @asynccontextmanager
    async def connector(_url: str) -> AsyncGenerator[FakeSocket]:
        yield socket

    current = datetime(2026, 8, 31, 14, tzinfo=UTC)
    runner = PublicStreamRunner(
        url=build_ws_url(product=Product.SPOT, kind=StreamKind.BOOK_TICKER, symbol="BTCUSDT"),
        connector=connector,
        clock=lambda: current,
        maximum_backoff_seconds=0.001,
    )
    stop = asyncio.Event()
    received: list[bytes] = []

    async def handler(payload: bytes, _observed_at: datetime) -> None:
        received.append(payload)
        if len(received) == 2:
            stop.set()

    await runner.run(stop=stop, on_message=handler)
    health = runner.health()
    assert len(received) == 2
    assert health.message_count == 2
    assert health.reconnect_count == 0
    assert health.status == "STOPPED"


@pytest.mark.asyncio
async def test_forced_adapter_outage_reconnects_without_touching_host_network() -> None:
    sockets = [
        FakeSocket([b'{"e":"depthUpdate","U":1,"u":1}']),
        FakeSocket([b'{"e":"depthUpdate","U":2,"u":2}']),
    ]
    connection_count = 0

    @asynccontextmanager
    async def connector(_url: str) -> AsyncGenerator[FakeSocket]:
        nonlocal connection_count
        socket = sockets[connection_count]
        connection_count += 1
        yield socket

    current = datetime(2026, 8, 31, 14, tzinfo=UTC)
    runner = PublicStreamRunner(
        url=build_ws_url(product=Product.SPOT, kind=StreamKind.DEPTH, symbol="BTCUSDT"),
        connector=connector,
        clock=lambda: current,
        maximum_backoff_seconds=0.001,
    )
    stop = asyncio.Event()
    received = 0

    async def handler(_payload: bytes, _observed_at: datetime) -> None:
        nonlocal received
        received += 1
        if received == 1:
            runner.request_reconnect()
        else:
            stop.set()

    await runner.run(stop=stop, on_message=handler)
    assert received == 2
    assert connection_count == 2
    assert runner.health().reconnect_count == 1
    assert sockets[0].closed_reasons == ["FORCED_TEST_RECONNECT"]


@pytest.mark.asyncio
async def test_server_shutdown_event_reconnects_before_delivering_payload() -> None:
    sockets = [
        FakeSocket([b'{"e":"serverShutdown","E":1788184800000}']),
        FakeSocket([b'{"e":"aggTrade","a":1}']),
    ]
    connection_count = 0

    @asynccontextmanager
    async def connector(_url: str) -> AsyncGenerator[FakeSocket]:
        nonlocal connection_count
        socket = sockets[connection_count]
        connection_count += 1
        yield socket

    runner = PublicStreamRunner(
        url=build_ws_url(product=Product.USD_M, kind=StreamKind.AGG_TRADE, symbol="BTCUSDT"),
        connector=connector,
        maximum_backoff_seconds=0.001,
    )
    stop = asyncio.Event()
    delivered: list[bytes] = []

    async def handler(payload: bytes, _observed_at: datetime) -> None:
        delivered.append(payload)
        stop.set()

    await runner.run(stop=stop, on_message=handler)
    assert delivered == [b'{"e":"aggTrade","a":1}']
    assert connection_count == 2
    assert sockets[0].closed_reasons == ["SERVER_SHUTDOWN"]


def test_connection_attempt_limiter_uses_rolling_window() -> None:
    limiter = ConnectionAttemptLimiter(maximum_attempts=2, window_seconds=300)
    limiter.require(0.0)
    limiter.require(1.0)
    with pytest.raises(RuntimeError, match="CONNECTION-LIMIT"):
        limiter.require(2.0)
    limiter.require(301.0)
