from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.labels import ActionValueLabel, CostAssumption, generate_action_value_label
from tests.unit.labels.test_action_value_symmetry import action_prices


def test_each_action_pays_its_own_legs_funding_and_borrow() -> None:
    label = generate_action_value_label(
        observations=action_prices("110"),
        decision_index=0,
        horizon_steps=2,
        cost=CostAssumption(
            policy_version="directional",
            long_entry_cost=Decimal("0.01"),
            long_exit_cost=Decimal("0.02"),
            short_entry_cost=Decimal("0.03"),
            short_exit_cost=Decimal("0.04"),
            funding_rate=Decimal("0.001"),
            borrow_rate=Decimal("0.005"),
        ),
        long_risk_buffer=Decimal("0.002"),
        short_tail_risk_buffer=Decimal("0.003"),
    )
    assert label.net_value_long == Decimal("0.067")
    assert label.net_value_short == Decimal("-0.177")
    with pytest.raises(ValidationError, match="conserve"):
        ActionValueLabel.model_validate({**label.model_dump(), "net_value_short": Decimal("1")})
