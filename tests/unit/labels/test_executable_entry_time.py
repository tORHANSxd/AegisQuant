from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.labels import (
    CostAssumption,
    generate_action_value_label,
    generate_return_path_label,
)
from tests.unit.labels.test_action_value_symmetry import action_prices


def test_decision_bar_price_does_not_create_fictitious_profit() -> None:
    values = action_prices("101", decision_price="50")
    label = generate_action_value_label(
        observations=values,
        decision_index=0,
        horizon_steps=2,
        cost=CostAssumption(policy_version="zero"),
    )
    assert label.gross_long_return == Decimal("0.01")
    assert label.earliest_execution_time == values[1].event_time
    old_shape = generate_return_path_label(
        observations=values,
        decision_index=0,
        horizon_steps=2,
        cost=CostAssumption(policy_version="zero"),
        risk_flat_threshold=Decimal("0"),
    )
    assert old_shape.gross_return == label.gross_long_return
    assert old_shape.label_start_time == label.earliest_execution_time


def test_late_arriving_decision_cannot_trade_an_already_occurred_event() -> None:
    values = list(action_prices("101"))
    values[0] = values[0].model_copy(
        update={"available_time": values[1].event_time + timedelta(microseconds=1)}
    )
    with pytest.raises(ValueError, match="entry event occurred"):
        generate_action_value_label(
            observations=values,
            decision_index=0,
            horizon_steps=2,
            cost=CostAssumption(policy_version="zero"),
        )
