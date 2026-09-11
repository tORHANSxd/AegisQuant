"""R4 checkpoint recovery by replaying persisted causal events in the original ledger."""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import BacktestResult, BacktestRunSpec, BarEvent
from aegisquant.data.hashing import canonical_sha256
from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.research.strategies.buffered_target import BufferPolicy
from aegisquant.research.strategies.cost_aware_trend import build_trend_features, trend_targets
from aegisquant.research.validation.cat_replay import CatMarket, replay_cat
from scripts.export_alpha_v4_audit_bundle import digest
from scripts.run_alpha_r4 import read_result
from scripts.run_alpha_v4_audit import ROOT, inputs, read_json
from scripts.run_alpha_v4_audit_r2 import policies
from scripts.run_alpha_v4_walkforward import write_json

STATE_FIELDS = (
    "time",
    "cash",
    "current_quantity",
    "target_quantity",
    "pending_quantity",
    "reason",
    "known_close",
    "current_weight",
    "final_weight",
    "signed_planned_quantity",
    "trend_state",
    "risk_vol_estimate",
    "risk_only_weight",
    "last_resize_time_before_decision",
    "rebalance_permitted",
    "buffer_lower",
    "buffer_upper",
    "buffer_reason",
)


def replay_journal(
    *,
    bars: tuple[BarEvent, ...],
    spec: BacktestRunSpec,
    market: CatMarket,
    gate: EconomicGatePolicy,
    buffered: bool,
    final: bool,
) -> tuple[BacktestResult, list[dict[str, Any]]]:
    """Reconstruct every hidden engine/strategy state from known immutable input.

    ponytail: prefix replay costs O(n²) over checkpoints; a resumable engine session
    is only warranted if research restart time becomes material. No second ledger.
    The journal includes warmup. It contains no event beyond its observed boundary.
    """
    features = build_trend_features(bars)
    trend = trend_targets(features.values[:, 0], features.valid)
    return replay_cat(
        root=ROOT,
        spec=spec,
        bars=tuple(b for b in bars if b.event_time >= spec.start_time),
        features=features,
        feature_indices={t: i for i, t in enumerate(features.available_times)},
        trend_by_time={t: bool(v) for t, v in zip(features.available_times, trend, strict=True)},
        forecasts={},
        level="A1",
        audit_policy=policies()["A1"],
        gate_policy=gate,
        market_spec=market,
        buffer_policy=BufferPolicy() if buffered else None,
        terminal_exit=final,
        terminal_exit_reason="EVALUATION_END_NEXT_OPEN_EXIT",
    )


def known_state(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Normalize parquet datetimes and reconstructed Python datetimes identically.
    return [{key: str(row.get(key)) for key in STATE_FIELDS} for row in trace]


def compare_prefix(
    full: BacktestResult, restored: BacktestResult, time: datetime, *, final: bool
) -> dict[str, Any]:
    expected_fills = tuple(f for f in full.fills if f.available_time < time)
    if restored.fills != expected_fills:
        raise ValueError("checkpoint restoration changed fills or their identities")
    ids = {f.fill_id for f in expected_fills}
    # Spot R4 has only initial funding and fill records, no transfers/borrow/funding.
    expected_records = tuple(
        r for r in full.ledger_records if r.source_fill_id is None or r.source_fill_id in ids
    )
    if restored.ledger_records != expected_records:
        raise ValueError("checkpoint restoration changed authoritative ledger or cost basis")
    full_points = {p.time: p for p in resample_equity(full.equity_curve, 14400)}
    for point in resample_equity(restored.equity_curve, 14400):
        if point != full_points[point.time]:
            raise ValueError("checkpoint restoration changed complete cash/MTM clock")
    complete = [o for o in full.orders if o.completed_at is not None and o.completed_at < time]
    by_order = {o.order.backtest_order_id: o for o in restored.orders}
    if any(by_order[o.order.backtest_order_id] != o for o in complete):
        raise ValueError("checkpoint restoration changed a previously completed order")
    pending = [
        o
        for o in restored.orders
        if o.order.backtest_order_id not in {c.order.backtest_order_id for c in complete}
    ]
    # Terminal result formatting marks accepted orders expired. Restore uses the
    # persisted event journal, so this reporting status is NEVER fed into execution.
    if any(o.order not in [f.order for f in full.orders] for o in pending):
        raise ValueError("checkpoint restoration produced a new pending order")
    if final:
        for field in (
            "orders",
            "positions",
            "equity_curve",
            "economic_event_hash",
            "closed_trades",
            "cost_identity_residual",
        ):
            if getattr(restored, field) != getattr(full, field):
                raise ValueError(f"final reconstructed state differs: {field}")
    return {
        "fills": len(expected_fills),
        "ledger_records": len(expected_records),
        "completed_orders": len(complete),
        "pending_orders_to_reconstruct_from_journal": len(pending),
        "cash": str(restored.equity_curve[-1].cash),
        "position_quantity": str(restored.positions[-1].quantity),
        "average_entry_price": str(restored.positions[-1].average_entry_price),
        "final_economic_hash_matched": final,
    }


def verify_boundaries(output: Path, symbol: str = "BTCUSDT") -> None:
    target = output / "boundary_checkpoints" / symbol
    if target.exists():
        raise FileExistsError("checkpoint evidence already exists")
    target.mkdir(parents=True)
    config = read_json(output / "effective_config.json")
    _, market, bars, _, _, _, folds, _, _ = inputs(symbol)
    gate = EconomicGatePolicy.model_validate_json(json.dumps(config["gate"]))
    checks: list[dict[str, Any]] = []
    for arm in ("F2", "F3"):
        folder = output / "runs" / arm / symbol / "REDECIDE_FUNDED_1/continuous"
        full = read_result(folder)
        trace = pl.read_parquet(folder / "decision_trace.parquet").to_dicts()
        previous_file: Path | None = None
        previous_count = 0
        persisted: list[str] = []
        for number, fold in enumerate(folds, 1):
            print(f"checkpoint {arm} {symbol} quarter {number}/14", flush=True)
            prefix = tuple(b for b in bars if b.available_time < fold.test_end)
            if previous_file is not None:
                with gzip.open(previous_file, "rt", encoding="utf-8") as stream:
                    previous = json.load(stream)
                persisted = previous["events"]
                if canonical_sha256(persisted) != previous["events_sha256"]:
                    raise ValueError("checkpoint event journal corrupted")
            persisted += [b.model_dump_json() for b in prefix[previous_count:]]
            path = target / f"{arm}_{fold.fold_id}.json.gz"
            payload = {
                "version": "r4-event-journal-checkpoint-v1",
                "events": persisted,
                "events_sha256": canonical_sha256(persisted),
                "observed_through": fold.test_end.isoformat(),
                "input_source_sha256": config["integrated_source_sha256"],
                "spec": full.spec.model_dump_json(),
                "gate": config["gate"],
                "execution": config["audit_policy"],
                "latency_rule_cost_contract": "unchanged cat-proxy-v2 and market precision from frozen effective inputs",
                "external_orders_cancels_faults_funding_multileg": [],
                "recovery": "recompute full engine and strategy state from persisted known event prefix; not in-place session restore",
            }
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                json.dump(payload, stream)
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                checkpoint = json.load(stream)
            restored_bars = tuple(BarEvent.model_validate_json(s) for s in checkpoint["events"])
            if restored_bars != prefix or any(
                b.available_time >= fold.test_end for b in restored_bars
            ):
                raise ValueError("journal contains missing, modified or future events")
            final = number == len(folds)
            spec = BacktestRunSpec.model_validate_json(checkpoint["spec"]).model_copy(
                update={"end_time": fold.test_end}
            )
            result, restored_trace = replay_journal(
                bars=restored_bars,
                spec=spec,
                market=market,
                gate=gate,
                buffered=arm == "F3",
                final=final,
            )
            prior_trace = [r for r in trace if r["time"] < fold.test_end]
            if known_state(restored_trace) != known_state(prior_trace):
                raise ValueError(
                    "restoration changed trend/risk/cooldown/pending/quantity decisions"
                )
            checked = compare_prefix(full, result, fold.test_end, final=final)
            checks.append(
                {
                    "arm": arm,
                    "symbol": symbol,
                    "quarter": fold.fold_id,
                    "status": "PASS",
                    "journal_sha256": digest(path),
                    "known_events_including_warmup": len(prefix),
                    "trace_rows_compared": len(prior_trace),
                    **checked,
                }
            )
            write_json(target / "progress.json", {"checks": checks})
            previous_file, previous_count = path, len(prefix)
    write_json(
        output / "boundary_state_checks.json",
        {
            "status": "PASS",
            "checks": checks,
            "method": "save known event journal each quarter, load it and append only new events; replay original engine to recover all state",
            "in_place_incremental_session_restore": "NOT_IMPLEMENTED_NOT_REQUIRED_FOR_SINGLE_PASS_MAIN_RUN",
            "main_execution": "one uninterrupted run per sleeve; quarter boundaries are report slices only",
            "final_exit": "only final evaluation endpoint, next known eligible open inside evaluation period",
            "scope": "two actual BTC strategies, all 14 quarter prefixes plus final full economic identity; shared algorithm also covered by synthetic mutation tests",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args()
    verify_boundaries(args.output.resolve(), args.symbol)
