from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.labels import (
    CostAssumption,
    DirectionClass,
    PricePathObservation,
    generate_action_value_label,
)


def action_prices(
    exit_price: str, *, decision_price: str = "100"
) -> tuple[PricePathObservation, ...]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        PricePathObservation(
            instrument_id="BINANCE:SPOT:BTCUSDT",
            event_time=now + timedelta(hours=i),
            available_time=now + timedelta(hours=i, seconds=1),
            executable_price=Decimal(price),
            source_dataset_id="action-value-test",
        )
        for i, price in enumerate((decision_price, "100", exit_price))
    )


@pytest.mark.parametrize(
    "exit_price,expected",
    [
        ("101.5", DirectionClass.UP),
        ("98.5", DirectionClass.DOWN),
        ("100.5", DirectionClass.FLAT),
        ("99.5", DirectionClass.FLAT),
    ],
)
def test_symmetric_round_trip_costs_do_not_bias_down(
    exit_price: str, expected: DirectionClass
) -> None:
    label = generate_action_value_label(
        observations=action_prices(exit_price),
        decision_index=0,
        horizon_steps=2,
        cost=CostAssumption(policy_version="symmetric-v4", fee_rate=Decimal("0.01")),
    )
    assert label.best_action is expected
    assert label.gross_long_return == -label.gross_short_return
    assert (
        label.long_entry_cost + label.long_exit_cost
        == label.short_entry_cost + label.short_exit_cost
        == Decimal("0.01")
    )


def test_uncertainty_requires_strict_economic_margin() -> None:
    label = generate_action_value_label(
        observations=action_prices("101"),
        decision_index=0,
        horizon_steps=2,
        cost=CostAssumption(policy_version="zero"),
        uncertainty_buffer=Decimal("0.005"),
        minimum_economic_margin=Decimal("0.005"),
    )
    assert label.action_margin == Decimal("0.01")
    assert label.best_action is DirectionClass.FLAT
