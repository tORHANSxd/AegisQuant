"""Safety-priority rate limit and bounded backpressure."""

from __future__ import annotations

from aegisquant.execution.rate_limit import (
    PriorityRateLimiter,
    RequestPriority,
    ScheduledRequest,
)


def request(name: str, priority: RequestPriority, *, weight: int = 1) -> ScheduledRequest:
    return ScheduledRequest(request_id=name, priority=priority, weight=weight, enqueued_at_ms=0)


def test_cancel_and_reconciliation_preempt_new_orders() -> None:
    limiter = PriorityRateLimiter(capacity=3, refill_per_second=1, maximum_queue=5)
    limiter.enqueue(request("submit", RequestPriority.SUBMIT))
    limiter.enqueue(request("reconcile", RequestPriority.RECONCILIATION))
    limiter.enqueue(request("cancel", RequestPriority.RISK_OR_CANCEL))
    assert limiter.next_ready(now_ms=0).request_id == "cancel"  # type: ignore[union-attr]
    assert limiter.next_ready(now_ms=0).request_id == "reconcile"  # type: ignore[union-attr]
    assert limiter.next_ready(now_ms=0).request_id == "submit"  # type: ignore[union-attr]


def test_safety_request_evicts_background_under_backpressure() -> None:
    limiter = PriorityRateLimiter(capacity=1, refill_per_second=1, maximum_queue=2)
    assert limiter.enqueue(request("background-1", RequestPriority.BACKGROUND)) is True
    assert limiter.enqueue(request("background-2", RequestPriority.BACKGROUND)) is True
    assert limiter.enqueue(request("cancel", RequestPriority.RISK_OR_CANCEL)) is True
    assert limiter.queued == 2
    assert limiter.next_ready(now_ms=0).request_id == "cancel"  # type: ignore[union-attr]


def test_idempotency_and_jitter_are_deterministic() -> None:
    limiter = PriorityRateLimiter(capacity=1, refill_per_second=1, maximum_queue=2)
    item = request("same", RequestPriority.SUBMIT)
    assert limiter.enqueue(item) is True
    assert limiter.enqueue(item) is False
    assert limiter.deterministic_jitter_ms(
        "same", maximum_ms=100
    ) == limiter.deterministic_jitter_ms("same", maximum_ms=100)
