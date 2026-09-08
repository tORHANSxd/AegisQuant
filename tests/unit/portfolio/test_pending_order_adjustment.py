from decimal import Decimal

from aegisquant.portfolio.optimizer import target_quantity_adjustment


def test_pending_quantity_is_subtracted_and_opposing_pending_is_cancelled_first() -> None:
    result = target_quantity_adjustment(
        target_quantity=Decimal("10"),
        current_quantity=Decimal("4"),
        signed_pending_quantity=Decimal("3"),
        price=Decimal("100"),
        quantity_step=Decimal("0.1"),
        minimum_notional=Decimal("10"),
    )
    assert result.signed_order_quantity == 3
    changed_target = target_quantity_adjustment(
        target_quantity=Decimal("4"),
        current_quantity=Decimal("4"),
        signed_pending_quantity=Decimal("3"),
        price=Decimal("100"),
        quantity_step=Decimal("0.1"),
        minimum_notional=Decimal("10"),
    )
    assert changed_target.cancel_pending_first
    assert changed_target.signed_order_quantity == 0
