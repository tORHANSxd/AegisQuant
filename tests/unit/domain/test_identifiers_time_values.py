"""Strong identifier, UTC clock, and Decimal value tests."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import AssetId, EventId, RunId
from aegisquant.domain.time import FixedClock, assert_point_in_time, ensure_utc
from aegisquant.domain.values import Money, Price, RoundingMode


class EventHolder(DomainModel):
    event_id: EventId


def test_identifier_generation_is_deterministic_and_types_do_not_mix() -> None:
    namespace = UUID("12345678-1234-5678-1234-567812345678")
    assert EventId.from_name(namespace, "same") == EventId.from_name(namespace, "same")
    assert EventId.from_content(b"fact") == EventId.from_content(b"fact")
    with pytest.raises(ValidationError):
        EventHolder(event_id=RunId("run-1"))  # type: ignore[arg-type]


def test_utc_time_rejects_naive_and_normalizes_offsets() -> None:
    with pytest.raises(ValueError, match="AQ-TIME-NAIVE"):
        FixedClock(datetime(2026, 8, 31, 8))
    local = datetime(2026, 8, 31, 17, tzinfo=timezone(timedelta(hours=9)))
    assert ensure_utc(local) == datetime(2026, 8, 31, 8, tzinfo=UTC)


def test_point_in_time_gate_rejects_lookahead() -> None:
    decision = datetime(2026, 8, 31, 8, tzinfo=UTC)
    assert_point_in_time(available_time=decision, decision_time=decision)
    with pytest.raises(ValueError, match="AQ-TIME-LOOKAHEAD"):
        assert_point_in_time(
            available_time=decision + timedelta(microseconds=1), decision_time=decision
        )


def test_economic_values_reject_float_nonfinite_negative_zero_and_unit_mixing() -> None:
    with pytest.raises(ValidationError):
        Money(amount=1.25, asset_id=AssetId("USDT"))  # type: ignore[arg-type]
    for invalid in (Decimal("NaN"), Decimal("Infinity"), Decimal("-0")):
        with pytest.raises(ValidationError):
            Money(amount=invalid, asset_id=AssetId("USDT"))
    with pytest.raises(ValueError, match="cannot mix"):
        _ = Money(amount=Decimal("1"), asset_id=AssetId("USDT")) + Money(
            amount=Decimal("1"), asset_id=AssetId("USD")
        )


def test_price_uses_explicit_increment_rounding() -> None:
    value = Price(
        amount=Decimal("123.456"),
        base_asset_id=AssetId("BTC"),
        quote_asset_id=AssetId("USDT"),
    )
    assert value.quantize(Decimal("0.10"), RoundingMode.DOWN).amount == Decimal("123.40")
