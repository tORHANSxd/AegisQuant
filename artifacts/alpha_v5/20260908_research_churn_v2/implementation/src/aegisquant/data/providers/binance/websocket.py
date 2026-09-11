"""Public Binance WebSocket lifecycle with bounded reconnect and proactive rollover."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Protocol, cast

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from aegisquant.data.providers.binance.contracts import assert_public_url
from aegisquant.data.providers.binance.models import ConnectionHealth


class PublicWebSocket(Protocol):
    async def recv(self, decode: bool | None = None) -> str | bytes: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


Connector = Callable[[str], AbstractAsyncContextManager[PublicWebSocket]]
MessageHandler = Callable[[bytes, datetime], Awaitable[None]]
ConnectionHandler = Callable[[datetime], Awaitable[None]]


@asynccontextmanager
async def _default_connector(url: str) -> AsyncGenerator[PublicWebSocket]:
    async with connect(
        url,
        ping_interval=None,
        ping_timeout=None,
        close_timeout=5,
        open_timeout=10,
        max_queue=1024,
        max_size=2 * 1024 * 1024,
        compression=None,
        additional_headers={"User-Agent": "AegisQuant/3.1 public-market-data"},
        proxy=None,
    ) as websocket:
        yield cast(PublicWebSocket, websocket)


class ConnectionAttemptLimiter:
    """Local conservative enforcement of Binance's per-IP connection-attempt window."""

    def __init__(self, *, maximum_attempts: int = 300, window_seconds: float = 300.0) -> None:
        if maximum_attempts < 1 or window_seconds <= 0:
            raise ValueError("connection limiter bounds must be positive")
        self.maximum_attempts = maximum_attempts
        self.window_seconds = window_seconds
        self._attempts: deque[float] = deque()

    def require(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._attempts and self._attempts[0] <= cutoff:
            self._attempts.popleft()
        if len(self._attempts) >= self.maximum_attempts:
            raise RuntimeError("AQ-PROVIDER-BINANCE-WS-CONNECTION-LIMIT")
        self._attempts.append(now)


class PublicStreamRunner:
    """Run one direct public stream; direct URLs avoid subscription control-message load."""

    def __init__(
        self,
        *,
        url: str,
        connector: Connector = _default_connector,
        maximum_connection_age_seconds: float = 85_800.0,
        message_timeout_seconds: float = 120.0,
        maximum_backoff_seconds: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        attempt_limiter: ConnectionAttemptLimiter | None = None,
    ) -> None:
        assert_public_url(url, websocket=True)
        if not 1 <= maximum_connection_age_seconds <= 86_400:
            raise ValueError("connection age must be within the official 24-hour lifetime")
        if message_timeout_seconds <= 0 or maximum_backoff_seconds <= 0:
            raise ValueError("WebSocket timeout and backoff must be positive")
        self.url = url
        self._connector = connector
        self._maximum_age = maximum_connection_age_seconds
        self._message_timeout = message_timeout_seconds
        self._maximum_backoff = maximum_backoff_seconds
        self._monotonic = monotonic
        self._clock = clock
        self._limiter = attempt_limiter or ConnectionAttemptLimiter()
        self._force_reconnect = asyncio.Event()
        self._connected_at: datetime | None = None
        self._last_message_at: datetime | None = None
        self._reconnect_count = 0
        self._message_count = 0
        self._forced_rollover_count = 0
        self._status = "IDLE"

    def request_reconnect(self) -> None:
        """Request an adapter-level outage/reconnect without touching the host network stack."""
        self._force_reconnect.set()

    def health(
        self, *, duplicate_count: int = 0, late_count: int = 0, gap_count: int = 0
    ) -> ConnectionHealth:
        return ConnectionHealth(
            stream_url=self.url,
            connected_at=self._connected_at,
            last_message_at=self._last_message_at,
            reconnect_count=self._reconnect_count,
            message_count=self._message_count,
            duplicate_count=duplicate_count,
            late_count=late_count,
            gap_count=gap_count,
            forced_rollover_count=self._forced_rollover_count,
            status=self._status,
        )

    async def run(
        self,
        *,
        stop: asyncio.Event,
        on_message: MessageHandler,
        on_connect: ConnectionHandler | None = None,
    ) -> None:
        consecutive_failures = 0
        while not stop.is_set():
            self._limiter.require(self._monotonic())
            connection_started = self._monotonic()
            self._status = "CONNECTING"
            try:
                async with self._connector(self.url) as socket:
                    self._connected_at = self._clock()
                    self._status = "CONNECTED"
                    consecutive_failures = 0
                    if on_connect is not None:
                        await on_connect(self._connected_at)
                    reconnect_reason = await self._consume_connection(
                        socket=socket,
                        stop=stop,
                        on_message=on_message,
                        connection_started=connection_started,
                    )
                    if reconnect_reason == "STOP":
                        self._status = "STOPPED"
                        return
                    await socket.close(code=1000, reason=reconnect_reason)
                    self._reconnect_count += 1
            except (ConnectionClosed, OSError, TimeoutError):
                self._reconnect_count += 1
                consecutive_failures += 1
                self._status = "RECONNECTING"
            if stop.is_set():
                break
            delay = self._backoff_delay(max(1, consecutive_failures or self._reconnect_count))
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
        self._status = "STOPPED"

    async def _consume_connection(
        self,
        *,
        socket: PublicWebSocket,
        stop: asyncio.Event,
        on_message: MessageHandler,
        connection_started: float,
    ) -> str:
        while True:
            remaining_age = self._maximum_age - (self._monotonic() - connection_started)
            if remaining_age <= 0:
                self._forced_rollover_count += 1
                return "PROACTIVE_24H_ROLLOVER"
            receive_task = asyncio.create_task(socket.recv(decode=False))
            stop_task = asyncio.create_task(stop.wait())
            reconnect_task = asyncio.create_task(self._force_reconnect.wait())
            done, pending = await asyncio.wait(
                {receive_task, stop_task, reconnect_task},
                timeout=min(remaining_age, self._message_timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if stop_task in done and stop_task.result():
                receive_task.cancel()
                reconnect_task.cancel()
                return "STOP"
            if reconnect_task in done and reconnect_task.result():
                self._force_reconnect.clear()
                receive_task.cancel()
                stop_task.cancel()
                return "FORCED_TEST_RECONNECT"
            if receive_task not in done:
                receive_task.cancel()
                stop_task.cancel()
                reconnect_task.cancel()
                if remaining_age <= self._message_timeout:
                    self._forced_rollover_count += 1
                    return "PROACTIVE_24H_ROLLOVER"
                raise TimeoutError("public stream message timeout")
            raw = receive_task.result()
            payload = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            if len(payload) > 2 * 1024 * 1024:
                raise ValueError("AQ-DATA-BINANCE-WS-FRAME-TOO-LARGE")
            observed = self._clock()
            self._last_message_at = observed
            self._message_count += 1
            decoded: object = json.loads(payload)
            if isinstance(decoded, dict):
                decoded_mapping = cast(dict[object, object], decoded)
                if decoded_mapping.get("e") == "serverShutdown":
                    return "SERVER_SHUTDOWN"
            await on_message(payload, observed)

    def _backoff_delay(self, attempt: int) -> float:
        base = min(0.5 * 2 ** min(attempt - 1, 8), self._maximum_backoff)
        deterministic_jitter = 0.8 + ((attempt * 1_103_515_245) % 401) / 1000
        return min(base * deterministic_jitter, self._maximum_backoff)
