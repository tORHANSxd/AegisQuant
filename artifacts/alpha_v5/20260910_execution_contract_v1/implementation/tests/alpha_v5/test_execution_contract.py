"""B4 synthetic cost, liquidity, native-ledger and report checks; no strategy replay."""

from __future__ import annotations

import copy
import json
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from aegisquant.accounting.ledger import AccountingPolicy, LedgerEngine
from aegisquant.accounting.models import (
    AccountRole,
    CashflowDirection,
    CashflowEvent,
    CashflowType,
    FxRate,
    ValuationQuote,
)
from aegisquant.backtest.costs import (
    FeeAccountState,
    HistoricalCostBook,
    execution_price_and_cost,
    settle_execution_fee,
)
from aegisquant.backtest.fills import EventLiquidityBudget, ParticipationWindow, decide_fills
from aegisquant.backtest.models import (
    CommissionRates,
    CostSchedule,
    ExecutionCostEvidence,
    ExecutionReference,
    FeeTerms,
    FillPrecision,
    FillSlice,
    LiquidityRole,
)
from aegisquant.data.hashing import sha256_file
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import ArtifactId, AssetId, BacktestEventId, IdempotencyKey
from aegisquant.domain.values import Money, Price
from aegisquant.portfolio.models import SignalInput
from aegisquant.portfolio.optimizer import (
    _capacity_weight,  # pyright: ignore[reportPrivateUsage] -- test the actual internal capacity boundary.
)
from aegisquant.portfolio.transition_costs import (
    ImpactModel,
    estimate_spot_transition_costs,
    legacy_impact_model,
)
from aegisquant.research.validation import evidence_contract as evidence
from aegisquant.research.validation import execution_contract as contract
from tests.alpha_v5.test_benchmark_contract import r5_fixture
from tests.p05 import helpers as accounting
from tests.p05.test_ledger_core import assert_balanced_by_asset
from tests.p06.helpers import BTC, NOW, USDT, bars, l2_book, order, policy, trade_quote
from tests.p11_helpers import construction_policy, signal

ROOT = Path(__file__).resolve().parents[2]
D = Decimal
HASH = "1" * 64
BNB = AssetId("BNB")


def curve(model: str = "LINEAR_PROXY_V1", coefficient: str = "10", cap: str = "1") -> ImpactModel:
    return ImpactModel.model_validate(
        {
            "model_id": model,
            "coefficient_bps": D(coefficient),
            "horizon_seconds": 60,
            "participation_unit": "ORDER_QUOTE_NOTIONAL_OVER_WINDOW_QUOTE_TURNOVER",
            "target": "TOTAL_PRICE_IMPACT",
            "evidence_status": "PROXY_ONLY",
            "maximum_supported_participation": D(cap),
        }
    )


def execution_pair(
    kind: str, price: str, included: tuple[str, ...] = ()
) -> tuple[FillSlice, CostSchedule]:
    reference = ExecutionReference.model_validate(
        {
            "reference_price_kind": kind,
            "included_cost_components": included,
            "source_sha256": HASH,
            "evidence_kind": "PROXY_ONLY" if kind == "BAR_OPEN_PROXY" else "SYNTHETIC_ONLY",
            "participation_window_seconds": 60,
            "window_quote_turnover": D("10000"),
        }
    )
    fill = FillSlice(
        quantity=D("1"),
        reference_price=D(price),
        available_liquidity=D("100"),
        precision=FillPrecision.L2_DEPTH,
        liquidity_role=LiquidityRole.TAKER,
        source_event_id=BacktestEventId("synthetic-reference"),
        event_time=NOW,
        available_time=NOW,
        reference=reference,
    )
    schedule = CostSchedule.model_validate(
        {
            **dict(policy().cost_schedules[0]),
            "maker_fee_bps": D("0"),
            "taker_fee_bps": D("0"),
            "half_spread_bps": D("10"),
            "slippage_bps": D("0"),
            "impact_coefficient_bps": D("0"),
            "evidence": ExecutionCostEvidence(
                account_scope="SYNTHETIC_ACCOUNT",
                available_at=NOW,
                source_sha256=HASH,
                verified_kind="SYNTHETIC_ONLY",
                impact_model=curve(coefficient="0"),
            ),
        }
    )
    return fill, schedule


@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
def test_mid_and_bbo_charge_spread_exactly_once(side: OrderSide) -> None:
    mid, schedule = execution_pair("MID", "100")
    bbo, _ = execution_pair("BBO", "100.1" if side is OrderSide.BUY else "99.9", ("SPREAD",))
    candidate = order(sequence=1, side=side)
    priced = [
        execution_price_and_cost(
            order=candidate,
            fill_slice=value,
            schedule=schedule,
            base_asset_id=BTC,
            quote_asset_id=USDT,
        )
        for value in (mid, bbo)
    ]
    assert priced[0][0] == priced[1][0]
    assert priced[0][1].spread == D("0.1") and priced[1][1].spread == 0


def test_depth_includes_visible_impact_and_explicit_residual_is_separate() -> None:
    fill, schedule = execution_pair("DEPTH_VWAP", "101", ("SPREAD", "VISIBLE_DEPTH"))
    proof = schedule.evidence
    assert proof is not None
    schedule = CostSchedule.model_validate(
        {
            **dict(schedule),
            "impact_coefficient_bps": D("10"),
            "evidence": proof.model_copy(update={"impact_model": curve()}),
        }
    )
    args: dict[str, Any] = dict(
        order=order(sequence=1, side=OrderSide.BUY),
        fill_slice=fill,
        schedule=schedule,
        base_asset_id=BTC,
        quote_asset_id=USDT,
    )
    price, cost = execution_price_and_cost(**args)
    assert price.amount == 101 and cost.spread == cost.impact == 0
    residual_curve = curve().model_copy(update={"target": "RESIDUAL_BEYOND_REFERENCE"})
    residual = schedule.model_copy(
        update={"evidence": proof.model_copy(update={"impact_model": residual_curve})}
    )
    residual_args: dict[str, Any] = {**args, "schedule": residual}
    _, residual_cost = execution_price_and_cost(**residual_args)
    assert residual_cost.impact > 0
    with pytest.raises(ValueError, match="EMPIRICAL-EVIDENCE"):
        execution_price_and_cost(**args, strict_evidence=True)


@pytest.mark.parametrize(
    "bad",
    [
        "unknown_bbo_component",
        "mid_includes_spread",
        "bar_is_real",
        "mixed_version",
        "wrong_horizon",
    ],
)
def test_reference_evidence_conflicts_fail(bad: str) -> None:
    fill, schedule = execution_pair("MID", "100")
    assert fill.reference is not None and schedule.evidence is not None
    if bad in {"unknown_bbo_component", "mid_includes_spread", "bar_is_real"}:
        changes = {
            "unknown_bbo_component": {"reference_price_kind": "BBO"},
            "mid_includes_spread": {"included_cost_components": ("SPREAD",)},
            "bar_is_real": {
                "reference_price_kind": "BAR_OPEN_PROXY",
                "evidence_kind": "HISTORICAL_MARKET_EVIDENCE",
            },
        }[bad]
        with pytest.raises(ValueError):
            ExecutionReference.model_validate({**fill.reference.model_dump(), **changes})
    else:
        changed = fill.model_copy(
            update={
                "reference": None
                if bad == "mixed_version"
                else fill.reference.model_copy(update={"participation_window_seconds": 3600})
            }
        )
        with pytest.raises(ValueError):
            execution_price_and_cost(
                order=order(sequence=1, side=OrderSide.BUY),
                fill_slice=changed,
                schedule=schedule,
                base_asset_id=BTC,
                quote_asset_id=USDT,
            )


@pytest.mark.parametrize("model", ["LINEAR_PROXY_V1", "SQRT_PROXY_V1"])
def test_impact_forward_inverse_and_capacity_use_one_horizon(model: str) -> None:
    selected = curve(model, "100", "0.5")
    for participation in map(D, ("0", "0.01", "0.25", "0.5")):
        assert (
            selected.participation_for_impact(selected.impact_bps(participation)) == participation
        )
    base = signal(
        asset=BTC,
        instrument="SYNTHETIC-BTC",
        adv=D("10000"),
        impact_bps=D("100"),
        raw_score=D("1"),
        confidence=D("1"),
    )
    versioned = SignalInput.model_validate(
        {**dict(base), "impact_model": selected, "liquidity_horizon_seconds": 60}
    )
    cap = _capacity_weight(versioned, nav=D("1000"), policy=construction_policy())
    assert cap == D("10") * min(
        construction_policy().maximum_participation,
        selected.participation_for_impact(construction_policy().maximum_impact_bps),
    )
    with pytest.raises(ValueError, match="HORIZON"):
        SignalInput.model_validate(
            {**dict(base), "impact_model": selected, "liquidity_horizon_seconds": 86400}
        )
    with pytest.raises(ValueError, match="OUTSIDE"):
        selected.impact_bps(D("0.5001"))
    assert selected.participation_for_impact(D("1000")) == D("0.5")


def test_legacy_capacity_and_new_linear_capacity_are_explicitly_different() -> None:
    legacy = legacy_impact_model(D("100"), capacity=True)
    assert legacy.participation_for_impact(D("10")) == D("0.01")
    assert curve(coefficient="100").participation_for_impact(D("10")) == D("0.1")
    assert curve(coefficient="0", cap="0.4").participation_for_impact(D("0")) == D("0.4")


def fee_terms() -> FeeTerms:
    return FeeTerms(
        standard=CommissionRates(maker=D("8"), taker=D("10"), buyer=D("1"), seller=D("2")),
        special=CommissionRates(maker=D("1"), taker=D("1")),
        tax=CommissionRates(maker=D("2"), taker=D("2")),
        normal_fee_asset="RECEIVED_ASSET",
        discount_asset_id=BNB,
        standard_discount_fraction=D("0.25"),
        discount_effective_from=NOW - timedelta(days=1),
        discount_effective_to=NOW + timedelta(days=1),
    )


def fee_args() -> dict[str, Any]:
    return dict(
        terms=fee_terms(),
        fill_time=NOW,
        role=LiquidityRole.TAKER,
        side=OrderSide.BUY,
        quantity=D("2"),
        execution_price=D("100"),
        base_asset_id=BTC,
        quote_asset_id=USDT,
        available_balances={BNB: D("1"), USDT: D("1000")},
        quote_fx={BNB: D("250")},
        fx_available_at=NOW,
    )


def test_discount_only_reduces_standard_fee_and_partial_fills_consume_actual_balance() -> None:
    args = fee_args()
    first = settle_execution_fee(**args)
    assert first.undiscounted_quote_equivalent == D("0.28")
    assert first.quote_equivalent == D("0.225") and first.fee.amount == D("0.0009")
    assert first.fee.asset_id == BNB and first.discount_applied
    low_balance: dict[str, Any] = {**args, "available_balances": {BNB: first.fee.amount}}
    paid = settle_execution_fee(**low_balance)
    exhausted_balance: dict[str, Any] = {**low_balance, "available_balances": {BNB: D("0")}}
    second = settle_execution_fee(**exhausted_balance)
    assert paid.discount_applied and not second.discount_applied
    assert second.fee.asset_id == BTC and second.fee.amount == D("0.0028")
    assert second.fallback_reason == "DISCOUNT_ASSET_BALANCE_INSUFFICIENT"


@pytest.mark.parametrize("cause", ["expired", "missing_fx", "future_fx", "insufficient_normal"])
def test_discount_boundaries_and_fx_are_fail_closed(cause: str) -> None:
    args = fee_args()
    if cause == "expired":
        args["fill_time"] = fee_terms().discount_effective_to
        assert settle_execution_fee(**args).fallback_reason == "DISCOUNT_NOT_EFFECTIVE"
    elif cause == "missing_fx":
        args["quote_fx"] = {}
        assert settle_execution_fee(**args).fallback_reason == "DISCOUNT_FX_UNAVAILABLE"
    else:
        if cause == "future_fx":
            args["fx_available_at"] = NOW + timedelta(microseconds=1)
        else:
            args["terms"] = fee_terms().model_copy(update={"normal_fee_asset": "QUOTE"})
            args["available_balances"] = {}
        with pytest.raises(ValueError):
            settle_execution_fee(**args)


def test_fee_effective_time_is_not_decision_known_time_and_future_revisions_do_not_leak() -> None:
    _, base = execution_pair("MID", "100")
    assert base.evidence is not None
    proof = base.evidence.model_copy(
        update={
            "available_at": NOW + timedelta(hours=1),
            "verified_kind": "HISTORICAL_ACCOUNT_EVIDENCE",
        }
    )
    late = base.model_copy(update={"evidence": proof})
    book = HistoricalCostBook((late,))
    candidate = order(sequence=1, side=OrderSide.BUY)
    assert book.at(candidate, NOW) == late
    with pytest.raises(ValueError, match="UNKNOWN-AT-DECISION"):
        book.decision_at(candidate, NOW)
    mutated = late.model_copy(
        update={
            "evidence": proof.model_copy(update={"source_sha256": "2" * 64}),
            "taker_fee_bps": D("70"),
        }
    )
    with pytest.raises(ValueError, match="UNKNOWN-AT-DECISION"):
        HistoricalCostBook((mutated,)).decision_at(candidate, NOW)
    assert book.decision_at(candidate, NOW + timedelta(hours=1)) == late


def test_native_fee_contract_cannot_silently_use_old_quote_fee_engine_path() -> None:
    fill, schedule = execution_pair("BBO", "100", ("SPREAD",))
    assert schedule.evidence is not None
    schedule = schedule.model_copy(
        update={"evidence": schedule.evidence.model_copy(update={"fee_terms": fee_terms()})}
    )
    args: dict[str, Any] = dict(
        order=order(sequence=1, side=OrderSide.BUY),
        fill_slice=fill,
        schedule=schedule,
        base_asset_id=BTC,
        quote_asset_id=USDT,
    )
    with pytest.raises(ValueError, match="ACCOUNT-STATE-REQUIRED"):
        execution_price_and_cost(**args)
    _, cost = execution_price_and_cost(
        **args, fee_account=FeeAccountState({BNB: D("1")}, {BNB: D("250")}, NOW)
    )
    assert cost.fee_settlement is not None
    assert (
        cost.fee == cost.fee_settlement.quote_equivalent and cost.fee_settlement.fee.asset_id == BNB
    )


def window(event: Any, turnover: str = "10000") -> ParticipationWindow:
    return ParticipationWindow(
        window_id="SYNTHETIC_WINDOW",
        instrument_id=event.instrument_id,
        venue_id=event.venue_id,
        start=event.event_time - timedelta(seconds=60),
        end=event.event_time,
        available_at=event.available_time,
        quote_turnover=D(turnover),
        source_sha256=HASH,
    )


def test_shared_depth_cannot_be_reused_and_fill_identity_is_idempotent() -> None:
    event = l2_book()
    budget = EventLiquidityBudget(window(event), D("1"))
    first = order(sequence=1, side=OrderSide.BUY)
    one = budget.preview(order=first, event=event, remaining=D("1"), arrival_at=first.submitted_at)
    assert one.slices[0].reference_price == D("100.01")
    assert budget.used_quote_notional == 0
    assert budget.commit(fill_id="f1", order=first, item=one.slices[0])
    assert not budget.commit(fill_id="f1", order=first, item=one.slices[0])
    second = order(sequence=2, side=OrderSide.BUY)
    two = budget.preview(
        order=second, event=event, remaining=D("1"), arrival_at=second.submitted_at
    )
    assert two.slices[0].reference_price == D("100.02") and two.unfilled_quantity == 0
    with pytest.raises(ValueError, match="CONFLICTING-FILL"):
        budget.commit(fill_id="f1", order=second, item=two.slices[0])
    altered = event.model_copy(update={"asks": event.asks[::-1]})
    with pytest.raises(ValueError, match="CONFLICTING-MARKET"):
        budget.preview(
            order=second, event=altered, remaining=D("1"), arrival_at=second.submitted_at
        )


def test_shared_window_does_not_net_opposite_sides_and_preserves_fok_residual() -> None:
    event = l2_book()
    budget = EventLiquidityBudget(window(event, "150"), D("1"))
    buy = order(sequence=1, side=OrderSide.BUY)
    one = budget.preview(order=buy, event=event, remaining=D("1"), arrival_at=buy.submitted_at)
    budget.commit(fill_id="buy", order=buy, item=one.slices[0])
    sell = order(sequence=2, side=OrderSide.SELL, time_in_force=TimeInForce.FILL_OR_KILL)
    denied = budget.preview(order=sell, event=event, remaining=D("1"), arrival_at=sell.submitted_at)
    assert not denied.slices and denied.unfilled_quantity == 1 and "FOK" in denied.reason
    partial = sell.model_copy(update={"time_in_force": TimeInForce.GOOD_TIL_CANCELED})
    two = budget.preview(
        order=partial, event=event, remaining=D("1"), arrival_at=partial.submitted_at
    )
    assert 0 < two.slices[0].quantity < 1 and two.unfilled_quantity > 0
    budget.commit(fill_id="sell", order=partial, item=two.slices[0])
    assert budget.used_quote_notional <= 150 and budget.used_quote_notional > 149


def test_latency_queue_unknown_cancellation_and_bar_proxy_are_explicit() -> None:
    event = trade_quote()
    candidate = order(sequence=1, side=OrderSide.BUY)
    budget = EventLiquidityBudget(window(event), D("1"))
    assert (
        budget.preview(
            order=candidate,
            event=event,
            remaining=D("1"),
            arrival_at=event.event_time + timedelta(microseconds=1),
        ).reason
        == "ORDER_NOT_AT_VENUE"
    )
    assert (
        budget.preview(
            order=candidate,
            event=event,
            remaining=D("1"),
            arrival_at=candidate.submitted_at,
            cancel_effective_at=event.event_time - timedelta(microseconds=1),
        ).reason
        == "CANCEL_ALREADY_EFFECTIVE"
    )
    assert budget.preview(
        order=candidate,
        event=event,
        remaining=D("1"),
        arrival_at=candidate.submitted_at,
        cancel_effective_at=event.event_time,
    ).slices
    maker = order(sequence=3, side=OrderSide.SELL).model_copy(
        update={
            "order_type": OrderType.LIMIT,
            "limit_price": Price(amount=D("100"), base_asset_id=BTC, quote_asset_id=USDT),
        }
    )
    assert (
        budget.preview(
            order=maker, event=event, remaining=D("1"), arrival_at=maker.submitted_at
        ).reason
        == "MAKER_QUEUE_UNKNOWN"
    )
    assert not budget.preview(
        order=maker,
        event=event,
        remaining=D("1"),
        arrival_at=maker.submitted_at,
        queue_ahead=D("3"),
        queue_source_sha256=HASH,
    ).slices
    ready = EventLiquidityBudget(window(event), D("1")).preview(
        order=maker,
        event=event,
        remaining=D("1"),
        arrival_at=maker.submitted_at,
        queue_ahead=D("0.5"),
        queue_source_sha256=HASH,
    )
    assert (
        ready.slices
        and ready.slices[0].reference is not None
        and ready.slices[0].reference.reference_price_kind == "MAKER_LIMIT"
    )
    bar = bars()[1]
    assert (
        EventLiquidityBudget(window(bar), D("1"))
        .preview(order=candidate, event=bar, remaining=D("1"), arrival_at=candidate.submitted_at)
        .reason
        == "BAR_PROXY_ONLY"
    )


def deposit(ledger: LedgerEngine, asset: AssetId, amount: str) -> None:
    ledger.process_cashflow(
        CashflowEvent(
            event_id=ArtifactId("deposit-" + str(asset)),
            venue="SIM",
            cashflow_type=CashflowType.EXTERNAL_TRANSFER_IN,
            direction=CashflowDirection.INFLOW,
            amount=Money(amount=D(amount), asset_id=asset),
            event_time=accounting.NOW,
            recorded_at=accounting.NOW,
            idempotency_key=IdempotencyKey("deposit-" + str(asset)),
            reference="SYNTHETIC_TEST_CAPITAL",
        )
    )


def native_ledger() -> LedgerEngine:
    policy_data = accounting.accounting_policy(ROOT).model_dump()
    selected = AccountingPolicy.model_validate(
        {
            **policy_data,
            "policy_version": policy_data["policy_version"] + ":native-fees-v2",
            "spot_fee_policy": "SPOT_NATIVE_FEES_V2",
        }
    )
    ledger = LedgerEngine(policy=selected, effective_from=accounting.NOW)
    deposit(ledger, USDT, "1000")
    return ledger


def cash(ledger: LedgerEngine, asset: AssetId) -> Decimal:
    return sum(
        (
            balance.amount
            for balance in ledger.native_balances()
            if balance.asset_id == asset
            and ledger.chart.definition(balance.account_id).role is AccountRole.CASH
        ),
        D("0"),
    )


def test_native_base_fees_reduce_fifo_lots_partial_orders_and_rebuild_exactly() -> None:
    ledger = native_ledger()
    instrument = accounting.spot_instrument()
    for sequence in (1, 2):
        value = accounting.fill(
            instrument,
            sequence=sequence,
            side=OrderSide.BUY,
            quantity="0.5",
            price="100",
            fee="0.0005",
            fee_asset=BTC,
        )
        assert ledger.process_fill(value, instrument).inserted
        assert not ledger.process_fill(value, instrument).inserted
    assert cash(ledger, BTC) == D("0.999")
    assert sum(lot.remaining_quantity for lot in ledger.open_lots()) == D("0.999")
    before = ledger.state_digest()
    with pytest.raises(ValueError, match="BALANCE-INSUFFICIENT"):
        ledger.process_fill(
            accounting.fill(
                instrument,
                sequence=3,
                side=OrderSide.SELL,
                quantity="0.999",
                price="100",
                fee="0.001",
                fee_asset=BTC,
            ),
            instrument,
        )
    assert ledger.state_digest() == before
    ledger.process_fill(
        accounting.fill(
            instrument,
            sequence=4,
            side=OrderSide.SELL,
            quantity="0.999",
            price="100",
            fee="0.1",
            fee_asset=USDT,
        ),
        instrument,
    )
    assert not ledger.open_lots() and cash(ledger, BTC) == 0 and cash(ledger, USDT) == D("999.8")
    assert ledger.rebuild().state_digest() == ledger.state_digest()
    for record in ledger.records:
        assert_balanced_by_asset(record)


@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
@pytest.mark.parametrize("price", ["50", "300"])
def test_native_base_fee_fifo_pnl_is_posted_without_quote_cash(side: OrderSide, price: str) -> None:
    ledger = native_ledger()
    instrument = accounting.spot_instrument()
    for sequence, entry in ((1, "100"), (2, "200")):
        ledger.process_fill(
            accounting.fill(
                instrument,
                sequence=sequence,
                side=OrderSide.BUY,
                quantity="1",
                price=entry,
                fee="0",
            ),
            instrument,
        )
    result = ledger.process_fill(
        accounting.fill(
            instrument,
            sequence=3,
            side=side,
            quantity="1",
            price=price,
            fee="0.5",
            fee_asset=BTC,
        ),
        instrument,
    )
    mark = D(price)
    expected_realized = (
        D("0.5") * (mark - 100) if side is OrderSide.BUY else mark - 100 + D("0.5") * (mark - 200)
    )
    posted = sum(
        (
            balance.amount * (1 if role is AccountRole.TRADING_REALIZED_PNL else -1)
            for balance in ledger.native_balances()
            if (role := ledger.chart.definition(balance.account_id).role)
            in {AccountRole.TRADING_REALIZED_PNL, AccountRole.TRADING_LOSS}
        ),
        D("0"),
    )
    assert result.applied_fill.realized_pnl.amount == posted == expected_realized
    assert cash(ledger, USDT) == 700 + (-mark if side is OrderSide.BUY else mark)
    assert cash(ledger, BTC) == (D("2.5") if side is OrderSide.BUY else D("0.5"))
    assert sum(lot.remaining_quantity for lot in ledger.open_lots()) == cash(ledger, BTC)
    assert ledger.rebuild().state_digest() == ledger.state_digest()
    for record in ledger.records:
        assert_balanced_by_asset(record)


def test_native_base_rebate_has_real_quantity_and_third_asset_needs_balance_and_fx() -> None:
    ledger = native_ledger()
    instrument = accounting.spot_instrument()
    base = accounting.fill(
        instrument,
        sequence=1,
        side=OrderSide.BUY,
        quantity="1",
        price="100",
        fee="-0.001",
        fee_asset=BTC,
    )
    ledger.process_fill(base, instrument)
    assert cash(ledger, BTC) == D("1.001") and sum(
        lot.remaining_quantity for lot in ledger.open_lots()
    ) == D("1.001")
    third = accounting.fill(
        instrument,
        sequence=2,
        side=OrderSide.BUY,
        quantity="1",
        price="100",
        fee="0.1",
        fee_asset=BNB,
    )
    before = ledger.state_digest()
    with pytest.raises(ValueError, match="BALANCE-INSUFFICIENT"):
        ledger.process_fill(third, instrument)
    assert ledger.state_digest() == before
    deposit(ledger, BNB, "1")
    ledger.process_fill(third, instrument)
    assert cash(ledger, BNB) == D("0.9")
    valuation = ledger.valuation_snapshot(
        {
            instrument.instrument_id: ValuationQuote(
                instrument_id=instrument.instrument_id,
                as_of_time=third.event_time,
                available_time=third.available_time,
                mark=D("100"),
            )
        }
    )
    fx = {
        BTC: FxRate(
            asset_id=BTC,
            reporting_asset_id=USDT,
            rate=D("100"),
            as_of_time=third.event_time,
            policy_version="SYNTHETIC",
        )
    }
    with pytest.raises(ValueError):
        ledger.equity_snapshot(valuation=valuation, reporting_asset_id=USDT, fx_rates=fx)
    fx[BNB] = FxRate(
        asset_id=BNB,
        reporting_asset_id=USDT,
        rate=D("250"),
        as_of_time=third.event_time,
        policy_version="SYNTHETIC",
    )
    assert ledger.equity_snapshot(
        valuation=valuation, reporting_asset_id=USDT, fx_rates=fx
    ).equity == D("1225.1")
    assert ledger.rebuild().state_digest() == ledger.state_digest()


def frozen_module(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    frozen = ROOT / "artifacts/alpha_v5/20260908_research_churn_v3"
    manifest = json.loads((frozen / "audit_manifest.json").read_text(encoding="utf-8"))
    path = frozen / "implementation" / name
    assert sha256_file(path) == manifest["source_hashes"][name]
    module = ModuleType("b4_frozen_" + name.replace("/", "_").replace(".", "_"))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102 -- hash-verified project code, synthetic inputs only.
    return module


def test_legacy_cost_fills_transitions_and_ledger_keep_exact_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_cost = frozen_module("src/aegisquant/backtest/costs.py", monkeypatch)
    old_fills = frozen_module("src/aegisquant/backtest/fills.py", monkeypatch)
    old_transition = frozen_module("src/aegisquant/portfolio/transition_costs.py", monkeypatch)
    old_ledger = frozen_module("src/aegisquant/accounting/ledger.py", monkeypatch)
    candidate = order(sequence=1, side=OrderSide.BUY, quantity="2")
    for event in (bars()[1], trade_quote(), l2_book()):
        args: dict[str, Any] = dict(
            order=candidate, event=event, remaining=D("2"), participation_cap=D("0.4")
        )
        current = decide_fills(**args)
        assert current == old_fills.decide_fills(**args)
        for item in current:
            cost_args: dict[str, Any] = dict(
                order=candidate,
                fill_slice=item,
                schedule=policy().cost_schedules[0],
                base_asset_id=BTC,
                quote_asset_id=USDT,
            )
            assert execution_price_and_cost(**cost_args) == old_cost.execution_price_and_cost(
                **cost_args
            )
            assert "reference" not in item.model_dump()
    assert "evidence" not in policy().cost_schedules[0].model_dump()
    for notional in ("0", "1.123456789012345678901234567", "10000"):
        args = dict(
            available_time=NOW,
            natr=D("0.012345"),
            quote_volume=D("12345.678901"),
            order_notional=D(notional),
            exit_order_notional=D(notional) / 3,
        )
        assert estimate_spot_transition_costs(**args).model_dump(
            mode="json"
        ) == old_transition.estimate_spot_transition_costs(**args).model_dump(mode="json")
    current = accounting.engine(ROOT)
    old_policy = old_ledger.AccountingPolicy.model_validate(current.policy.model_dump())
    old = old_ledger.LedgerEngine(policy=old_policy, effective_from=accounting.NOW)
    instrument = accounting.spot_instrument()
    for sequence, side in ((1, OrderSide.BUY), (2, OrderSide.SELL)):
        value = accounting.fill(
            instrument, sequence=sequence, side=side, quantity="1", price="100", fee="0.1"
        )
        current.process_fill(value, instrument)
        old.process_fill(value, instrument)
    assert current.state_digest() == old.state_digest()
    assert "spot_fee_policy" not in current.policy.model_dump()


def observations(days: int = 20, per_day: int = 10) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for day in range(days):
        for index in range(per_day):
            time = NOW + timedelta(days=day, minutes=index)
            result.append(
                dict(
                    fill_id=f"fill-{day}-{index}",
                    order_id=f"order-{day}-{index}",
                    quantity="1",
                    order_quantity="1",
                    side="BUY",
                    decision_at=(time - timedelta(seconds=2)).isoformat(),
                    send_at=(time - timedelta(seconds=1)).isoformat(),
                    venue_receive_at=time.isoformat(),
                    ack_at=time.isoformat(),
                    fill_at=time.isoformat(),
                    receive_at=time.isoformat(),
                    cancel_request_at=None,
                    cancel_ack_at=None,
                    clock_error_ns=0,
                    source_sha256=HASH,
                    bucket="REGISTERED_BUCKET",
                    fee_asset="USDT",
                    fee_amount="0.01",
                    expected_fee_amount="0.01",
                    fee_quantum="0.0001",
                    residual_bps="0.5",
                    observed_adverse_bps="1",
                    predicted_q95_bps="2",
                    reference_price_kind="BBO",
                    reference_price="100",
                )
            )
    return result


@pytest.mark.parametrize("kind", ["duplicate", "overfill", "clock", "cancel", "reference"])
def test_execution_observation_bad_records_cannot_enter_calibration(kind: str) -> None:
    rows = observations(days=1, per_day=2)
    if kind == "duplicate":
        rows[1]["fill_id"] = rows[0]["fill_id"]
    elif kind == "overfill":
        rows[1]["order_id"] = rows[0]["order_id"]
    elif kind == "clock":
        rows[0]["send_at"] = (NOW + timedelta(days=1)).isoformat()
    elif kind == "cancel":
        rows[0]["cancel_ack_at"] = NOW.isoformat()
    else:
        rows[0]["reference_price_kind"] = "GUESSED_ORDERBOOK"
    with pytest.raises(ValueError):
        contract.validate_execution_observations(rows)


def test_fixed_split_rejects_orders_across_boundary_and_future_receipts() -> None:
    rows = observations(days=2, per_day=1)
    args = dict(
        calibration_start=(NOW - timedelta(days=1)).isoformat(),
        calibration_end=(NOW + timedelta(hours=12)).isoformat(),
        validation_start=(NOW + timedelta(hours=12)).isoformat(),
        validation_end=(NOW + timedelta(days=2)).isoformat(),
    )
    result = contract.split_execution_calibration(rows, **args)
    assert len(result["calibration"]) == len(result["validation"]) == 1
    bad = copy.deepcopy(rows)
    for row in bad:
        row["order_id"] = "same-partial-order"
        row["order_quantity"] = "2"
    with pytest.raises(ValueError, match="CROSSES-SPLIT"):
        contract.split_execution_calibration(bad, **args)
    bad = copy.deepcopy(rows)
    bad[0]["receive_at"] = (NOW + timedelta(days=3)).isoformat()
    with pytest.raises(ValueError, match="NOT-KNOWN"):
        contract.split_execution_calibration(bad, **args)


def test_residual_quality_preserves_missing_and_failing_buckets_without_model_fit() -> None:
    insufficient = contract.calibration_residual_buckets(observations(days=19))
    assert insufficient["buckets"]["REGISTERED_BUCKET"]["status"] == "INSUFFICIENT_SAMPLE"
    valid = observations()
    assert (
        contract.calibration_residual_buckets(valid)["buckets"]["REGISTERED_BUCKET"]["status"]
        == "SUPPLIED_RECORDS_PASS"
    )
    for row in valid:
        row["observed_adverse_bps"] = "3"
    failed = contract.calibration_residual_buckets(valid)["buckets"]["REGISTERED_BUCKET"]
    assert failed["status"] == "CALIBRATION_FAILED" and failed["q95_exceedance_ci95"] == [1, 1]


def test_shared_report_seals_missing_evidence_and_blocks_reuse(tmp_path: Path) -> None:
    root, stage = tmp_path / "synthetic-root", tmp_path / "synthetic-stage"
    root.mkdir()
    stage.mkdir()
    config = yaml.safe_load(
        (ROOT / "configs/research/alpha_v5_execution_contract.yaml").read_text(encoding="utf-8")
    )

    def save(name: str, data: str) -> Path:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
        return target

    for name in contract.FILES:
        save(name, "SYNTHETIC CODE RECEIPT\n")
    source_data = {
        "r5_manifest": r5_fixture(),
        "b3_manifest": {"synthetic": True},
        "b2_safety": {"strict_data_quality": "FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE"},
    }
    for name, binding in config["sources"].items():
        binding["sha256"] = sha256_file(save(binding["path"], json.dumps(source_data[name])))
    save(
        "configs/research/aegis_alpha_v5.yaml", yaml.safe_dump(source_data["r5_manifest"]["config"])
    )
    save(
        "src/aegisquant/bootstrap/live_lock.py",
        "LIVE_TRADING: bool = False\nORDER_SUBMISSION_ENABLED: bool = False\nLIVE_ADAPTERS: tuple = ()\n",
    )
    baseline = dict(
        root=str(root),
        head=evidence.BASE,
        branch="main",
        allowed_modifications=list(contract.FILES[:8]),
        files={
            path.relative_to(root).as_posix(): dict(
                sha256=sha256_file(path), bytes=path.stat().st_size
            )
            for path in root.rglob("*")
            if path.is_file()
        },
    )
    (stage / "baseline_workspace.json").write_text(json.dumps(baseline), encoding="utf-8")
    for name in contract.FILES[:8]:
        target = stage / "before" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / name).read_bytes())
    for name in ("workspace_before.patch", "version_graph.txt", "test_commands_and_results.txt"):
        (stage / name).write_text("SYNTHETIC RECEIPT\n", encoding="utf-8")
    hashes = {name: sha256_file(root / name) for name in contract.FILES}
    (stage / "validation_records.json").write_text(
        json.dumps(
            [
                dict(check=kind, command=["SYNTHETIC"], exit_code=0, source_sha256=hashes)
                for kind in ("ruff", "format", "pyright", "pytest")
            ]
        ),
        encoding="utf-8",
    )
    (stage / "pytest_results.xml").write_text(
        '<testsuite><testcase name="SYNTHETIC"/></testsuite>', encoding="utf-8"
    )
    contract.validate_config(config)
    output = evidence.run_zero_research_contract(
        root=root,
        config=config,
        stage=stage,
        git_state={"head": evidence.BASE, "branch": "main"},
        files=contract.FILES,
        build_documents=contract.build_documents,
    )
    assert evidence.load_evidence_manifest(output, "OUTPUT_MANIFEST.json")["status"] == "VERIFIED"
    freeze = json.loads((output / "calibration_freeze_manifest.json").read_text())
    assert freeze["actual_data_splits"] == freeze["model_fits"] == freeze["replay_scenarios"] == 0
    assert freeze["validation_period"] is None
    with pytest.raises(FileExistsError):
        evidence.run_zero_research_contract(
            root=root,
            config=config,
            stage=stage,
            git_state={"head": evidence.BASE, "branch": "main"},
            files=contract.FILES,
            build_documents=contract.build_documents,
        )


@pytest.mark.parametrize("kind", ["data", "fit", "capital", "threshold"])
def test_report_config_cannot_turn_into_empirical_run(kind: str) -> None:
    config = yaml.safe_load(
        (ROOT / "configs/research/alpha_v5_execution_contract.yaml").read_text(encoding="utf-8")
    )
    if kind == "data":
        config["execution_observations"] = "real-data.csv"
    elif kind == "fit":
        config["calibration_split"] = {}
    elif kind == "capital":
        config["future_scenarios"]["capital_multipliers"].append("100")
    else:
        config["calibration_acceptance"]["maximum_abs_median_residual_bps"] = "10"
    with pytest.raises(ValueError):
        contract.validate_config(config)
