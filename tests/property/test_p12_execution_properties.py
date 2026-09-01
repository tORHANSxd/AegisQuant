"""Property checks for deterministic IDs, exact slicing, and idempotency."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from aegisquant.domain.values import Quantity
from aegisquant.execution.algorithms import build_twap_slices
from aegisquant.execution.rate_limit import (
    PriorityRateLimiter,
    RequestPriority,
    ScheduledRequest,
)
from tests.p12_helpers import BTC, NOW, command


@given(st.integers(min_value=1, max_value=20))
def test_twap_quantity_is_conserved(slice_count: int) -> None:
    slices = build_twap_slices(
        total_quantity=Quantity(amount=Decimal("1"), asset_id=BTC),
        slice_count=slice_count,
        start_at=NOW,
        interval_seconds=2,
        passive_seconds=1,
    )
    assert sum((item.quantity.amount for item in slices), start=Decimal("0")) == Decimal("1")


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20))
def test_rate_limit_semantic_id_is_idempotent(request_id: str) -> None:
    limiter = PriorityRateLimiter(capacity=1, refill_per_second=1, maximum_queue=2)
    item = ScheduledRequest(
        request_id=request_id,
        priority=RequestPriority.SUBMIT,
        weight=1,
        enqueued_at_ms=0,
    )
    assert limiter.enqueue(item) is True
    assert limiter.enqueue(item) is False


def test_client_order_identity_is_stable() -> None:
    assert command().identity == command().identity
