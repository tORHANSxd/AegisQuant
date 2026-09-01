"""Fill precision, cancellation races, disconnects and non-atomic legs."""

from datetime import timedelta
from decimal import Decimal

from aegisquant.backtest.costs import HistoricalCostBook
from aegisquant.backtest.engine import EventBacktestEngine
from aegisquant.backtest.fills import decide_fills
from aegisquant.backtest.models import (
    BacktestResult,
    CancelRequest,
    FaultType,
    FaultWindow,
    FillPrecision,
    MultiLegPlan,
)
from aegisquant.backtest.rules import HistoricalRuleBook
from aegisquant.domain.accounting import PostingSide
from aegisquant.domain.execution import OrderSide, VenueOrderStatus
from aegisquant.domain.identifiers import (
    BacktestEventId,
    CostScheduleId,
    InstrumentRuleId,
    MultiLegPlanId,
    VenueId,
)
from tests.p06.helpers import (
    NOW,
    ROOT,
    VENUE,
    bars,
    engine,
    l2_book,
    order,
    policy,
    run_spec,
    spot_instrument,
    trade_quote,
)


def _assert_ledger_balanced(result: BacktestResult) -> None:
    for record in result.ledger_records:
        balances: dict[str, Decimal] = {}
        for posting in record.journal_entry.postings:
            sign = Decimal("1") if posting.side is PostingSide.DEBIT else Decimal("-1")
            asset = str(posting.amount.asset_id)
            balances[asset] = balances.get(asset, Decimal("0")) + sign * posting.amount.amount
        assert all(value == 0 for value in balances.values())


def test_bar_trade_quote_and_l2_fill_precision_are_explicit() -> None:
    candidate = order(sequence=1, side=OrderSide.BUY, quantity="2")
    bar_slices = decide_fills(
        order=candidate,
        event=bars(2, volume="1")[1],
        remaining=Decimal("2"),
        participation_cap=Decimal("0.5"),
    )
    quote_slices = decide_fills(
        order=candidate,
        event=trade_quote(quantity="2"),
        remaining=Decimal("2"),
        participation_cap=Decimal("1"),
    )
    depth_slices = decide_fills(
        order=candidate,
        event=l2_book(),
        remaining=Decimal("2"),
        participation_cap=Decimal("1"),
    )

    assert bar_slices[0].quantity == Decimal("0.5")
    assert bar_slices[0].precision is FillPrecision.BAR_CONSERVATIVE
    assert quote_slices[0].precision is FillPrecision.TRADE_QUOTE
    assert sum(item.quantity for item in depth_slices) == Decimal("2")
    assert all(item.precision is FillPrecision.L2_DEPTH for item in depth_slices)


def test_disconnect_enters_unknown_without_blind_resubmit_or_fill() -> None:
    candidate = order(sequence=1, side=OrderSide.BUY)
    fault = FaultWindow(
        fault_type=FaultType.REQUEST_TIMEOUT,
        venue_id=VENUE,
        starts_at=NOW,
        ends_at=NOW + timedelta(seconds=2),
        evidence="recorded deterministic request timeout",
    )
    result = engine().run(
        spec=run_spec(run_id="p06-timeout"),
        instrument=spot_instrument(),
        market_events=bars(),
        orders=(candidate,),
        faults=(fault,),
    )

    assert result.orders[0].status is VenueOrderStatus.UNKNOWN
    assert result.orders[0].unknown_reason == "AQ-BACKTEST-ORDER-ACK-TIMEOUT"
    assert "requery-required:no-blind-resubmit" in result.orders[0].recovery_evidence
    assert result.fills == ()
    _assert_ledger_balanced(result)


def test_market_event_wins_equal_time_cancel_race_but_earlier_cancel_wins() -> None:
    candidate = order(sequence=1, side=OrderSide.BUY)
    event_time = bars()[1].available_time
    equal_request = CancelRequest(
        backtest_order_id=candidate.backtest_order_id,
        requested_at=event_time - timedelta(milliseconds=1),
    )
    equal_result = engine().run(
        spec=run_spec(run_id="p06-cancel-equal"),
        instrument=spot_instrument(),
        market_events=bars(),
        orders=(candidate,),
        cancel_requests=(equal_request,),
    )
    assert equal_result.orders[0].status is VenueOrderStatus.FILLED

    early_request = equal_request.model_copy(
        update={"requested_at": event_time - timedelta(milliseconds=2)}
    )
    early_result = engine().run(
        spec=run_spec(run_id="p06-cancel-early"),
        instrument=spot_instrument(),
        market_events=bars(),
        orders=(candidate,),
        cancel_requests=(early_request,),
    )
    assert early_result.orders[0].status is VenueOrderStatus.CANCELED
    assert early_result.fills == ()


def test_partial_fill_and_failed_second_leg_preserve_balanced_ledger() -> None:
    plan_id = MultiLegPlanId("p06-plan-failed-leg")
    first = order(sequence=1, side=OrderSide.BUY, quantity="1").model_copy(
        update={"multi_leg_plan_id": plan_id, "leg_index": 0}
    )
    second = order(
        sequence=2,
        side=OrderSide.BUY,
        quantity="2",
        submitted_at=NOW + timedelta(microseconds=2),
    ).model_copy(update={"multi_leg_plan_id": plan_id, "leg_index": 1})
    plan = MultiLegPlan(
        multi_leg_plan_id=plan_id,
        orders=(first, second),
        maximum_exposure_ns=2_000_000_000,
    )
    result = engine().run(
        spec=run_spec(run_id="p06-multileg-failure"),
        instrument=spot_instrument(),
        market_events=(bars(2, volume="1")[1],),
        orders=(first, second),
        multi_leg_plans=(plan,),
        failed_leg_indices={plan_id: 1},
    )

    assert result.orders[0].status is VenueOrderStatus.PARTIALLY_FILLED
    assert result.orders[0].cumulative_filled_quantity == Decimal("0.5")
    assert result.orders[1].status is VenueOrderStatus.REJECTED
    assert result.orders[1].rejection_code == "AQ-BACKTEST-MULTILEG-LEG-FAILURE"
    assert result.multi_leg_exposures[0].filled_legs == 1
    assert result.multi_leg_exposures[0].failed_leg_index == 1
    _assert_ledger_balanced(result)


def test_cross_venue_legs_execute_sequentially_without_rollback() -> None:
    selected = policy()
    second_venue = VenueId("SIM2")
    second_cost = selected.cost_schedules[0].model_copy(
        update={
            "cost_schedule_id": CostScheduleId("sim2-btcusdt-cost-v1"),
            "venue_id": second_venue,
        }
    )
    second_rule = selected.instrument_rules[0].model_copy(
        update={
            "instrument_rule_id": InstrumentRuleId("sim2-btcusdt-rule-v1"),
            "venue_id": second_venue,
        }
    )
    event_engine = EventBacktestEngine(
        project_root=ROOT,
        cost_book=HistoricalCostBook((selected.cost_schedules[0], second_cost)),
        rule_book=HistoricalRuleBook((selected.instrument_rules[0], second_rule)),
        latency_policy=selected.latency_policy,
    )
    plan_id = MultiLegPlanId("p06-cross-venue-plan")
    first = order(sequence=60, side=OrderSide.BUY).model_copy(
        update={"multi_leg_plan_id": plan_id, "leg_index": 0}
    )
    second = order(
        sequence=61,
        side=OrderSide.SELL,
        submitted_at=NOW + timedelta(microseconds=2),
    ).model_copy(
        update={
            "venue_id": second_venue,
            "multi_leg_plan_id": plan_id,
            "leg_index": 1,
        }
    )
    plan = MultiLegPlan(
        multi_leg_plan_id=plan_id,
        orders=(first, second),
        maximum_exposure_ns=2_000_000_000,
    )
    first_event = bars(2)[1]
    second_event = first_event.model_copy(
        update={
            "event_id": BacktestEventId("sim2-bar-1"),
            "venue_id": second_venue,
        }
    )

    result = event_engine.run(
        spec=run_spec(run_id="p06-cross-venue"),
        instrument=spot_instrument(),
        market_events=(first_event, second_event),
        orders=(first, second),
        multi_leg_plans=(plan,),
    )

    assert [item.status for item in result.orders] == [
        VenueOrderStatus.FILLED,
        VenueOrderStatus.FILLED,
    ]
    assert [str(fill.source_event_id) for fill in result.fills] == ["bar-1", "sim2-bar-1"]
    assert result.positions[0].quantity == 0
    assert result.multi_leg_exposures[0].filled_legs == 2
    _assert_ledger_balanced(result)
