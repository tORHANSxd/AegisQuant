"""Golden cost arithmetic and conservative margin/liquidation tests."""

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.backtest.costs import (
    HistoricalCostBook,
    borrow_interest_cost,
    execution_price_and_cost,
    funding_cost,
    settlement_fee,
)
from aegisquant.backtest.margin import (
    create_liquidation_order,
    evaluate_margin,
    liquidation_instruction,
    require_leverage_allowed,
)
from aegisquant.backtest.models import FillPrecision, FillSlice, LiquidityRole, MarginMode
from aegisquant.domain.accounting import PostingSide
from aegisquant.domain.execution import OrderSide, VenueOrderStatus
from aegisquant.domain.identifiers import BacktestEventId, CostScheduleId
from tests.p06.helpers import (
    NOW,
    USDT,
    VENUE,
    engine,
    order,
    perp_bars,
    perp_instrument,
    perp_order,
    policy,
    run_spec,
)


def test_fee_spread_slippage_and_impact_match_hand_calculation() -> None:
    schedule = policy().cost_schedules[0]
    candidate = order(sequence=1, side=OrderSide.BUY, quantity="10")
    fill_slice = FillSlice(
        quantity=Decimal("10"),
        reference_price=Decimal("100"),
        available_liquidity=Decimal("20"),
        precision=FillPrecision.L2_DEPTH,
        liquidity_role=LiquidityRole.TAKER,
        source_event_id=BacktestEventId("cost-golden-event"),
        event_time=NOW,
        available_time=NOW,
    )

    price, cost = execution_price_and_cost(
        order=candidate,
        fill_slice=fill_slice,
        schedule=schedule,
        base_asset_id=candidate.quantity.asset_id,
        quote_asset_id=USDT,
    )

    assert price.amount == Decimal("100.0500")
    assert cost.gross_notional == Decimal("1000")
    assert cost.fee == Decimal("0.200100")
    assert cost.spread == Decimal("0.1")
    assert cost.slippage == Decimal("0.2")
    assert cost.impact == Decimal("0.20")
    assert cost.total == Decimal("0.700100")


def test_funding_borrow_and_settlement_costs_match_hand_calculation() -> None:
    perp_schedule = policy().cost_schedules[1]

    assert funding_cost(
        signed_quantity=Decimal("2"),
        mark_price=Decimal("100"),
        funding_rate=Decimal("0.0001"),
    ) == Decimal("0.0200")
    assert borrow_interest_cost(
        borrowed_notional=Decimal("1000"),
        annual_rate=Decimal("0.10"),
        elapsed_seconds=31_557_600,
    ) == Decimal("100.00")
    assert settlement_fee(notional=Decimal("1000"), schedule=perp_schedule) == Decimal("0.1")


def test_margin_bracket_breach_produces_explicit_reduce_only_liquidation() -> None:
    margin_policy = policy().margin_policies[0]
    evaluation = evaluate_margin(
        policy=margin_policy,
        signed_quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("80"),
        collateral=Decimal("30"),
    )

    assert evaluation.notional == Decimal("800")
    assert evaluation.maintenance_margin == Decimal("20.000")
    assert evaluation.buffered_maintenance_margin == Decimal("22.0000")
    assert evaluation.equity == Decimal("-170")
    assert evaluation.liquidation_required is True
    instruction = liquidation_instruction(evaluation=evaluation, policy=margin_policy)
    assert instruction.side is OrderSide.SELL
    assert instruction.liquidation_price == Decimal("79.600")
    assert instruction.penalty == Decimal("4.00")

    liquidation = create_liquidation_order(
        instruction=instruction,
        instrument=perp_instrument(),
        venue_id=VENUE,
        decision_time=NOW,
        identity="margin-golden",
    )
    assert liquidation.reduce_only is True
    assert liquidation.quantity.amount == Decimal("10")
    assert liquidation.side is OrderSide.SELL


def test_historical_margin_bracket_rejects_excess_leverage() -> None:
    margin_policy = policy().margin_policies[0]
    assert require_leverage_allowed(
        policy=margin_policy,
        notional=Decimal("800"),
        collateral=Decimal("100"),
    ) == Decimal("8")
    with pytest.raises(ValueError, match="AQ-BACKTEST-MARGIN-LEVERAGE-EXCEEDED"):
        require_leverage_allowed(
            policy=margin_policy,
            notional=Decimal("800"),
            collateral=Decimal("10"),
        )


def test_historical_cost_schedule_changes_at_exact_effective_time() -> None:
    base = policy().cost_schedules[0]
    cutoff = NOW + timedelta(seconds=2)
    earlier = base.model_copy(update={"effective_to": cutoff})
    later = base.model_copy(
        update={
            "cost_schedule_id": CostScheduleId("cost-after-change"),
            "version": "cost-v2",
            "effective_from": cutoff,
            "effective_to": None,
            "taker_fee_bps": Decimal("3"),
        }
    )
    book = HistoricalCostBook((earlier, later))
    candidate = order(sequence=99, side=OrderSide.BUY)

    assert book.at(candidate, cutoff - timedelta(microseconds=1)).version == "cost-v1"
    selected = book.at(candidate, cutoff)
    assert selected.version == "cost-v2"
    assert selected.taker_fee_bps == Decimal("3")


def test_liquidation_order_closes_position_through_authoritative_balanced_ledger() -> None:
    selected = policy().margin_policies[0]
    evaluation = evaluate_margin(
        policy=selected,
        signed_quantity=Decimal("10"),
        entry_price=Decimal("100"),
        mark_price=Decimal("80"),
        collateral=Decimal("30"),
    )
    instruction = liquidation_instruction(evaluation=evaluation, policy=selected)
    opening = perp_order(
        sequence=1,
        side=OrderSide.BUY,
        quantity="10",
        submitted_at=NOW + timedelta(microseconds=1),
    )
    liquidation = create_liquidation_order(
        instruction=instruction,
        instrument=perp_instrument(),
        venue_id=VENUE,
        decision_time=NOW + timedelta(seconds=2, microseconds=1),
        identity="ledger-golden",
    )

    result = engine().run(
        spec=run_spec(run_id="p06-liquidation-ledger"),
        instrument=perp_instrument(),
        market_events=perp_bars(),
        orders=(opening, liquidation),
    )

    assert [item.status for item in result.orders] == [
        VenueOrderStatus.FILLED,
        VenueOrderStatus.FILLED,
    ]
    assert result.positions[0].quantity == 0
    assert liquidation.reduce_only is True
    for record in result.ledger_records:
        balances: dict[str, Decimal] = {}
        for posting in record.journal_entry.postings:
            sign = Decimal("1") if posting.side is PostingSide.DEBIT else Decimal("-1")
            asset = str(posting.amount.asset_id)
            balances[asset] = balances.get(asset, Decimal("0")) + sign * posting.amount.amount
        assert all(value == 0 for value in balances.values())


def test_isolated_margin_mode_is_preserved_in_evaluation_contract() -> None:
    isolated = policy().margin_policies[0].model_copy(update={"mode": MarginMode.ISOLATED})
    evaluation = evaluate_margin(
        policy=isolated,
        signed_quantity=Decimal("1"),
        entry_price=Decimal("100"),
        mark_price=Decimal("100"),
        collateral=Decimal("100"),
    )
    assert evaluation.mode is MarginMode.ISOLATED
