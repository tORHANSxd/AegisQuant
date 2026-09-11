from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from aegisquant.data.hashing import canonical_sha256
from aegisquant.research.validation.evidence_contract import ZERO_BUDGETS, zero_budget_guard
from aegisquant.research.validation.saved_run_audit import (
    at,
    audit_saved_result,
    combine_segments,
    tag_saved_row,
    tail_inventory,
    validate_config,
)

D = Decimal
START = datetime(2020, 1, 1, tzinfo=UTC)


def iso(hours: int, *, before: bool = False) -> str:
    return (
        START + timedelta(hours=hours) - (timedelta(milliseconds=1) if before else timedelta(0))
    ).isoformat()


def fixture() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A two-fill synthetic example; no historical input or strategy execution."""
    trace: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    for index, (hour, qty, cash, price) in enumerate(
        ((4, 0, 1000, 100), (8, 1, 898, 112), (12, 1, 898, 114), (16, 0, 1016, 120))
    ):
        active = index in (0, 2)
        side = "BUY" if index == 0 else "SELL"
        key = f"synthetic-{index + 1}"
        time = iso(hour, before=True)
        reference = "100" if index == 0 else "120"
        row = {
            "time": time,
            "decision_time": time,
            "known_close": str(price),
            "cash": str(cash),
            "current_quantity": str(qty),
            "target_quantity": "1" if index < 2 else "0",
            "signed_planned_quantity": ("1" if index == 0 else "-1") if active else "0",
            "reason": "TREND_ENTRY_PASSED_ENABLED_GATES"
            if index == 0
            else "CONFIRMED_TREND_EXIT"
            if index == 2
            else "INSIDE_ECONOMIC_NO_TRADE_REGION",
            "order_id": key if active else None,
            "order_status": "FILLED" if active else "NO_ORDER",
            "rejection_reason": None,
            "actual_fill_notional": reference if active else "0",
            "realized_execution_cost": "2" if active else "0",
            "rebalance_permitted": index == 0,
            "last_regular_review": None if index == 0 else iso(4 if index < 3 else 12, before=True),
            "last_resize_time_before_decision": None
            if index == 0
            else iso(4 if index < 3 else 12, before=True),
            "resize_gate_reason": None,
        }
        trace.append(row)
        if not active:
            continue
        order = {
            "backtest_order_id": key,
            "client_order_id": key,
            "order_intent_id": key,
            "instrument_id": "SIM:SPOT:BTCUSDT",
            "side": side,
            "quantity": {"amount": "1", "asset_id": "BTC"},
            "decision_time": time,
            "submitted_at": time,
        }
        venue_id = "simorder:" + key
        orders.append(
            {
                "order": order,
                "venue_order_id": venue_id,
                "status": "FILLED",
                "arrival_time": time,
                "cumulative_filled_quantity": "1",
                "rejection_code": None,
            }
        )
        costs = {
            "asset_id": "USDT",
            "gross_notional": reference,
            "fee": "1",
            "spread": "1",
            "slippage": "0",
            "impact": "0",
            "funding": "0",
            "borrow_interest": "0",
            "settlement_fee": "0",
            "liquidation_penalty": "0",
        }
        fills.append(
            {
                "fill_id": "simfill:" + key,
                "backtest_order_id": key,
                "client_order_id": key,
                "order_intent_id": key,
                "instrument_id": "SIM:SPOT:BTCUSDT",
                "side": side,
                "venue_order_id": venue_id,
                "quantity": {"amount": "1", "asset_id": "BTC"},
                "reference_price": {"amount": reference},
                "execution_price": {"amount": "101" if index == 0 else "119"},
                "fee": {"amount": "1", "asset_id": "USDT"},
                "cost_breakdown": costs,
                "source_event_id": "synthetic-bar",
                "event_time": iso(hour),
                "available_time": iso(hour + 4, before=True),
                "ingest_time": iso(hour + 4, before=True),
            }
        )
    records: list[dict[str, Any]] = []
    lot = {
        "position_lot_id": canonical_sha256({"fill_id": fills[0]["fill_id"], "ordinal": 0}),
        "account_id": "position_cost:SIM:SIM:SPOT:BTCUSDT",
        "instrument_id": "SIM:SPOT:BTCUSDT",
        "side": "LONG",
        "quantity_unit": "BASE_ASSET",
        "quantity_asset_id": "BTC",
        "opened_quantity": "1",
        "remaining_quantity": "1",
        "entry_price": "101",
        "contract_form": "SPOT",
        "contract_multiplier": "1",
        "settlement_asset_id": "USDT",
        "opening_fee": {"amount": "1", "asset_id": "USDT"},
        "source_fill_id": fills[0]["fill_id"],
        "opened_at": fills[0]["event_time"],
        "closed_at": None,
    }

    def posting(account: str, asset: str, value: str, side: str) -> dict[str, Any]:
        return {"account_id": account, "side": side, "amount": {"asset_id": asset, "amount": value}}

    def record(
        index: int,
        entries: list[dict[str, Any]],
        fill: dict[str, Any] | None,
        changes: list[dict[str, Any]],
    ) -> None:
        identity = str(index + 1) * 64
        payload = {
            "journal_entry": {
                "journal_entry_id": identity,
                "event_time": fill["event_time"] if fill else iso(0),
                "recorded_at": fill["ingest_time"] if fill else iso(0),
                "postings": entries,
                "reconciliation_adjustment": False,
                "supersedes_entry_id": None,
            },
            "policy_version": "accounting-v1",
            "chart_version": "coa-v1",
            "entry_template_id": "spot-fill" if fill else "external-transfer",
            "template_version": "entry-templates-v1",
            "source_fill_id": fill["fill_id"] if fill else None,
            "source_order_intent_id": fill["order_intent_id"] if fill else None,
            "idempotency_key": "simfill:" + fill["fill_id"] if fill else identity,
            "command_hash": identity,
            "previous_hash": records[-1]["event_hash"] if records else "0" * 64,
            "lot_changes": changes,
        }
        records.append({**payload, "event_hash": canonical_sha256(payload)})

    record(
        0,
        [
            posting("cash:SIM:USDT", "USDT", "1000", "DEBIT"),
            posting("owner:SIM:USDT", "USDT", "1000", "CREDIT"),
        ],
        None,
        [],
    )
    record(
        1,
        [
            posting("cash:SIM:BTC", "BTC", "1", "DEBIT"),
            posting("clearing:SIM:BTC", "BTC", "1", "CREDIT"),
            posting("position_cost:SIM:BTC", "USDT", "101", "DEBIT"),
            posting("cash:SIM:USDT", "USDT", "101", "CREDIT"),
            posting("fee:SIM:USDT", "USDT", "1", "DEBIT"),
            posting("cash:SIM:USDT", "USDT", "1", "CREDIT"),
        ],
        fills[0],
        [
            {
                "action": "OPEN",
                "lot_before": None,
                "lot_after": lot,
                "affected_quantity": "1",
                "realized_pnl": {"amount": "0", "asset_id": "USDT"},
            }
        ],
    )
    record(
        2,
        [
            posting("cash:SIM:BTC", "BTC", "1", "CREDIT"),
            posting("clearing:SIM:BTC", "BTC", "1", "DEBIT"),
            posting("cash:SIM:USDT", "USDT", "119", "DEBIT"),
            posting("position_cost:SIM:BTC", "USDT", "101", "CREDIT"),
            posting("realized:SIM:USDT", "USDT", "18", "CREDIT"),
            posting("fee:SIM:USDT", "USDT", "1", "DEBIT"),
            posting("cash:SIM:USDT", "USDT", "1", "CREDIT"),
        ],
        fills[1],
        [
            {
                "action": "CLOSE",
                "lot_before": lot,
                "lot_after": None,
                "affected_quantity": "1",
                "realized_pnl": {"amount": "18", "asset_id": "USDT"},
            }
        ],
    )
    raw_points: list[dict[str, Any]] = []
    for time, cash, position in (
        (iso(0), "1000", "0"),
        (iso(4, before=True), "1000", "0"),
        (iso(8, before=True), "898", "112"),
        (iso(12, before=True), "898", "114"),
        (iso(16, before=True), "1016", "0"),
        (iso(16), "1016", "0"),
    ):
        raw_points.append(
            {
                "time": time,
                "cash": cash,
                "position_value": position,
                "realized_pnl": "0",
                "unrealized_pnl": "0",
                "equity": str(D(cash) + D(position)),
                "reporting_asset_id": "USDT",
            }
        )
    return {
        "spec": {
            "run_id": "synthetic",
            "start_time": iso(0),
            "end_time": iso(16),
            "initial_cash": {"amount": "1000", "asset_id": "USDT"},
            "live_trading_locked": True,
            "accounting_policy_version": "accounting-v1",
            "cost_policy_version": "cat-proxy-v2",
        },
        "orders": orders,
        "fills": fills,
        "ledger_records": records,
        "positions": [{"quantity": "0"}],
        "closed_trades": [{}],
        "equity_curve": raw_points,
    }, trace


def run_audit(
    result: dict[str, Any], trace: list[dict[str, Any]], hours: int = 48
) -> dict[str, Any]:
    return audit_saved_result(result, trace, symbol="BTCUSDT", review_interval_hours=hours)


def test_original_records_join_and_native_cash_close_without_running_a_strategy() -> None:
    result, trace = fixture()
    audited = run_audit(result, trace)
    summary = audited["summary"]
    assert summary["status"] == "VERIFIED_STORED_SIMULATION", summary["checks"]
    assert (
        summary["orders"],
        summary["fills"],
        summary["ledger_records"],
        summary["raw_mtm_points"],
    ) == (2, 2, 3, 6)
    assert summary["final_cash"] == "1016" and summary["paid_cost"] == "4"
    assert len(audited["joins"]) == 2 and all(r["ledger_event_hash"] for r in audited["joins"])
    assert sum(r["rows"] for r in audited["gate_funnel"]) == 4
    assert audited["curve"][1]["equity"] == D(1000)  # 04:00 cannot use the 07:59 mark.
    assert audited["curve"][2]["equity"] == D(1010)


@pytest.mark.parametrize(
    "problem,check",
    [
        ("duplicate_fill", "unique_fill_id"),
        ("unknown_order", "fill_order_exists"),
        ("missing_trace", "complete_trace_order_join"),
        ("order_overfill", "order_not_overfilled"),
        ("cumulative", "order_cumulative_fill"),
        ("future_fill", "fill_causal_clocks"),
        ("fee_asset", "fill_units_and_ids"),
        ("fee_amount", "fee_money"),
        ("ledger_hash", "ledger_hash_chain"),
        ("unbalanced", "double_entry_by_asset"),
        ("lot_chain", "lot_change_continuity"),
        ("extra_cash", "ledger_cash_matches_every_mtm"),
        ("wrong_price", "every_mtm_native_position_value"),
        ("wrong_clock", "review_state_transition"),
    ],
)
def test_inconsistent_saved_evidence_is_not_declared_verified(problem: str, check: str) -> None:
    result, trace = fixture()
    if problem == "duplicate_fill":
        result["fills"].append(deepcopy(result["fills"][0]))
    elif problem == "unknown_order":
        result["fills"][0]["backtest_order_id"] = "missing"
    elif problem == "missing_trace":
        trace[0]["order_id"] = None
    elif problem == "order_overfill":
        result["orders"][0]["order"]["quantity"]["amount"] = "0.5"
    elif problem == "cumulative":
        result["orders"][0]["cumulative_filled_quantity"] = "0"
    elif problem == "future_fill":
        result["fills"][0]["available_time"] = iso(0)
    elif problem == "fee_asset":
        result["fills"][0]["fee"]["asset_id"] = "BNB"
    elif problem == "fee_amount":
        result["fills"][0]["fee"]["amount"] = "2"
    elif problem == "ledger_hash":
        result["ledger_records"][1]["previous_hash"] = "0" * 64
    elif problem == "unbalanced":
        result["ledger_records"][1]["journal_entry"]["postings"][0]["amount"]["amount"] = "2"
    elif problem == "lot_chain":
        result["ledger_records"][2]["lot_changes"][0]["lot_before"] = {
            **result["ledger_records"][2]["lot_changes"][0]["lot_before"],
            "remaining_quantity": "0.5",
        }
    elif problem == "extra_cash":
        result["equity_curve"][2]["cash"] = "900"
        result["equity_curve"][2]["equity"] = "1012"
    elif problem == "wrong_price":
        trace[1]["known_close"] = "1000"
    elif problem == "wrong_clock":
        trace[1]["last_regular_review"] = iso(100)
    audited = run_audit(result, trace)["summary"]
    assert audited["status"] == "INCONSISTENT_STORED_SIMULATION"
    assert audited["checks"][check]["failed"] > 0


@pytest.mark.parametrize(
    "field,value,check",
    [
        ("opened_quantity", "0", "lot_schema"),
        ("source_fill_id", "unknown", "lot_opening_fill_exists"),
        ("quantity_asset_id", "ETH", "lot_opening_fill_identity"),
        ("entry_price", "999", "lot_entry_price"),
        ("opened_quantity", "2", "lot_opened_quantity"),
    ],
)
def test_rehashed_illegal_lot_cannot_hide_behind_a_valid_ledger_chain(
    field: str, value: str, check: str
) -> None:
    result, trace = fixture()
    result["ledger_records"][1]["lot_changes"][0]["lot_after"][field] = value
    rehash(result)
    audited = run_audit(result, trace)["summary"]
    assert audited["checks"]["ledger_hash_chain"]["failed"] == 0
    assert audited["checks"][check]["failed"] > 0
    assert audited["status"] == "INCONSISTENT_STORED_SIMULATION"


def rehash(result: dict[str, Any]) -> None:
    previous = "0" * 64
    for record in result["ledger_records"]:
        record["previous_hash"] = previous
        record["event_hash"] = canonical_sha256(
            {key: value for key, value in record.items() if key != "event_hash"}
        )
        previous = record["event_hash"]


def test_rehashed_wrong_fill_idempotency_is_not_a_valid_link() -> None:
    result, trace = fixture()
    result["ledger_records"][1]["idempotency_key"] = "simfill:wrong-fill"
    rehash(result)
    checks = run_audit(result, trace)["summary"]["checks"]
    assert checks["ledger_hash_chain"]["failed"] == 0
    assert checks["ledger_fill_clocks_and_intent"]["failed"] == 1


def test_due_review_without_order_and_cost_veto_are_auditable() -> None:
    result, trace = fixture()
    for row in trace:
        row["rebalance_permitted"] = True
    trace[1]["last_regular_review"] = trace[1]["time"]
    trace[2]["last_regular_review"] = trace[1]["time"]
    trace[1].update(
        resize_gate_reason="REBALANCE_COST_EXCEEDS_RISK_BENEFIT",
        rebalance_risk_benefit="0.01",
        rebalance_cost_equity_fraction="0.02",
    )
    first = run_audit(result, trace, hours=4)["summary"]
    assert first["status"] == "VERIFIED_STORED_SIMULATION", first["checks"]
    assert first["due_reviews_without_order"] == 1
    trace[1]["resize_gate_reason"] = "REBALANCE_RISK_BENEFIT_COVERS_COST"
    assert (
        run_audit(result, trace, hours=4)["summary"]["checks"]["recorded_cost_benefit_veto"][
            "failed"
        ]
        == 1
    )


def curve(values: Sequence[Decimal]) -> list[dict[str, Any]]:
    return [
        {
            "time": START + timedelta(hours=4 * i),
            "source_time": START + timedelta(hours=4 * i),
            "equity": value,
            "cash": value,
            "position_value": D(0),
            "quantity": D(0),
            "mark": D(100),
        }
        for i, value in enumerate(values)
    ]


def test_all_tail_cutoff_ties_and_all_assets_are_preserved() -> None:
    values = [D(100)] * 38 + [D(90), D(81), D("72.9")]
    a, b = curve(values), curve([value * 2 for value in values])
    result = tail_inventory({"B": b, "A": a})
    assert result["minimum_selected"] == 2 and result["selected"] == 3
    assert all(
        len(row["assets"]) == 2 and row["sum_residual"] == "0.0" for row in result["rows"][-1:]
    )
    assert result == tail_inventory({"A": a, "B": b})
    all_flat = tail_inventory({"A": curve([D(100)] * 41)})
    assert all_flat["selected"] == 40


def test_tail_missing_asset_calendar_is_rejected_and_boundary_cash_cannot_reset() -> None:
    series = curve([D(100), D(101), D(102)])
    with pytest.raises(ValueError, match="same full calendar"):
        tail_inventory({"A": series, "B": series[1:]})
    assert combine_segments([series[:2], series[1:]]) == series
    wrong = deepcopy(series[1:])
    wrong[0]["cash"] += 1
    with pytest.raises(ValueError, match="inherited cash"):
        combine_segments([series[:2], wrong])


def test_naive_clocks_are_rejected() -> None:
    with pytest.raises(ValueError, match="explicit UTC"):
        at("2020-01-01T00:00:00")


def test_tail_common_gap_and_zero_nav_are_explicitly_rejected() -> None:
    with pytest.raises(ValueError, match="complete four-hour"):
        tail_inventory({"A": curve([D(100)] * 3)[::2]})
    with pytest.raises(ValueError, match="positive portfolio NAV"):
        tail_inventory({"A": curve([D(0), D(100)])})


def test_cost_scenario_cannot_be_replaced_by_a_paid_amount_in_assembled_rows() -> None:
    result, trace = fixture()
    audit = run_audit(result, trace)
    tags = {"arm": "G1", "symbol": "BTCUSDT", "cost": "1.5", "segment": "continuous"}
    summary = tag_saved_row(tags, audit["summary"])
    joins = [tag_saved_row(tags, row) for row in audit["joins"]]
    assert summary["cost"] == "1.5" and summary["paid_cost"] == "4"
    assert all(row["cost"] == "1.5" and row["paid_cost"] == "2" for row in joins)
    with pytest.raises(ValueError, match="TAG-COLLISION"):
        tag_saved_row(tags, {"cost": "4"})


def test_saved_audit_operates_inside_zero_research_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aegisquant.accounting.ledger import LedgerEngine
    from aegisquant.backtest.engine import EventBacktestEngine

    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("an audit cannot execute an engine or ledger command")

    monkeypatch.setattr(EventBacktestEngine, "run", forbidden)
    monkeypatch.setattr(LedgerEngine, "process_fill", forbidden)
    output = tmp_path / "new-output"
    output.mkdir()
    counters: dict[str, int] = dict.fromkeys(ZERO_BUDGETS, 0)
    result, trace = fixture()
    with zero_budget_guard(output, tmp_path, counters):
        assert run_audit(result, trace)["summary"]["status"] == "VERIFIED_STORED_SIMULATION"
    assert all(value == 0 for value in counters.values())


def test_saved_scope_cannot_turn_into_a_new_strategy_trial() -> None:
    config = yaml.safe_load(
        Path("configs/research/alpha_v5_saved_run_audit.yaml").read_text(encoding="utf-8")
    )
    validate_config(config)
    config["saved_scope"]["new_strategy_runs"] = 1
    with pytest.raises(ValueError, match="SCOPE"):
        validate_config(config)
