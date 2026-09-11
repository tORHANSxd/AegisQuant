"""Read-only joins and arithmetic over saved simulations; never execute a strategy."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import polars as pl

from aegisquant.accounting.models import LotChange
from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import EquityPoint
from aegisquant.data.hashing import canonical_sha256
from aegisquant.research.validation.evidence_contract import checked_path, decimal, require
from scripts.summarize_alpha_r4 import execution_reason

FILES = (
    "src/aegisquant/research/validation/saved_run_audit.py",
    "scripts/audit_alpha_v5_saved_runs.py",
    "configs/research/alpha_v5_saved_run_audit.yaml",
    "tests/alpha_v5/test_saved_run_audit.py",
    "docs/research/alpha_v5_saved_run_audit.md",
)
R5 = "artifacts/alpha_v5/20260908_research_churn_v3"
R4 = "artifacts/alpha_r4/20260908_v1"
SYMBOLS = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
ZERO = Decimal(0)
MONEY_TOLERANCE = Decimal("1e-18")
COST_FIELDS = (
    "fee",
    "spread",
    "slippage",
    "impact",
    "funding",
    "borrow_interest",
    "settlement_fee",
    "liquidation_penalty",
)


def at(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("saved evidence clocks must be explicit UTC")
    return result.astimezone(UTC)


def amount(value: Any) -> Decimal:
    return decimal(value)


@dataclass
class AuditChecks:
    counts: dict[str, dict[str, Any]] = field(default_factory=lambda: dict[str, dict[str, Any]]())

    def check(self, name: str, passed: bool, identity: str) -> None:
        row = self.counts.setdefault(name, {"checked": 0, "failed": 0, "examples": []})
        row["checked"] += 1
        if not passed:
            row["failed"] += 1
            if len(row["examples"]) < 5:
                row["examples"].append(identity)

    def equal(self, name: str, left: Decimal, right: Decimal, identity: str) -> None:
        self.check(name, abs(left - right) <= MONEY_TOLERANCE, identity)
        row = self.counts[name]
        row["maximum_absolute_residual"] = str(
            max(amount(row.get("maximum_absolute_residual", "0")), abs(left - right))
        )

    @property
    def passed(self) -> bool:
        return bool(self.counts) and all(row["failed"] == 0 for row in self.counts.values())


def _unique(rows: Sequence[dict[str, Any]], key: str, checks: AuditChecks) -> dict[str, Any]:
    values = {row[key]: row for row in rows}
    checks.check("unique_" + key, len(values) == len(rows), key)
    return values


def audit_saved_result(
    result: dict[str, Any],
    trace: list[dict[str, Any]],
    *,
    symbol: str,
    review_interval_hours: int | None,
    cost_benefit_lambda: Decimal = Decimal(1),
) -> dict[str, Any]:
    """Verify stored links, postings and marks. No engine or ledger commands are invoked."""
    checks = AuditChecks()
    spec = result["spec"]
    run_id = str(spec["run_id"])
    base, quote = symbol.removesuffix("USDT"), "USDT"
    start, end = at(spec["start_time"]), at(spec["end_time"])
    checks.check(
        "frozen_simulation_identity",
        spec["live_trading_locked"] is True
        and spec["accounting_policy_version"] == "accounting-v1"
        and spec["cost_policy_version"] == "cat-proxy-v2",
        run_id,
    )
    orders = {row["order"]["backtest_order_id"]: row for row in result["orders"]}
    checks.check("unique_orders", len(orders) == len(result["orders"]), run_id)
    fills = _unique(result["fills"], "fill_id", checks)
    by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trace_orders = {row["order_id"]: row for row in trace if row.get("order_id")}
    checks.check(
        "unique_trace_orders",
        len(trace_orders) == sum(bool(r.get("order_id")) for r in trace),
        run_id,
    )
    checks.check("complete_trace_order_join", set(trace_orders) == set(orders), run_id)
    checks.check("unique_trace_clock", len({at(r["time"]) for r in trace}) == len(trace), run_id)
    checks.check(
        "trace_clock_order",
        [at(r["time"]) for r in trace] == sorted(at(r["time"]) for r in trace),
        run_id,
    )
    checks.check("trace_in_period", all(start <= at(r["time"]) <= end for r in trace), run_id)
    total_cost = ZERO
    joined: list[dict[str, Any]] = []
    fill_position = ZERO
    episodes = 0
    for fill_id, fill in fills.items():
        key = fill["backtest_order_id"]
        checks.check("fill_order_exists", key in orders and key in trace_orders, fill_id)
        if key not in orders or key not in trace_orders:
            continue
        order, saved = orders[key]["order"], trace_orders[key]
        quantity = amount(fill["quantity"]["amount"])
        signed = quantity if fill["side"] == "BUY" else -quantity
        checks.check(
            "fill_units_and_ids",
            quantity > 0
            and fill["quantity"]["asset_id"] == base
            and fill["fee"]["asset_id"] == quote
            and fill["cost_breakdown"]["asset_id"] == quote
            and all(
                fill[name] == order[name]
                for name in ("client_order_id", "order_intent_id", "instrument_id", "side")
            )
            and fill["venue_order_id"] == orders[key]["venue_order_id"],
            fill_id,
        )
        checks.check(
            "fill_causal_clocks",
            at(order["decision_time"])
            == at(saved["decision_time"])
            <= at(order["submitted_at"])
            <= at(orders[key]["arrival_time"])
            <= at(fill["event_time"])
            <= at(fill["available_time"])
            <= at(fill["ingest_time"]),
            fill_id,
        )
        costs = fill["cost_breakdown"]
        fee = amount(fill["fee"]["amount"])
        reference, execution = (
            amount(fill["reference_price"]["amount"]),
            amount(fill["execution_price"]["amount"]),
        )
        adverse = sum((amount(costs[name]) for name in ("spread", "slippage", "impact")), ZERO)
        paid = sum((amount(costs[name]) for name in COST_FIELDS), ZERO)
        checks.equal(
            "reference_notional", amount(costs["gross_notional"]), quantity * reference, fill_id
        )
        checks.equal("fee_money", amount(costs["fee"]), fee, fill_id)
        checks.equal(
            "execution_price_cost_bridge", signed * (execution - reference), adverse, fill_id
        )
        by_order[key].append(fill)
        total_cost += paid
        if fill_position == 0:
            episodes += 1
        fill_position += signed
        checks.check("funded_long_fill_path", fill_position >= 0, fill_id)
        joined.append(
            {
                "run_id": run_id,
                "order_id": key,
                "fill_id": fill_id,
                "decision_time": at(saved["decision_time"]).isoformat(),
                "submitted_at": order["submitted_at"],
                "arrival_time": orders[key]["arrival_time"],
                "event_time": fill["event_time"],
                "available_time": fill["available_time"],
                "source_event_id": fill["source_event_id"],
                "reason_primary": execution_reason(saved),
                "reason": saved["reason"],
                "signed_quantity": str(signed),
                "reference_price": str(reference),
                "execution_price": str(execution),
                "gross_notional": costs["gross_notional"],
                "cost": str(paid),
                "fee_asset": fill["fee"]["asset_id"],
                "fee": str(fee),
            }
        )
    for key, saved_order in orders.items():
        order, linked = saved_order["order"], by_order[key]
        quantity = sum((amount(row["quantity"]["amount"]) for row in linked), ZERO)
        checks.equal(
            "order_cumulative_fill",
            amount(saved_order["cumulative_filled_quantity"]),
            quantity,
            key,
        )
        checks.check("order_not_overfilled", quantity <= amount(order["quantity"]["amount"]), key)
        if key in trace_orders:
            row = trace_orders[key]
            signed = amount(order["quantity"]["amount"]) * (1 if order["side"] == "BUY" else -1)
            checks.equal(
                "submitted_quantity_matches_trace",
                signed,
                amount(row["signed_planned_quantity"]),
                key,
            )
            checks.equal(
                "trace_fill_notional",
                amount(row["actual_fill_notional"]),
                sum((amount(f["cost_breakdown"]["gross_notional"]) for f in linked), ZERO),
                key,
            )
            checks.equal(
                "trace_realized_execution_cost",
                amount(row["realized_execution_cost"]),
                sum(
                    (
                        sum((amount(f["cost_breakdown"][name]) for name in COST_FIELDS), ZERO)
                        for f in linked
                    ),
                    ZERO,
                ),
                key,
            )
            checks.check(
                "trace_order_outcome",
                row["order_status"] == saved_order["status"]
                and row["rejection_reason"] == saved_order["rejection_code"],
                key,
            )
    checks.check(
        "terminal_flat",
        fill_position == 0 and amount(result["positions"][-1]["quantity"]) == 0,
        run_id,
    )
    checks.check("closed_episode_count", episodes == len(result["closed_trades"]), run_id)

    records = result["ledger_records"]
    cash: dict[str, Decimal] = defaultdict(lambda: ZERO)
    lots: dict[str, dict[str, Any]] = {}
    chain = "0" * 64
    seen_fill_records: dict[str, dict[str, Any]] = {}
    snapshots: list[dict[str, Any]] = []
    external_records = 0
    for ordinal, record in enumerate(records):
        identity = record["journal_entry"]["journal_entry_id"]
        checks.check(
            "ledger_hash_chain",
            record["previous_hash"] == chain
            and record["event_hash"]
            == canonical_sha256({k: v for k, v in record.items() if k != "event_hash"}),
            identity,
        )
        chain = record["event_hash"]
        journal = record["journal_entry"]
        checks.check(
            "journal_identity",
            identity == record["command_hash"]
            and not journal["reconciliation_adjustment"]
            and journal["supersedes_entry_id"] is None,
            identity,
        )
        balancing: dict[str, Decimal] = defaultdict(lambda: ZERO)
        cash_delta: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for posting in journal["postings"]:
            asset, value = posting["amount"]["asset_id"], amount(posting["amount"]["amount"])
            checks.check(
                "posting_nonnegative_and_side",
                value >= 0 and posting["side"] in {"DEBIT", "CREDIT"},
                identity,
            )
            signed = value if posting["side"] == "DEBIT" else -value
            balancing[asset] += signed
            if posting["account_id"].startswith("cash:"):
                cash_delta[asset] += signed
                cash[asset] += signed
        checks.check(
            "double_entry_by_asset",
            all(abs(value) <= MONEY_TOLERANCE for value in balancing.values()),
            identity,
        )
        source_fill = record["source_fill_id"]
        if source_fill is None:
            external_records += 1
            checks.check(
                "only_registered_initial_funding",
                ordinal == 0
                and record["entry_template_id"] == "external-transfer"
                and at(journal["event_time"]) == start
                and dict(cash_delta) == {quote: amount(spec["initial_cash"]["amount"])},
                identity,
            )
        else:
            checks.check(
                "unique_fill_ledger_link",
                source_fill in fills and source_fill not in seen_fill_records,
                identity,
            )
            seen_fill_records[source_fill] = record
            if source_fill in fills:
                fill = fills[source_fill]
                qty = amount(fill["quantity"]["amount"]) * (1 if fill["side"] == "BUY" else -1)
                checks.equal("ledger_fill_base_cash", cash_delta[base], qty, identity)
                checks.equal(
                    "ledger_fill_quote_cash",
                    cash_delta[quote],
                    -qty * amount(fill["execution_price"]["amount"])
                    - amount(fill["fee"]["amount"]),
                    identity,
                )
                checks.check(
                    "ledger_fill_clocks_and_intent",
                    record["source_order_intent_id"] == fill["order_intent_id"]
                    and record["idempotency_key"] == "simfill:" + source_fill
                    and at(journal["event_time"]) == at(fill["event_time"])
                    and at(journal["recorded_at"]) == at(fill["ingest_time"]),
                    identity,
                )
        for change in record["lot_changes"]:
            try:
                LotChange.model_validate_json(json.dumps(change))
            except ValueError:
                checks.check("lot_schema", False, identity)
                continue
            checks.check("lot_schema", True, identity)
            before, after = change["lot_before"], change["lot_after"]
            lot_id = (before or after)["position_lot_id"]
            checks.check(
                "lot_change_continuity", lots.get(lot_id) == before, identity + ":" + lot_id
            )
            for lot in (before, after):
                if lot is None:
                    continue
                opening = fills.get(lot["source_fill_id"])
                checks.check("lot_opening_fill_exists", opening is not None, lot_id)
                if opening is not None:
                    checks.check(
                        "lot_opening_fill_identity",
                        lot_id == canonical_sha256({"fill_id": opening["fill_id"], "ordinal": 0})
                        and opening["side"] == "BUY"
                        and lot["side"] == "LONG"
                        and lot["instrument_id"] == opening["instrument_id"]
                        and lot["quantity_unit"] == "BASE_ASSET"
                        and lot["quantity_asset_id"] == base
                        and lot["settlement_asset_id"] == quote
                        and lot["contract_form"] == "SPOT"
                        and amount(lot["contract_multiplier"]) == 1
                        and at(lot["opened_at"]) == at(opening["event_time"]),
                        lot_id,
                    )
                    checks.equal(
                        "lot_opened_quantity",
                        amount(lot["opened_quantity"]),
                        amount(opening["quantity"]["amount"]),
                        lot_id,
                    )
                    checks.equal(
                        "lot_entry_price",
                        amount(lot["entry_price"]),
                        amount(opening["execution_price"]["amount"]),
                        lot_id,
                    )
                    checks.check(
                        "lot_opening_fee_asset",
                        lot["opening_fee"]["asset_id"] == quote,
                        lot_id,
                    )
                    checks.equal(
                        "lot_opening_fee",
                        amount(lot["opening_fee"]["amount"]),
                        amount(opening["fee"]["amount"]),
                        lot_id,
                    )
            if after is None:
                lots.pop(lot_id, None)
            else:
                lots[lot_id] = after
        checks.equal(
            "native_inventory_matches_net_lots",
            cash[base],
            sum((amount(lot["remaining_quantity"]) for lot in lots.values()), ZERO),
            identity,
        )
        checks.check(
            "native_cash_funded",
            cash[base] >= -MONEY_TOLERANCE and cash[quote] >= -MONEY_TOLERANCE,
            identity,
        )
        snapshots.append(
            {"time": at(journal["recorded_at"]), "quantity": cash[base], "cash": cash[quote]}
        )
    checks.check(
        "all_fills_have_ledger",
        set(seen_fill_records) == set(fills) and external_records == 1,
        run_id,
    )
    checks.check(
        "ledger_information_order",
        [r["time"] for r in snapshots] == sorted(r["time"] for r in snapshots),
        run_id,
    )
    for row in joined:
        ledger = seen_fill_records.get(row["fill_id"])
        row["ledger_event_hash"] = ledger["event_hash"] if ledger else None

    trace_by_time = {at(row["time"]): row for row in trace}
    raw_curve = result["equity_curve"]
    raw_times = [at(row["time"]) for row in raw_curve]
    checks.check(
        "raw_mtm_clock",
        raw_times == sorted(set(raw_times)) and raw_times[0] == start and raw_times[-1] == end,
        run_id,
    )
    cursor = 0
    information: dict[datetime, dict[str, Any]] = {}
    for point, time in zip(raw_curve, raw_times, strict=True):
        while cursor + 1 < len(snapshots) and snapshots[cursor + 1]["time"] <= time:
            cursor += 1
        snapshot = snapshots[cursor]
        checks.check("ledger_known_before_mark", snapshot["time"] <= time, time.isoformat())
        checks.equal(
            "ledger_cash_matches_every_mtm",
            snapshot["cash"],
            amount(point["cash"]),
            time.isoformat(),
        )
        checks.equal(
            "every_mtm_funding_identity",
            amount(point["cash"]) + amount(point["position_value"]),
            amount(point["equity"]),
            time.isoformat(),
        )
        saved = trace_by_time.get(time)
        price = amount(saved["known_close"]) if saved is not None else None
        if snapshot["quantity"] == 0:
            checks.equal(
                "every_mtm_native_position_value",
                amount(point["position_value"]),
                ZERO,
                time.isoformat(),
            )
        elif price is not None:
            checks.equal(
                "every_mtm_native_position_value",
                snapshot["quantity"] * price,
                amount(point["position_value"]),
                time.isoformat(),
            )
        else:
            checks.check("held_mtm_requires_saved_price", False, time.isoformat())
        if saved is not None:
            checks.equal(
                "decision_native_quantity",
                amount(saved["current_quantity"]),
                amount(snapshot["quantity"]),
                time.isoformat(),
            )
            checks.equal(
                "decision_quote_cash", amount(saved["cash"]), snapshot["cash"], time.isoformat()
            )
        information[time] = {"quantity": snapshot["quantity"], "mark": price, "source_time": time}
    points = tuple(EquityPoint.model_validate_json(json.dumps(row)) for row in raw_curve)
    grid = resample_equity(points, 14400)
    cursor = 0
    curve: list[dict[str, Any]] = []
    for point in grid:
        while cursor + 1 < len(raw_times) and raw_times[cursor + 1] <= point.time:
            cursor += 1
        info = information[raw_times[cursor]]
        curve.append(
            {
                "time": point.time,
                "equity": point.equity,
                "cash": point.cash,
                "position_value": point.position_value,
                **info,
            }
        )

    funnel: Counter[tuple[str, str, str, str]] = Counter()
    last_review = last_submitted = None
    clock_rows = no_order_reviews = 0
    for ordinal, row in enumerate(trace, 1):
        time = at(row["time"])
        funnel[
            (
                str(row["reason"]),
                str(row.get("resize_gate_reason")),
                str(row.get("rebalance_permitted")),
                str(row["order_status"]),
            )
        ] += 1
        if row.get("rebalance_permitted") is not None and review_interval_hours is not None:
            permitted = last_review is None or time - last_review >= timedelta(
                hours=review_interval_hours
            )
            shown = (
                at(row["last_regular_review"])
                if row.get("last_regular_review") is not None
                else None
            )
            submitted_before = (
                at(row["last_resize_time_before_decision"])
                if row.get("last_resize_time_before_decision") is not None
                else None
            )
            checks.check(
                "review_due_from_previous_state",
                row["rebalance_permitted"] is permitted,
                str(ordinal),
            )
            checks.check(
                "review_state_transition",
                shown == last_review or (permitted and shown == time),
                str(ordinal),
            )
            checks.check(
                "submitted_clock_is_not_fill_clock",
                submitted_before == last_submitted,
                str(ordinal),
            )
            clock_rows += 1
            if shown == time and not row.get("order_id"):
                no_order_reviews += 1
            last_review = shown
        reason = row.get("resize_gate_reason")
        if reason in {"REBALANCE_COST_EXCEEDS_RISK_BENEFIT", "REBALANCE_RISK_BENEFIT_COVERS_COST"}:
            benefit, cost = (
                amount(row["rebalance_risk_benefit"]),
                amount(row["rebalance_cost_equity_fraction"]),
            )
            accepted = benefit > 0 and cost <= cost_benefit_lambda * benefit
            checks.check(
                "recorded_cost_benefit_veto",
                accepted is (reason == "REBALANCE_RISK_BENEFIT_COVERS_COST"),
                str(ordinal),
            )
        if row.get("order_id"):
            last_submitted = time
            if review_interval_hours is not None:
                last_review = time
    return {
        "summary": {
            "run_id": run_id,
            "status": "VERIFIED_STORED_SIMULATION"
            if checks.passed
            else "INCONSISTENT_STORED_SIMULATION",
            "orders": len(orders),
            "fills": len(fills),
            "ledger_records": len(records),
            "trace_rows": len(trace),
            "raw_mtm_points": len(raw_curve),
            "grid_points": len(grid),
            "cost": str(total_cost),
            "initial_cash": spec["initial_cash"]["amount"],
            "final_cash": str(cash[quote]),
            "clock_rows_checked": clock_rows,
            "carried_mark_older_than_4h": sum(
                row["time"] - row["source_time"] > timedelta(hours=4) for row in curve
            ),
            "due_reviews_without_order": no_order_reviews,
            "checks": checks.counts,
        },
        "joins": joined,
        "curve": curve,
        "gate_funnel": [
            {
                "reason": key[0],
                "resize_gate_reason": key[1],
                "review_due": key[2],
                "order_status": key[3],
                "rows": count,
            }
            for key, count in sorted(funnel.items())
        ],
    }


def combine_segments(segments: Sequence[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for segment in segments:
        if not segment:
            raise ValueError("missing segment curve")
        if output:
            previous, current = output[-1], segment[0]
            if previous["time"] != current["time"] or any(
                previous[key] != current[key]
                for key in ("equity", "cash", "quantity", "position_value")
            ):
                raise ValueError("quarter boundary must preserve the paid exit and inherited cash")
            output.extend(segment[1:])
        else:
            output.extend(segment)
    if any(b["time"] - a["time"] != timedelta(hours=4) for a, b in pairwise(output)):
        raise ValueError("complete four-hour calendar required")
    return output


def tail_inventory(curves: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not curves or any(
        [r["time"] for r in curve] != [r["time"] for r in next(iter(curves.values()))]
        for curve in curves.values()
    ):
        raise ValueError("tail attribution needs the same full calendar for every asset")
    symbols = sorted(curves)
    size = len(curves[symbols[0]])
    if size < 2:
        raise ValueError("tail attribution needs at least two marks")
    if any(b["time"] - a["time"] != timedelta(hours=4) for a, b in pairwise(curves[symbols[0]])):
        raise ValueError("tail attribution needs a complete four-hour calendar")
    nav = [
        sum((curves[symbol][index]["equity"] for symbol in symbols), ZERO) for index in range(size)
    ]
    if any(value <= 0 for value in nav):
        raise ValueError("tail attribution requires positive portfolio NAV")
    returns = [(nav[index] - nav[index - 1]) / nav[index - 1] for index in range(1, size)]
    rank = (len(returns) + 19) // 20
    threshold = sorted(returns)[rank - 1]
    selected = [index for index in range(1, size) if returns[index - 1] <= threshold]
    rows: list[dict[str, Any]] = []
    for index in selected:
        components: list[dict[str, Any]] = []
        total = ZERO
        for symbol in symbols:
            previous, current = curves[symbol][index - 1], curves[symbol][index]
            change = current["equity"] - previous["equity"]
            total += change
            components.append(
                {
                    "symbol": symbol,
                    "quantity_before": str(previous["quantity"]),
                    "quantity_after": str(current["quantity"]),
                    "saved_mark_before": str(previous["mark"])
                    if previous["mark"] is not None
                    else None,
                    "saved_mark_after": str(current["mark"])
                    if current["mark"] is not None
                    else None,
                    "cash_change": str(current["cash"] - previous["cash"]),
                    "position_value_change": str(
                        current["position_value"] - previous["position_value"]
                    ),
                    "equity_change": str(change),
                    "portfolio_return_contribution": str(change / nav[index - 1]),
                    "source_mark_before": previous["source_time"].isoformat(),
                    "source_mark_after": current["source_time"].isoformat(),
                    "source_age_seconds_after": str(
                        (current["time"] - current["source_time"]).total_seconds()
                    ),
                }
            )
        residual = total - (nav[index] - nav[index - 1])
        if abs(residual) > MONEY_TOLERANCE:
            raise ValueError("asset changes do not sum to portfolio change")
        rows.append(
            {
                "start": curves[symbols[0]][index - 1]["time"].isoformat(),
                "end": curves[symbols[0]][index]["time"].isoformat(),
                "net_return": str(returns[index - 1]),
                "equity_change": str(total),
                "sum_residual": str(residual),
                "assets": components,
            }
        )
    return {
        "selection": "WORST_CEIL_5_PERCENT_OF_ALL_4H_RETURNS_INCLUDING_ALL_CUTOFF_TIES",
        "observations": len(returns),
        "minimum_selected": rank,
        "threshold": str(threshold),
        "selected": len(rows),
        "rows": rows,
        "meaning": "STORED_SIMULATED_ACCOUNT_CONTRIBUTIONS_NOT_CAUSAL_FACTOR_ALPHA",
    }


def validate_config(config: Mapping[str, Any]) -> None:
    match = re.fullmatch(r"alpha-r5-saved-evidence-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-SAVED-EVIDENCE-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_saved_evidence_v{match[2]}",
        "AQ-SAVED-EVIDENCE-OUTPUT",
    )
    require(
        config["scope"] == "B1_SAVED_SIMULATION_JOINS_NO_REPLAY"
        and config["saved_scope"]
        == {"r5_registered_runs": 55, "r4_f0_quarter_segments": 70, "new_strategy_runs": 0},
        "AQ-SAVED-EVIDENCE-SCOPE",
    )
    require(
        config["tail_fraction"] == "0.05"
        and config["source_period"] == ["2022-04-01T00:00:00Z", "2025-10-01T00:00:00Z"],
        "AQ-SAVED-EVIDENCE-FIXED-AUDIT",
    )


def build_documents(root: Path, sources: dict[str, Any]) -> Mapping[str, Any]:
    catalog, original = sources["b0_catalog"]["reads"], sources["b0_baseline"]["files"]
    reads: list[dict[str, Any]] = []

    def read(name: str) -> bytes:
        binding = catalog.get(name) or original.get(name)
        require(binding is not None, "AQ-SAVED-EVIDENCE-UNREGISTERED-SOURCE:" + name)
        path = checked_path(root, name)
        raw = path.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == binding["sha256"] and len(raw) == binding["bytes"],
            "AQ-SAVED-EVIDENCE-CHANGED-SOURCE:" + name,
        )
        reads.append({"path": name, "sha256": binding["sha256"], "bytes": len(raw)})
        return raw

    r5_manifest = sources["r5_manifest"]
    tasks: list[dict[str, Any]] = []
    for run in r5_manifest["planned_runs"]:
        arm, symbol, cost = (str(run[k]) for k in ("arm", "symbol", "cost"))
        require(
            symbol in SYMBOLS
            and arm in r5_manifest["config"]["arms"]
            and cost in r5_manifest["config"]["arms"][arm]["costs"],
            "AQ-SAVED-EVIDENCE-UNREGISTERED-RUN",
        )
        settings = {**r5_manifest["config"]["resize"], **r5_manifest["config"]["arms"][arm]}
        tasks.append(
            {
                "arm": arm,
                "symbol": symbol,
                "cost": cost,
                "segment": "continuous",
                "folder": f"{R5}/runs/{arm}/{symbol}/{cost}",
                "hours": None if arm == "G0" else settings["review_interval_hours"],
            }
        )
    require(len(tasks) == 55, "AQ-SAVED-EVIDENCE-R5-SCOPE")
    r4_registry = sources["r4_registry"]
    for trial in r4_registry["trials"]:
        if (trial["arm"], trial["mode"], trial["cost_multiplier"]) != (
            "F0",
            "REDECIDE_FUNDED",
            "1",
        ):
            continue
        require(
            trial["status"] == "REPLAYED"
            and trial["symbol"] in SYMBOLS
            and len(trial["segments"]) == 14,
            "AQ-SAVED-EVIDENCE-F0-SCOPE",
        )
        for segment in trial["segments"]:
            tasks.append(
                {
                    "arm": "F0",
                    "symbol": trial["symbol"],
                    "cost": "1",
                    "segment": segment["segment"],
                    "folder": f"{R4}/{trial['output']}/{segment['segment']}",
                    "hours": None,
                }
            )
    require(
        len(tasks) == 125 and len({r["folder"] for r in tasks}) == 125,
        "AQ-SAVED-EVIDENCE-COMPLETE-SCOPE",
    )
    summaries: list[dict[str, Any]] = []
    joins: list[dict[str, Any]] = []
    funnels: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str], list[list[dict[str, Any]]]] = defaultdict(list)
    for index, task in enumerate(tasks, 1):
        folder = task["folder"]
        result = json.loads(gzip.decompress(read(folder + "/result.json.gz")), parse_float=str)
        trace = pl.read_parquet(read(folder + "/decision_trace.parquet")).to_dicts()
        audit = audit_saved_result(
            result,
            trace,
            symbol=task["symbol"],
            review_interval_hours=task["hours"],
            cost_benefit_lambda=amount(r5_manifest["config"]["resize"]["cost_benefit_lambda"]),
        )
        tags = {k: task[k] for k in ("arm", "symbol", "cost", "segment")}
        summaries.append({**tags, **audit["summary"]})
        joins.extend({**tags, **row} for row in audit["joins"])
        funnels.extend({**tags, **row} for row in audit["gate_funnel"])
        groups[(task["arm"], task["cost"], task["symbol"])].append(audit["curve"])
        if index % 10 == 0:
            print(f"saved evidence {index}/{len(tasks)} (no strategy execution)", flush=True)
    curves = {key: combine_segments(value) for key, value in groups.items()}
    require(
        all(
            curve[0]["time"] == at("2022-04-01T00:00:00Z")
            and curve[-1]["time"] == at("2025-10-01T00:00:00Z")
            for curve in curves.values()
        ),
        "AQ-SAVED-EVIDENCE-FULL-REGISTERED-PERIOD",
    )
    tails: list[dict[str, Any]] = []
    for arm, cost in sorted({(key[0], key[1]) for key in curves}):
        sleeves = {symbol: curves[(arm, cost, symbol)] for symbol in SYMBOLS}
        tails.append({"arm": arm, "cost": cost, **tail_inventory(sleeves)})
    attribution = pl.read_parquet(read(R5 + "/execution_reason_attribution.parquet")).to_dicts()
    saved_r5 = [row for row in attribution if row["arm"] in r5_manifest["config"]["arms"]]
    saved_by_fill = {row["fill_id"]: row for row in saved_r5}
    reconstructed = [row for row in joins if row["arm"] != "F0"]
    derived_checks = AuditChecks()
    derived_checks.check("unique_saved_derived_fill_ids", len(saved_by_fill) == len(saved_r5), "R5")
    derived_checks.check(
        "complete_saved_derived_fill_ids",
        set(saved_by_fill) == {row["fill_id"] for row in reconstructed},
        "R5",
    )
    for row in reconstructed:
        prior = saved_by_fill.get(row["fill_id"])
        if prior is None:
            continue
        derived_checks.check(
            "saved_reason_and_order",
            prior["reason_primary"] == row["reason_primary"]
            and prior["order_id"] == row["order_id"],
            row["fill_id"],
        )
        for old_key, new_key in (
            ("filled_qty", "signed_quantity"),
            ("filled_notional", "gross_notional"),
            ("total_cost", "cost"),
            ("fee_paid", "fee"),
        ):
            derived_checks.equal(
                "saved_derived_" + old_key,
                amount(prior[old_key]),
                amount(row[new_key]),
                row["fill_id"],
            )
    passed = (
        all(row["status"] == "VERIFIED_STORED_SIMULATION" for row in summaries)
        and derived_checks.passed
    )
    ordinary = Counter(
        (row["arm"], row["cost"], row["reason_primary"])
        for row in joins
        if row["reason_primary"] in {"ORDINARY_RISK_REDUCE", "ORDINARY_RISK_RESTORE"}
    )
    status = "VERIFIED_STORED_SIMULATION" if passed else "INCONSISTENT_STORED_SIMULATION"
    return {
        "raw_source_inventory.json": {
            "reads": reads,
            "source_identity": "B0_HASHED_ORIGINAL_FILES_AND_R5_JOURNAL_BOUND_CATALOG",
            "new_strategy_runs": 0,
        },
        "raw_order_fill_ledger_audit.json": {
            "status": status,
            "runs": summaries,
            "joins": joins,
            "derived_table_checks": derived_checks.counts,
        },
        "recorded_gate_funnel.json": {
            "status": "OBSERVED_RECORDED_TERMINAL_GATES_ONLY",
            "total_decisions": sum(r["trace_rows"] for r in summaries),
            "groups": funnels,
            "all_internal_gate_evaluations": "NOT_PERSISTED_CANNOT_RECONSTRUCT_SKIPPED_GATES",
            "ordinary_fill_counts": [
                {"arm": key[0], "cost": key[1], "reason": key[2], "fills": value}
                for key, value in sorted(ordinary.items())
            ],
        },
        "all_worst_5pct_inventory.json": {
            "groups": tails,
            "statistical_test_or_bootstrap": False,
            "new_candidate_selection": False,
        },
        "evidence_gaps.json": {
            "still_unverified": [
                "EVERY_INTERNAL_GATE_AND_PRE_VETO_POST_SECOND_ROUNDING_TARGET",
                "EXTERNAL_ACK_CANCEL_AND_QUEUE_EVENT_STREAM",
                "INDEPENDENT_PIT_FEE_RULE_DEPTH_LATENCY",
                "CAUSAL_FACTOR_AND_EXECUTION_DECOMPOSITION_OF_TAIL",
                "COMPLETE_TRIAL_HISTORY_AND_UNUSED_HOLDOUT",
            ],
            "old_reports_preserved": True,
            "real_execution_verified": False,
            "research_conclusion": "NO_PROVEN_ALPHA",
        },
        "report.md": f"""# 已保存 R5 与 F0 原始模拟记录只读核验

**NO_PROVEN_ALPHA / CASH；模型、纸面、实盘和订单继续关闭。**

本批核验原 R5 的全部 55 个保存结果及原 F0 的 70 个季度分区；所有输入先与 B0 封存哈希核对。当前结果：**{status}**。这是读取原始模拟记录后的联结与算术核验，没有调用策略引擎、重建行情、重定价成交、训练或重新计算显著性。此前 HASH_ONLY/NOT_VERIFIED 报告保留，不能把本报告倒填成此前已经完成。

逐单核对 trace→order→fill→ledger、数量/时钟/费用资产、原账本哈希链和每资产借贷平衡，并从已有 postings 和 lot changes 核对每个已保存 MTM 的资金、原生库存和已记录价格。F0 季度边界要求付费退出与下一季度初始资金一致，不能遗漏不利边界。检查逐项计数和失败示例见 raw_order_fill_ledger_audit.json；失败不会被删掉或强制改成预期数字。

共读取 {sum(r["trace_rows"] for r in summaries)} 行决策 trace。门槛表覆盖这些行的已记录终态理由；它不是未保存的逐个内部门槛执行轨迹。复核状态从前行保存状态及提交事件核对，未下单也可能消耗到期复核。没有外部 ack/cancel/queue 流，不能据此声称真实场所时钟已验证。

最差窗口固定为每个策略/成本组完整四小时日历的最差 ceil(5%×N)，临界值并列全部保留；每个窗口列出全部五币的原生持仓、cash/position value 变化和组合收益贡献。沿用原 resample_equity 的已知标记前填规则并记录 source_time/标记年龄；网格完整不代表底层行情无缺口。只是原模拟账户贡献，不是因果因子归因或信号 alpha。没有读取新的行情，也没有事后挑选一两个故事窗口。

仍缺逐个内部门槛、veto 前和二次取整后完整目标、真实 PIT/费用/盘口/延迟、完整试验史及未使用留出。任务的完整实证验收仍未完成；所有新历史策略回放、真实收益模型拟合、真实校准拟合、最终留出读取和真实订单均为 0。
""",
    }
