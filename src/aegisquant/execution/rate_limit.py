"""Priority-aware deterministic rate limiting and bounded backpressure."""

from __future__ import annotations

import hashlib
import heapq
from dataclasses import dataclass, field
from enum import IntEnum


class RequestPriority(IntEnum):
    RISK_OR_CANCEL = 0
    RECONCILIATION = 1
    SUBMIT = 2
    BACKGROUND = 3


@dataclass(frozen=True, slots=True)
class ScheduledRequest:
    request_id: str
    priority: RequestPriority
    weight: int
    enqueued_at_ms: int

    def __post_init__(self) -> None:
        if not self.request_id or self.weight < 1 or self.enqueued_at_ms < 0:
            raise ValueError("invalid scheduled request")


@dataclass(order=True, slots=True)
class _QueueItem:
    sort_key: tuple[int, int, str]
    request: ScheduledRequest = field(compare=False)


class PriorityRateLimiter:
    """Token bucket with strict safety priority and no unbounded queue."""

    def __init__(self, *, capacity: int, refill_per_second: int, maximum_queue: int) -> None:
        if capacity < 1 or refill_per_second < 1 or maximum_queue < 1:
            raise ValueError("rate limiter parameters must be positive")
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.maximum_queue = maximum_queue
        self._tokens = capacity
        self._last_refill_ms = 0
        self._queue: list[_QueueItem] = []
        self._known_ids: set[str] = set()

    def enqueue(self, request: ScheduledRequest) -> bool:
        if request.weight > self.capacity:
            raise ValueError("request weight exceeds bucket capacity")
        if request.request_id in self._known_ids:
            return False
        if len(self._queue) >= self.maximum_queue:
            if request.priority is RequestPriority.BACKGROUND:
                return False
            background = [
                item for item in self._queue if item.request.priority is RequestPriority.BACKGROUND
            ]
            if not background:
                raise BufferError("AQ-EXEC-RATE-LIMIT-SAFETY-QUEUE-FULL")
            victim = max(background, key=lambda item: item.sort_key)
            self._queue.remove(victim)
            heapq.heapify(self._queue)
            self._known_ids.remove(victim.request.request_id)
        heapq.heappush(
            self._queue,
            _QueueItem(
                sort_key=(int(request.priority), request.enqueued_at_ms, request.request_id),
                request=request,
            ),
        )
        self._known_ids.add(request.request_id)
        return True

    def next_ready(self, *, now_ms: int) -> ScheduledRequest | None:
        if now_ms < self._last_refill_ms:
            raise ValueError("rate limiter clock moved backwards")
        elapsed = now_ms - self._last_refill_ms
        added = elapsed * self.refill_per_second // 1000
        if added:
            self._tokens = min(self.capacity, self._tokens + added)
            self._last_refill_ms += added * 1000 // self.refill_per_second
        if not self._queue or self._queue[0].request.weight > self._tokens:
            return None
        item = heapq.heappop(self._queue)
        self._known_ids.remove(item.request.request_id)
        self._tokens -= item.request.weight
        return item.request

    @staticmethod
    def deterministic_jitter_ms(request_id: str, *, maximum_ms: int) -> int:
        if maximum_ms < 0:
            raise ValueError("maximum jitter cannot be negative")
        if maximum_ms == 0:
            return 0
        digest = hashlib.sha256(request_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % (maximum_ms + 1)

    @property
    def queued(self) -> int:
        return len(self._queue)
