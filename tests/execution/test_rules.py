"""Dynamic instrument rule and precision gates."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.execution.rules import TradingStatus, quantize_order_values
from tests.p12_helpers import NOW, intent, reference_price, rules


def test_valid_order_uses_exact_point_in_time_rules() -> None:
    result = quantize_order_values(
        intent=intent(),
        rules=rules(),
        reference_price=reference_price(),
        decision_time=NOW + timedelta(seconds=2),
    )
    assert result.quantity.amount == Decimal("1")
    assert result.notional == Decimal("50000")


def test_illegal_precision_is_rejected_locally() -> None:
    with pytest.raises(ValueError, match="ILLEGAL-QUANTITY-PRECISION"):
        quantize_order_values(
            intent=intent(quantity=Decimal("1.0001")),
            rules=rules(),
            reference_price=reference_price(),
            decision_time=NOW + timedelta(seconds=2),
        )


def test_stale_and_close_only_rules_fail_closed() -> None:
    with pytest.raises(ValueError, match="RULE-STALE"):
        quantize_order_values(
            intent=intent(),
            rules=rules(),
            reference_price=reference_price(),
            decision_time=NOW + timedelta(hours=2),
        )
    close_only = rules().model_copy(update={"trading_status": TradingStatus.CLOSE_ONLY})
    with pytest.raises(ValueError, match="CLOSE-ONLY"):
        quantize_order_values(
            intent=intent(),
            rules=close_only,
            reference_price=reference_price(),
            decision_time=NOW + timedelta(seconds=2),
        )
