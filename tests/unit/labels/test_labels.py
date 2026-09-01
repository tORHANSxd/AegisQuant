from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.labels import (
    CostAssumption,
    DirectionClass,
    PricePathObservation,
    generate_event_impact_label,
    generate_execution_label,
    generate_return_labels,
    generate_return_path_label,
)

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)


def prices() -> tuple[PricePathObservation, ...]:
    return tuple(
        PricePathObservation(
            instrument_id="BINANCE:SPOT:BTCUSDT",
            event_time=NOW + timedelta(minutes=index),
            available_time=NOW + timedelta(minutes=index, seconds=1),
            executable_price=Decimal(value),
            source_dataset_id="executable-price-v1",
        )
        for index, value in enumerate(("100", "98", "104", "110", "105"))
    )


def cost() -> CostAssumption:
    return CostAssumption(
        policy_version="cost-v1",
        fee_rate=Decimal("0.001"),
        spread_rate=Decimal("0.001"),
        slippage_rate=Decimal("0.001"),
        impact_rate=Decimal("0.001"),
        borrow_rate=Decimal("0.0005"),
        funding_rate=Decimal("0.0005"),
    )


def test_return_path_label_is_future_cost_aware_and_path_complete() -> None:
    label = generate_return_path_label(
        observations=prices(),
        decision_index=0,
        horizon_steps=3,
        cost=cost(),
        risk_flat_threshold=Decimal("0.001"),
        overlap_count=3,
    )
    assert label.gross_return == Decimal("0.1")
    assert label.total_cost_rate == Decimal("0.005")
    assert label.net_return == Decimal("0.095")
    assert label.direction is DirectionClass.UP
    assert label.maximum_adverse_excursion == Decimal("-0.02")
    assert label.maximum_favorable_excursion == Decimal("0.1")
    assert label.q10_return <= label.q50_return <= label.q90_return
    assert label.overlap_weight == Decimal("0.3333333333333333333333333333")
    assert label.decision_time < label.label_start_time <= label.label_end_time


def test_overlapping_labels_have_deterministic_inverse_horizon_weight() -> None:
    labels = generate_return_labels(
        observations=prices(),
        horizon_steps=2,
        cost=cost(),
        risk_flat_threshold=Decimal("0"),
    )
    assert len(labels) == 3
    assert {item.overlap_weight for item in labels} == {Decimal("0.5")}
    assert all(item.net_return == item.gross_return - item.total_cost_rate for item in labels)


def test_label_generator_rejects_non_future_availability() -> None:
    values = list(prices())
    values[1] = values[1].model_copy(update={"available_time": values[0].available_time})
    with pytest.raises(ValueError, match="strictly increasing"):
        generate_return_path_label(
            observations=values,
            decision_index=0,
            horizon_steps=2,
            cost=cost(),
            risk_flat_threshold=Decimal("0"),
        )


def test_execution_and_event_labels_keep_future_windows_and_net_economics() -> None:
    execution = generate_execution_label(
        label_id="execution-1",
        decision_time=NOW,
        label_end_time=NOW + timedelta(minutes=1),
        attempts=4,
        fills=3,
        requested_quantity=Decimal("2"),
        filled_quantity=Decimal("1.5"),
        slippage_bps=Decimal("2"),
        adverse_selection_bps=Decimal("1"),
        post_cancel_fill=False,
        impact_bps=Decimal("0.5"),
        recovery_seconds=Decimal("30"),
        multi_leg_exposure_seconds=Decimal("4"),
    )
    assert execution.fill_probability == execution.fill_ratio == Decimal("0.75")

    event = generate_event_impact_label(
        label_id="event-impact-1",
        event_id="event-1",
        instrument_id="BINANCE:SPOT:BTCUSDT",
        first_observed_time=NOW,
        label_end_time=NOW + timedelta(hours=1),
        gross_return=Decimal("0.02"),
        cost=cost(),
        pre_volatility=Decimal("0.01"),
        post_volatility=Decimal("0.03"),
        downside_return=Decimal("-0.01"),
        spread_before_bps=Decimal("2"),
        spread_after_bps=Decimal("5"),
        funding_before=Decimal("0.0001"),
        funding_after=Decimal("0.0003"),
        event_persisted=True,
    )
    assert event.net_return == Decimal("0.015")
    assert event.volatility_change == Decimal("0.02")
    assert event.spread_change_bps == Decimal("3")

    with pytest.raises(ValidationError, match="future observation window"):
        execution.model_copy(update={"label_end_time": NOW}).model_validate(
            execution.model_copy(update={"label_end_time": NOW}).model_dump()
        )
