"""Property tests for money, time, serialization, ledger, and idempotency invariants."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from aegisquant.domain.identifiers import AssetId, EventId, IdempotencyKey
from aegisquant.domain.serialization import deserialize_event, serialize_event
from aegisquant.domain.time import ensure_utc
from aegisquant.domain.values import Money

FINITE_DECIMALS = st.decimals(
    min_value=Decimal("-1000000000"),
    max_value=Decimal("1000000000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
).filter(lambda value: not (value.is_zero() and value.is_signed()))


@given(left=FINITE_DECIMALS, right=FINITE_DECIMALS)
def test_money_add_subtract_is_exact(left: Decimal, right: Decimal) -> None:
    asset = AssetId("USDT")
    first = Money(amount=left, asset_id=asset)
    second = Money(amount=right, asset_id=asset)
    assert (first + second).amount == left + right
    assert (first - second).amount == left - right


@given(value=st.floats(allow_nan=False, allow_infinity=False))
def test_money_never_implicitly_accepts_float(value: float) -> None:
    with pytest.raises(ValidationError):
        Money(amount=value, asset_id=AssetId("USDT"))  # type: ignore[arg-type]


@given(
    offset_minutes=st.integers(min_value=-1439, max_value=1439),
    seconds=st.integers(min_value=0, max_value=2_000_000_000),
)
def test_aware_time_normalizes_to_same_utc_instant(offset_minutes: int, seconds: int) -> None:
    instant = datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    zone = timezone(timedelta(minutes=offset_minutes))
    localized = instant.astimezone(zone)
    assert ensure_utc(localized) == instant


@given(amount=FINITE_DECIMALS, suffix=st.text(min_size=1, max_size=20))
def test_versioned_round_trip_preserves_decimal_and_version(amount: Decimal, suffix: str) -> None:
    money = Money(amount=amount, asset_id=AssetId("USDT"))
    event_id = EventId.from_content(suffix.encode(errors="surrogatepass"))
    now = datetime(2026, 8, 31, 8, tzinfo=UTC)
    raw = serialize_event(
        money,
        schema_name="aegisquant.money-test",
        schema_version="1.0.0",
        event_id=event_id,
        occurred_at=now,
        available_at=now,
    )
    restored = deserialize_event(
        raw,
        Money,
        expected_schema_name="aegisquant.money-test",
        current_version="1.0.0",
    )
    assert restored == money
    assert b'"schema_version":"1.0.0"' in raw


@given(content=st.binary(min_size=0, max_size=2048))
def test_idempotency_key_is_content_deterministic(content: bytes) -> None:
    first = IdempotencyKey.from_content(content)
    second = IdempotencyKey.from_content(content)
    assert first == second
    assert len(first.value) == 64
