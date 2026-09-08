from datetime import timedelta
from decimal import Decimal

from aegisquant.backtest.models import SpotBorrowPolicy
from aegisquant.domain.execution import OrderSide
from tests.p06.helpers import NOW, bars, engine, order, run_spec, spot_instrument, zero_cost_policy


def test_short_borrows_repays_and_accrues_quote_interest_over_real_elapsed_time() -> None:
    policy = zero_cost_policy()
    policy = policy.model_copy(
        update={
            "cost_schedules": tuple(
                schedule.model_copy(update={"borrow_rate_annual": Decimal("0.36525")})
                for schedule in policy.cost_schedules
            )
        }
    )
    values = list(bars(3, volume="100"))
    values[1] = values[1].model_copy(
        update={
            "open": Decimal("100"),
            "close": Decimal("100"),
            "low": Decimal("100"),
            "high": Decimal("100"),
        }
    )
    ending = NOW + timedelta(days=1, seconds=1)
    values[2] = values[2].model_copy(
        update={
            "event_time": ending,
            "available_time": ending,
            "open": Decimal("90"),
            "close": Decimal("90"),
            "low": Decimal("90"),
            "high": Decimal("90"),
        }
    )
    spec = run_spec(initial_cash="1000", end_time=ending).model_copy(
        update={
            "spot_borrow_policy": SpotBorrowPolicy(
                maximum_quantity=Decimal("2"),
                source="quote-settled deterministic borrow fixture",
            ),
        }
    )
    result = engine(policy).run(
        spec=spec,
        instrument=spot_instrument(),
        market_events=values,
        orders=(
            order(sequence=1, side=OrderSide.SELL),
            order(
                sequence=2, side=OrderSide.BUY, submitted_at=NOW + timedelta(seconds=2)
            ).model_copy(update={"reduce_only": True}),
        ),
    )
    assert result.positions[0].quantity == 0
    assert result.pnl_attribution[0].borrow_interest == Decimal("0.1")
    assert result.equity_curve[-1].equity == Decimal("1009.9")
    assert result.cost_identity_residual == 0
    types = [str(record.entry_template_id) for record in result.ledger_records]
    assert "borrow" in types and "repay" in types and "borrow-interest" in types


def test_borrow_limit_rejects_before_any_loan_or_fill() -> None:
    result = engine(zero_cost_policy()).run(
        spec=run_spec().model_copy(
            update={
                "spot_borrow_policy": SpotBorrowPolicy(
                    maximum_quantity=Decimal("0.5"),
                    source="finite borrow pool fixture",
                )
            }
        ),
        instrument=spot_instrument(),
        market_events=bars(),
        orders=(order(sequence=1, side=OrderSide.SELL),),
    )
    assert not result.fills
    assert len(result.ledger_records) == 1
    assert result.orders[0].rejection_code == "AQ-BACKTEST-SPOT-BORROW-LIMIT-EXCEEDED"
