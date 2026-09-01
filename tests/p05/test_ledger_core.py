"""Golden and unit contracts for P05 double-entry accounting."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from aegisquant.accounting.ledger import calculate_contract_pnl
from aegisquant.accounting.models import (
    CashflowDirection,
    CashflowEvent,
    CashflowType,
    LedgerRecord,
    SettlementEvent,
)
from aegisquant.domain.accounting import LotSide, PostingSide
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import ArtifactId, AssetId, IdempotencyKey
from aegisquant.domain.values import Money
from tests.p05.helpers import (
    BTC,
    NOW,
    USDT,
    accounting_policy,
    engine,
    fill,
    inverse_instrument,
    linear_instrument,
    spot_instrument,
)


def assert_balanced_by_asset(record: LedgerRecord) -> None:
    journal = record.journal_entry
    totals: dict[str, Decimal] = {}
    for posting in journal.postings:
        sign = Decimal("1") if posting.side is PostingSide.DEBIT else Decimal("-1")
        key = str(posting.amount.asset_id)
        totals[key] = totals.get(key, Decimal("0")) + sign * posting.amount.amount
    assert set(totals.values()) == {Decimal("0")}


def test_policy_chart_and_entry_templates_are_versioned(project_root: Path) -> None:
    policy = accounting_policy(project_root)
    ledger = engine(project_root)
    assert policy.lot_policy == "FIFO"
    assert policy.valuation_priority == ("MARK", "MID", "LAST", "INDEX")
    assert policy.mutation_score_threshold == Decimal("0.90")
    assert ledger.chart.snapshot().version == "coa-v1"
    assert {
        "SPOT_FILL",
        "DERIVATIVE_FILL",
        "CONTRACT_SETTLEMENT",
        "FUNDING_INCOME",
        "FUNDING_EXPENSE",
        "BORROW",
        "REPAY",
        "BORROW_INTEREST",
        "EXTERNAL_TRANSFER",
        "TRANSFER_FEE",
        "RECONCILIATION_ADJUSTMENT",
    } <= set(ledger.templates)
    assert {item.version for item in ledger.templates.values()} == {"entry-templates-v1"}


def test_spot_fifo_matches_committed_golden_fixture(project_root: Path) -> None:
    spec = spot_instrument()
    ledger = engine(project_root)
    ledger.process_fill(fill(spec, sequence=1, side=OrderSide.BUY, quantity="1", price="100"), spec)
    ledger.process_fill(fill(spec, sequence=2, side=OrderSide.BUY, quantity="2", price="110"), spec)
    outcome = ledger.process_fill(
        fill(spec, sequence=3, side=OrderSide.SELL, quantity="1.5", price="120"), spec
    )
    golden = cast(
        dict[str, object],
        json.loads(
            (project_root / "tests/fixtures/p05/golden_spot_fifo.json").read_text(encoding="utf-8")
        ),
    )
    projection = {
        "entry_count": len(ledger.records),
        "realized_pnl": str(outcome.applied_fill.realized_pnl.amount),
        "realized_asset": str(outcome.applied_fill.realized_pnl.asset_id),
        "open_lots": [
            {
                "entry_price": str(lot.entry_price),
                "remaining_quantity": str(lot.remaining_quantity),
                "side": lot.side.value,
            }
            for lot in ledger.open_lots()
        ],
    }
    assert projection == golden
    for record in ledger.records:
        assert_balanced_by_asset(record)


def test_spot_oversell_fails_before_any_state_change(project_root: Path) -> None:
    spec = spot_instrument()
    ledger = engine(project_root)
    ledger.process_fill(fill(spec, sequence=1, side=OrderSide.BUY, quantity="1", price="100"), spec)
    before = ledger.state_digest()
    with pytest.raises(ValueError, match="AQ-LEDGER-SPOT-SHORT"):
        ledger.process_fill(
            fill(spec, sequence=2, side=OrderSide.SELL, quantity="2", price="110"), spec
        )
    assert ledger.state_digest() == before


def test_linear_perpetual_reduces_reverses_and_keeps_fifo(project_root: Path) -> None:
    spec = linear_instrument()
    ledger = engine(project_root)
    ledger.process_fill(fill(spec, sequence=1, side=OrderSide.BUY, quantity="2", price="100"), spec)
    reduced = ledger.process_fill(
        fill(spec, sequence=2, side=OrderSide.SELL, quantity="1", price="110"), spec
    )
    reversed_fill = ledger.process_fill(
        fill(spec, sequence=3, side=OrderSide.SELL, quantity="2", price="90"), spec
    )
    assert reduced.applied_fill.realized_pnl.amount == Decimal("10")
    assert reversed_fill.applied_fill.realized_pnl.amount == Decimal("-10")
    lots = ledger.open_lots(spec.instrument_id)
    assert len(lots) == 1
    assert lots[0].side is LotSide.SHORT
    assert lots[0].remaining_quantity == Decimal("1")
    assert lots[0].entry_price == Decimal("90")
    assert ledger.rebuild().state_digest() == ledger.state_digest()


def test_instrument_contract_cannot_drift_within_one_ledger(project_root: Path) -> None:
    spec = linear_instrument()
    ledger = engine(project_root)
    ledger.process_fill(fill(spec, sequence=1, side=OrderSide.BUY, quantity="1", price="100"), spec)
    conflicting = spec.model_copy(update={"contract_multiplier": Decimal("2")})
    with pytest.raises(ValueError, match="INSTRUMENT-CONTRACT-CONFLICT"):
        ledger.process_fill(
            fill(
                conflicting,
                sequence=2,
                side=OrderSide.BUY,
                quantity="1",
                price="100",
            ),
            conflicting,
        )


def test_inverse_contract_formula_is_exact_and_native_settled() -> None:
    spec = inverse_instrument()
    result = calculate_contract_pnl(
        side=LotSide.LONG,
        quantity=Decimal("100"),
        entry_price=Decimal("10000"),
        exit_price=Decimal("11000"),
        instrument=spec,
    )
    expected = Decimal("100") * (Decimal("1") / Decimal("10000") - Decimal("1") / Decimal("11000"))
    assert result.amount == expected
    assert result.asset_id == BTC

    short = calculate_contract_pnl(
        side=LotSide.SHORT,
        quantity=Decimal("100"),
        entry_price=Decimal("11000"),
        exit_price=Decimal("10000"),
        instrument=spec,
    )
    assert short.amount > 0


def test_dated_future_settlement_closes_all_lots_and_replays(project_root: Path) -> None:
    spec = linear_instrument(future=True)
    ledger = engine(project_root)
    ledger.process_fill(fill(spec, sequence=1, side=OrderSide.BUY, quantity="3", price="100"), spec)
    event = SettlementEvent(
        event_id=ArtifactId("settlement-1"),
        instrument=spec,
        settlement_price=Decimal("120"),
        event_time=NOW + timedelta(hours=1),
        available_time=NOW + timedelta(hours=1, milliseconds=1),
        recorded_at=NOW + timedelta(hours=1, milliseconds=2),
        idempotency_key=IdempotencyKey("settlement-key-1"),
        reference="official dated future settlement",
    )
    outcome = ledger.process_settlement(event)
    replay = ledger.process_settlement(event)
    assert outcome.inserted is True
    assert replay.inserted is False
    assert not ledger.open_lots(spec.instrument_id)
    assert sum(change.realized_pnl.amount for change in outcome.record.lot_changes) == Decimal("60")
    assert ledger.rebuild().state_digest() == ledger.state_digest()


def cashflow(
    *,
    sequence: int,
    cashflow_type: CashflowType,
    direction: CashflowDirection,
    amount: str,
    supersedes: str | None = None,
) -> CashflowEvent:
    adjustment = cashflow_type is CashflowType.RECONCILIATION_ADJUSTMENT
    return CashflowEvent(
        event_id=ArtifactId(f"cashflow-{sequence}"),
        venue="SIM",
        cashflow_type=cashflow_type,
        direction=direction,
        amount=Money(amount=Decimal(amount), asset_id=USDT),
        event_time=NOW + timedelta(minutes=sequence),
        recorded_at=NOW + timedelta(minutes=sequence, milliseconds=1),
        idempotency_key=IdempotencyKey(f"cashflow-key-{sequence}"),
        reference=f"cashflow fixture {sequence}",
        supersedes_entry_id=supersedes if adjustment else None,
        approval_reference="approval-1" if adjustment else None,
        evidence=("venue-statement-1",) if adjustment else (),
    )


def test_cashflows_borrow_and_authoritative_pnl_decomposition(project_root: Path) -> None:
    ledger = engine(project_root)
    transfer = ledger.process_cashflow(
        cashflow(
            sequence=1,
            cashflow_type=CashflowType.EXTERNAL_TRANSFER_IN,
            direction=CashflowDirection.INFLOW,
            amount="1000",
        )
    )
    ledger.process_cashflow(
        cashflow(
            sequence=2,
            cashflow_type=CashflowType.FUNDING,
            direction=CashflowDirection.INFLOW,
            amount="10",
        )
    )
    ledger.process_cashflow(
        cashflow(
            sequence=3,
            cashflow_type=CashflowType.BORROW_INTEREST,
            direction=CashflowDirection.OUTFLOW,
            amount="2",
        )
    )
    ledger.process_cashflow(
        cashflow(
            sequence=4,
            cashflow_type=CashflowType.TRANSFER_FEE,
            direction=CashflowDirection.OUTFLOW,
            amount="1",
        )
    )
    ledger.process_cashflow(
        cashflow(
            sequence=5,
            cashflow_type=CashflowType.RECONCILIATION_ADJUSTMENT,
            direction=CashflowDirection.INFLOW,
            amount="3",
            supersedes=str(transfer.record.journal_entry.journal_entry_id),
        )
    )
    ledger.process_cashflow(
        cashflow(
            sequence=6,
            cashflow_type=CashflowType.BORROW,
            direction=CashflowDirection.INFLOW,
            amount="100",
        )
    )
    breakdown = ledger.pnl_breakdown(
        starting_equity=Decimal("0"),
        ending_equity=Decimal("1010"),
        starting_unrealized=Decimal("0"),
        ending_unrealized=Decimal("0"),
        reporting_asset_id=USDT,
        fx_rates={},
    )
    assert breakdown.net_external_transfers == Decimal("1000")
    assert breakdown.funding_income_expense == Decimal("10")
    assert breakdown.borrow_interest == Decimal("2")
    assert breakdown.transfer_fees == Decimal("1")
    assert breakdown.reconciliation_adjustments == Decimal("3")
    assert ledger.process_cashflow(ledger.commands[0]).inserted is False  # type: ignore[arg-type]


def test_float_cannot_enter_authoritative_accounting_models() -> None:
    with pytest.raises((TypeError, ValidationError)):
        Money(amount=1.0, asset_id=AssetId("USDT"))  # type: ignore[arg-type]
