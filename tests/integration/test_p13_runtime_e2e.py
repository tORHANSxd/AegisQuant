"""P13 end-to-end Paper recovery, projection, and Shadow comparison flow."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.runtime.comparison import compare_mode_semantics
from aegisquant.runtime.models import RuntimeMode
from aegisquant.runtime.paper import PaperEngine
from aegisquant.runtime.reconciliation import (
    PaperRuntimeSnapshot,
    ReconciliationStatus,
    reconcile_paper_day,
)
from aegisquant.runtime.runner import run_all_modes
from tests.p12_helpers import NOW, USDT, command
from tests.p13_helpers import bundle, market, paper_policy


def test_runtime_chain_recovers_without_duplicate_economic_facts() -> None:
    results = run_all_modes(bundle=bundle(), market=market(), paper_policy=paper_policy())
    comparison = compare_mode_semantics(tuple(item.trace for item in results))
    assert comparison.semantic_identity_equal is True
    engine = PaperEngine(mode=RuntimeMode.PAPER, policy=paper_policy())
    engine.submit(command())
    engine.process(market())
    restored = PaperEngine.restore(engine.checkpoint(), policy=paper_policy())
    restored.process(market())
    assert restored.economic_order_count == 1
    assert len(restored.fills) == 1
    fill = restored.fills[0]
    notional = fill.quantity.amount * fill.fill_price.amount
    snapshot_payload = {
        "order_ids": [str(item.command.command.client_order_id) for item in restored.orders],
        "fill_ids": [item.fill_id for item in restored.fills],
        "notional": str(notional),
        "fees": str(fill.fee.amount),
    }
    snapshot = PaperRuntimeSnapshot(
        snapshot_id="p13-daily-clear",
        business_date="2026-09-01",
        captured_at=NOW,
        quote_asset_id=USDT,
        order_ids=tuple(snapshot_payload["order_ids"]),
        fill_ids=tuple(snapshot_payload["fill_ids"]),
        ledger_fill_ids=tuple(snapshot_payload["fill_ids"]),
        read_model_fill_ids=tuple(snapshot_payload["fill_ids"]),
        expected_notional=notional,
        ledger_notional=notional,
        expected_fees=fill.fee.amount,
        ledger_fees=fill.fee.amount,
        source_sha256=canonical_sha256(snapshot_payload),
    )
    reconciled = reconcile_paper_day(snapshot)
    assert reconciled.status is ReconciliationStatus.CLEAR
    assert reconciled.new_risk_allowed is True
    assert reconciled.authoritative_state_unchanged is True


def test_daily_reconciliation_difference_halts_without_repair() -> None:
    snapshot = PaperRuntimeSnapshot(
        snapshot_id="p13-daily-difference",
        business_date="2026-09-01",
        captured_at=NOW,
        quote_asset_id=USDT,
        order_ids=("order-1",),
        fill_ids=("fill-1",),
        ledger_fill_ids=(),
        read_model_fill_ids=("fill-1",),
        expected_notional=Decimal("100"),
        ledger_notional=Decimal("0"),
        expected_fees=Decimal("1"),
        ledger_fees=Decimal("0"),
        source_sha256=canonical_sha256({"case": "difference"}),
    )
    reconciled = reconcile_paper_day(snapshot)
    assert reconciled.status is ReconciliationStatus.HALTED
    assert reconciled.new_risk_allowed is False
    assert reconciled.missing_ledger_fill_ids == ("fill-1",)
    assert reconciled.authoritative_state_unchanged is True
