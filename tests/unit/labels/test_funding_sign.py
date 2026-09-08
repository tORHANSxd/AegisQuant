from decimal import Decimal

import pytest

from aegisquant.labels import CostAssumption, DirectionClass, generate_action_value_label
from tests.unit.labels.test_action_value_symmetry import action_prices


@pytest.mark.parametrize(
    "funding,action", [("0.001", DirectionClass.DOWN), ("-0.001", DirectionClass.UP)]
)
def test_signed_funding_is_a_payment_for_one_side_and_receipt_for_other(
    funding: str, action: DirectionClass
) -> None:
    rate = Decimal(funding)
    label = generate_action_value_label(
        observations=action_prices("100"),
        decision_index=0,
        horizon_steps=2,
        cost=CostAssumption(policy_version="funding", funding_rate=rate),
    )
    assert label.expected_funding_long == rate
    assert label.expected_funding_short == -rate
    assert label.net_value_long == -rate
    assert label.net_value_short == rate
    assert label.best_action is action


def test_borrow_is_only_charged_to_short() -> None:
    label = generate_action_value_label(
        observations=action_prices("100"),
        decision_index=0,
        horizon_steps=2,
        cost=CostAssumption(
            policy_version="borrow", funding_rate=Decimal("0.001"), borrow_rate=Decimal("0.002")
        ),
    )
    assert label.net_value_long == label.net_value_short == Decimal("-0.001")
    assert label.best_action is DirectionClass.FLAT
