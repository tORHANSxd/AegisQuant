from decimal import Decimal

from aegisquant.portfolio.optimizer import target_quantity_adjustment


def test_repeating_filled_or_pending_target_does_not_place_another_order() -> None:
    for current, pending in (("10", "0"), ("4", "6")):
        result = target_quantity_adjustment(
            target_quantity=Decimal("10"),
            current_quantity=Decimal(current),
            signed_pending_quantity=Decimal(pending),
            price=Decimal("100"),
            quantity_step=Decimal("0.1"),
            minimum_notional=Decimal("10"),
        )
        assert result.signed_order_quantity == 0
        assert not result.cancel_pending_first
