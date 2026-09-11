"""Finite R4 research, using the existing event ledger and frozen public inputs."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import traceback
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import BacktestResult
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import RunId
from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.research.strategies.buffered_target import BufferPolicy
from aegisquant.research.strategies.cost_aware_trend import (
    R4TrendPolicy,
    build_trend_features,
    trend_targets,
)
from aegisquant.research.validation.cat_replay import replay_cat
from scripts.export_alpha_v4_audit_bundle import digest, git
from scripts.run_alpha_v4_audit import (
    ROOT,
    SYMBOLS,
    AuditInputs,
    inputs,
    make_spec,
    read_json,
    save_result,
    trial_collections,
)
from scripts.run_alpha_v4_audit_r2 import policies
from scripts.run_alpha_v4_walkforward import table, write_json

BASELINE = ROOT / "artifacts/current_system_backtest/20260908_v1"
TASKBOOK = ROOT / "AegisQuant_R4/AegisQuant_R4_低换手与连续持仓优化任务书_20260908.md"


def snapshot(output: Path) -> dict[str, str]:
    files = sorted(
        [*ROOT.glob("src/**/*.py"), *ROOT.glob("scripts/*.py"), *ROOT.glob("configs/**/*.yaml")]
    )
    files += [ROOT / "pyproject.toml", ROOT / "uv.lock", TASKBOOK]
    hashes: dict[str, str] = {}
    for source in files:
        name = source.relative_to(ROOT).as_posix()
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = digest(target)
    write_json(output / "source_manifest.json", {"files": hashes})
    return hashes


def preregister(output: Path) -> None:
    if output.exists():
        raise FileExistsError("preserve existing R4 evidence; select a new run directory")
    if git(ROOT, "branch", "--show-current") != "main":
        raise ValueError("R4 requires the existing main checkout")
    original = read_json(BASELINE / "run_manifest.json")
    for name, expected in original["source_sha256"].items():
        if name == "scripts/run_current_system_backtest.py":
            expected = read_json(BASELINE / "aggregation_manifest.json")["source_sha256"]
        if digest(ROOT / name) != expected:
            raise ValueError(f"baseline implementation binding differs: {name}")
    output.mkdir(parents=True)
    config = {
        "version": "alpha-r4-v1",
        "registered_at": datetime.now(UTC).isoformat(),
        "evidence_tier": "RETROSPECTIVE_DEVELOPMENT",
        "source_head": git(ROOT, "rev-parse", "HEAD"),
        "dirty_status": git(ROOT, "status", "--porcelain=v1"),
        "dirty_diff_summary": git(ROOT, "diff", "--stat"),
        "source_before": snapshot(output / "implementation_before"),
        "baseline_manifest_sha256": digest(BASELINE / "run_manifest.json"),
        "baseline_files": {
            p.relative_to(BASELINE).as_posix(): digest(p)
            for p in sorted(BASELINE.rglob("*"))
            if p.is_file()
        },
        "dataset_manifest": read_json(ROOT / "artifacts/alpha_v4_multi_asset/source_manifest.json"),
        "taskbook_sha256": digest(TASKBOOK),
        "test_start": original["test_start"],
        "test_end_exclusive": original["test_end_exclusive"],
        "symbols": SYMBOLS,
        "initial_cash_per_symbol": "10000",
        "gate": original["gate"],
        "audit_policy": original["arms"]["A1"],
        "risk_estimator": "42 completed 4h log returns, population std * sqrt(365.25 * 6)",
        "risk_scope": "independent sleeve target 20%; no portfolio covariance target",
        "review_clock": "original 86400s since last submitted order, checked each completed 4h bar",
        "hard_limits": "long/flat spot, maximum sleeve weight 1, no borrowing, cash >= 0; risk target is soft",
        "buffer": "additional 0.10 * full-trend risk quantity, nearest edge; retain existing economic band",
        "arms": {
            "F0": {"buffer": False, "continuous": False, "signal": "A1"},
            "F1": {"buffer": True, "continuous": False, "signal": "A1"},
            "F2": {"buffer": False, "continuous": True, "signal": "A1"},
            "F3": {"buffer": True, "continuous": True, "signal": "A1"},
            "F4": {"buffer": True, "continuous": True, "signal": "EQUAL_10_40_20_80_40_160"},
            "F5": {"buffer": True, "continuous": True, "signal": "RISK_MANAGED_HOLD"},
        },
        "primary_candidate": "F3",
        "cost_multipliers": ["1", "1.5", "2"],
        "cost_modes": ["SAME_FILL_SHADOW", "FROZEN_ORDERS_FUNDED", "REDECIDE_FUNDED"],
        "bootstrap": {
            "seed": 20260908,
            "repetitions": 10000,
            "frequency": "daily UTC, common five-sleeve clock",
            "block_length_rule": "max automatic stationary block estimate across paired daily returns and squared returns; ceil, bounded [2, n/3]",
            "comparisons": ["F1-F0", "F2-F0", "F3-F2", "F3-F1", "F3-F0", "F4-F3", "F3-F5", "F4-F5"],
        },
        "new_model_fits": 0,
        "new_calibration_fits": 0,
        "parameter_searches": 0,
        "final_holdout_access_count": 0,
        "production_policy": "CASH",
        "selected_model_id": None,
        "production_ml_enabled": False,
        "paper_trading_admitted": False,
        "live_trading": False,
        "order_submission_enabled": False,
    }
    config["sha256"] = canonical_sha256(config)
    write_json(output / "audit_manifest.json", config)
    write_json(output / "effective_config.json", config)
    print("R4 preregistered; baseline source and dirty workspace preserved", flush=True)


def reproduce(output: Path, *, input_loader: Callable[[str], AuditInputs] = inputs) -> None:
    config = read_json(output / "audit_manifest.json")
    original = read_json(BASELINE / "run_manifest.json")
    if (output / "baseline_reproduction.json").exists():
        raise FileExistsError("successful baseline evidence already exists")
    folder = output / "baseline" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    folder.mkdir(parents=True)
    expected = {
        name: pl.read_parquet(BASELINE / f"{name}.parquet").filter(pl.col("level") == "A1")
        for name in ("orders", "fills", "mtm_equity")
    }
    transitions = pl.read_parquet(BASELINE / "cash_transitions.parquet")
    checks: list[dict[str, Any]] = []
    collection = trial_collections()
    traces: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        source, market, bars, features, _, _, folds, indices, trend = input_loader(symbol)
        cash = Decimal("10000")
        for fold in folds:
            print(f"P0 {symbol} {fold.fold_id}", flush=True)
            spec = make_spec(symbol, fold, "A1", source, original, cash).model_copy(
                update={"run_id": RunId(f"current-r2-{symbol}-{fold.fold_id}-A1")}
            )
            allowed = set(fold.test_indices)
            result, trace = replay_cat(
                root=ROOT,
                spec=spec,
                bars=tuple(b for b in bars if fold.test_start <= b.event_time < fold.test_end),
                features=features,
                feature_indices=indices,
                trend_by_time={t: v and indices[t] in allowed for t, v in trend.items()},
                forecasts={},
                level="A1",
                audit_policy=policies()["A1"],
                gate_policy=EconomicGatePolicy.model_validate_json(json.dumps(config["gate"])),
                market_spec=market,
            )
            for name, rows in (("orders", result.orders), ("fills", result.fills)):
                prior = expected[name].filter(
                    (pl.col("symbol") == symbol) & (pl.col("fold_id") == fold.fold_id)
                )
                if [json.loads(p) for p in prior["payload_json"]] != [
                    r.model_dump(mode="json") for r in rows
                ]:
                    raise ValueError(
                        f"A1 exact {name} identity/payload mismatch {symbol}/{fold.fold_id}"
                    )
            old = transitions.filter(
                (pl.col("arm") == "A1")
                & (pl.col("symbol") == symbol)
                & (pl.col("fold_id") == fold.fold_id)
            ).to_dicts()[0]
            if cash != Decimal(old["initial_cash"]):
                raise ValueError("A1 cash inheritance mismatch")
            cash = result.equity_curve[-1].equity
            if cash != Decimal(old["final_cash"]) or result.positions[-1].quantity != 0:
                raise ValueError("A1 final cash or costed exit mismatch")
            prior_equity = (
                expected["mtm_equity"]
                .filter((pl.col("symbol") == symbol) & (pl.col("fold_id") == fold.fold_id))
                .to_dicts()
            )
            actual = resample_equity(result.equity_curve, 14400)
            if len(actual) != len(prior_equity) or any(
                p.time != r["time"]
                or any(getattr(p, k) != Decimal(r[k]) for k in ("equity", "cash", "position_value"))
                for p, r in zip(actual, prior_equity, strict=True)
            ):
                raise ValueError("A1 complete MTM differs")
            checks.append(
                {
                    "symbol": symbol,
                    "fold_id": fold.fold_id,
                    "status": "PASS",
                    "orders": len(result.orders),
                    "fills": len(result.fills),
                    "mtm_points": len(actual),
                    "final_cash": str(cash),
                }
            )
            counts = {name: len(rows) for name, rows in collection.items()}
            save_result(collection, result, fold, "F0")
            for name, rows in collection.items():
                for row in rows[counts[name] :]:
                    row["symbol"] = symbol
            traces.extend({"arm": "F0", "fold_id": fold.fold_id, **r} for r in trace)
    for name, rows in collection.items():
        table(folder / f"{name}.parquet", rows)
    table(folder / "decision_trace.parquet", traces)
    write_json(
        output / "baseline_reproduction.json",
        {
            "status": "PASS",
            "output": folder.relative_to(output).as_posix(),
            "exact_order_and_fill_identity": True,
            "complete_mtm_and_cash_chain": True,
            "partitions": checks,
        },
    )
    print("A1 exact reproduction PASS: 70 partitions", flush=True)


def read_result(folder: Path) -> BacktestResult:
    with gzip.open(folder / "result.json.gz", "rt", encoding="utf-8") as stream:
        return BacktestResult.model_validate_json(stream.read())


def save_run(folder: Path, result: BacktestResult, trace: list[dict[str, Any]]) -> None:
    folder.mkdir(parents=True)
    with gzip.open(folder / "result.json.gz", "wt", encoding="utf-8") as stream:
        stream.write(result.model_dump_json())
    table(folder / "decision_trace.parquet", trace)
    write_json(
        folder / "completion.json",
        {
            "status": "REPLAYED",
            "economic_hash": result.economic_event_hash,
            "files": {p.name: digest(p) for p in folder.iterdir() if p.is_file()},
        },
    )


def ensemble(data: AuditInputs) -> tuple[dict[datetime, Decimal], list[dict[str, Any]]]:
    _, _, bars, _, _, _, folds, _, _ = data
    signal_values: list[np.ndarray[Any, Any]] = []
    ready: list[np.ndarray[Any, Any]] = []
    for fast, slow in ((10, 40), (20, 80), (40, 160)):
        policy = R4TrendPolicy.model_validate({"fast_days": fast, "slow_days": slow})
        features = build_trend_features(bars, policy)
        signal_values.append(trend_targets(features.values[:, 0], features.valid, policy))
        ready.append(features.valid)
    # All three budgets remain reserved until their own causal windows are ready.
    # No redistribution to a shorter window after a gap.
    values: dict[datetime, Decimal] = {}
    readiness: list[dict[str, Any]] = []
    for i, bar in enumerate(bars):
        all_ready = all(bool(r[i]) for r in ready)
        active = sum(int(s[i]) for s in signal_values)
        values[bar.available_time] = Decimal(active) / 3 if all_ready else Decimal("0")
        if bar.event_time >= folds[0].test_start:
            readiness.append(
                {
                    "time": bar.available_time,
                    "ready_10_40": bool(ready[0][i]),
                    "ready_20_80": bool(ready[1][i]),
                    "ready_40_160": bool(ready[2][i]),
                    "all_ready": all_ready,
                    "signal_10_40": int(signal_values[0][i]),
                    "signal_20_80": int(signal_values[1][i]),
                    "signal_40_160": int(signal_values[2][i]),
                    "signal_budget_fraction": str(values[bar.available_time]),
                }
            )
    return values, readiness


def run_sleeve(
    output: Path, arm: str, symbol: str, data: AuditInputs, mode: str, multiplier: str
) -> dict[str, Any]:
    config = read_json(output / "effective_config.json")
    source, market, bars, features, _, _, folds, indices, trend = data
    settings = config["arms"][arm]
    continuous = settings["continuous"]
    segments = (
        (replace(folds[0], fold_id="continuous", test_end=folds[-1].test_end),)
        if continuous
        else folds
    )
    fractions = None
    readiness: list[dict[str, Any]] = []
    if arm == "F4":
        fractions, readiness = ensemble(data)
        trend = {t: v > 0 for t, v in fractions.items()}
    elif arm == "F5":
        # A long holding signal has no EMA readiness dependency. Independent
        # current risk/data checks in the original gate still apply every bar.
        trend = dict.fromkeys(trend, True)
    sleeve = output / "runs" / arm / symbol / f"{mode}_{multiplier}"
    if sleeve.exists():
        raise FileExistsError(f"run already exists: {sleeve.relative_to(output)}")
    cash = Decimal("10000")
    summary: list[dict[str, Any]] = []
    for segment in segments:
        print(f"R4 {arm} {symbol} {segment.fold_id} {mode} cost={multiplier}", flush=True)
        local_bars = tuple(b for b in bars if segment.test_start <= b.event_time < segment.test_end)
        allowed = set(segment.test_indices)
        local_trend = (
            trend if continuous else {t: v and indices[t] in allowed for t, v in trend.items()}
        )
        spec = make_spec(symbol, segment, arm, source, config, cash).model_copy(
            update={
                "run_id": RunId(f"r4-{arm}-{symbol}-{segment.fold_id}"),
                "code_sha256": config["integrated_source_sha256"],
                "reproduction_command": "python -m scripts.run_alpha_r4 matrix --output <registered-output>",
            }
        )
        fixed_orders = None
        base = None
        base_folder = output / "runs" / arm / symbol / "REDECIDE_FUNDED_1" / segment.fold_id
        if mode == "FROZEN_ORDERS_FUNDED":
            base = read_result(base_folder)
            fixed_orders = tuple(o.order for o in base.orders)
        result, trace = replay_cat(
            root=ROOT,
            spec=spec,
            bars=local_bars,
            features=features,
            feature_indices=indices,
            trend_by_time=local_trend,
            forecasts={},
            level="A1",
            audit_policy=policies()["A1"],
            gate_policy=EconomicGatePolicy.model_validate_json(json.dumps(config["gate"])),
            market_spec=market,
            cost_multiplier=Decimal(multiplier),
            fixed_orders=fixed_orders,
            buffer_policy=BufferPolicy() if settings["buffer"] else None,
            signal_fractions=fractions,
            terminal_exit_reason="EVALUATION_END_NEXT_OPEN_EXIT"
            if continuous or segment == segments[-1]
            else "PREREGISTERED_FOLD_END_NEXT_OPEN_EXIT",
        )
        folder = sleeve / segment.fold_id
        save_run(folder, result, trace)
        if arm == "F0" and multiplier == "1":
            previous = pl.read_parquet(BASELINE / "fills.parquet").filter(
                (pl.col("level") == "A1")
                & (pl.col("symbol") == symbol)
                & (pl.col("fold_id") == segment.fold_id)
            )
            from scripts.run_alpha_v4_audit_r2 import strip_identity

            if [strip_identity(json.loads(p)) for p in previous["payload_json"]] != [
                strip_identity(f.model_dump(mode="json")) for f in result.fills
            ]:
                raise ValueError("integrated F0 changed original A1 execution")
            original_cash = pl.read_parquet(BASELINE / "cash_transitions.parquet").filter(
                (pl.col("arm") == "A1")
                & (pl.col("symbol") == symbol)
                & (pl.col("fold_id") == segment.fold_id)
            )["final_cash"][0]
            if result.equity_curve[-1].equity != Decimal(original_cash):
                raise ValueError("integrated F0 changed original A1 cash")
        terminal_trace = next(
            (
                r
                for r in trace
                if r["reason"]
                in {"PREREGISTERED_FOLD_END_NEXT_OPEN_EXIT", "EVALUATION_END_NEXT_OPEN_EXIT"}
            ),
            None,
        )
        cash = result.equity_curve[-1].equity
        costs = sum((f.cost_breakdown.total for f in result.fills), Decimal("0"))
        terminal_fills = [
            f
            for f in result.fills
            if f.event_time == local_bars[-1].event_time and f.side.value == "SELL"
        ]
        row = {
            "segment": segment.fold_id,
            "initial_cash": str(spec.initial_cash.amount),
            "final_equity": str(cash),
            "final_cash": str(result.equity_curve[-1].cash),
            "position_quantity": str(result.positions[-1].quantity),
            "total_cost": str(costs),
            "orders": len(result.orders),
            "fills": len(result.fills),
            "rejections": sum(bool(o.rejection_code) for o in result.orders),
            "closed_trades": len(result.closed_trades),
            "cost_identity_residual": str(result.cost_identity_residual),
            "exit_decision_mtm": str(
                Decimal(terminal_trace["cash"])
                + Decimal(terminal_trace["current_quantity"])
                * Decimal(terminal_trace["known_close"])
            )
            if terminal_trace
            else None,
            "terminal_mtm_at_exit_reference": str(
                cash + sum((f.cost_breakdown.total for f in terminal_fills), Decimal("0"))
            ),
            "exit_reference_time": local_bars[-1].event_time,
            "forced_close_status": result.forced_close_status,
            "same_fill_quantities_as_1x": [
                (str(f.backtest_order_id), f.quantity.amount) for f in result.fills
            ]
            == [(str(f.backtest_order_id), f.quantity.amount) for f in base.fills]
            if base
            else None,
        }
        summary.append(row)
        if result.positions[-1].quantity != 0:
            write_json(
                sleeve / "summary.json",
                {
                    "status": "FAILED_UNLIQUIDATED_RESIDUAL_NO_FAKE_CASH_INHERITANCE",
                    "segments": summary,
                },
            )
            return {
                "arm": arm,
                "symbol": symbol,
                "mode": mode,
                "cost_multiplier": multiplier,
                "status": "FAILED_UNLIQUIDATED_RESIDUAL",
                "output": sleeve.relative_to(output).as_posix(),
            }
    if readiness:
        table(sleeve / "signal_readiness.parquet", readiness)
    result_row = {
        "arm": arm,
        "symbol": symbol,
        "mode": mode,
        "cost_multiplier": multiplier,
        "status": "REPLAYED",
        "output": sleeve.relative_to(output).as_posix(),
        "final_cash": str(cash),
        "segments": summary,
    }
    write_json(sleeve / "summary.json", result_row)
    return result_row


def matrix(output: Path, *, challengers: bool = False) -> None:
    baseline = read_json(output / "baseline_reproduction.json")
    if baseline["status"] != "PASS":
        raise ValueError("A1 exact reproduction must pass before R4 experiments")
    if not (output / "implementation/source_manifest.json").exists():
        config = read_json(output / "effective_config.json")
        config["integrated_source"] = snapshot(output / "implementation")
        config["integrated_source_sha256"] = canonical_sha256(config["integrated_source"])
        config["sha256"] = canonical_sha256({k: v for k, v in config.items() if k != "sha256"})
        write_json(output / "effective_config.json", config)
    config = read_json(output / "effective_config.json")
    # Strategy and ledger code cannot drift between scenarios. Reporting-only
    # edits retain a separate identity and do not rerun completed market trials.
    for name, expected in config["integrated_source"].items():
        if name.startswith("src/") and digest(ROOT / name) != expected:
            raise ValueError(f"integrated research source changed: {name}")
    registry_path = output / "experiment_registry.json"
    registry: dict[str, Any] = (
        read_json(registry_path)
        if registry_path.exists()
        else {
            "status": "IMPLEMENTED",
            "new_configuration_count": 6,
            "primary_candidate": "F3",
            "new_model_fits": 0,
            "new_calibration_fits": 0,
            "trials": [],
        }
    )
    arms = ("F4", "F5") if challengers else ("F0", "F1", "F2", "F3")
    if challengers:
        completed = {
            (r["arm"], r["symbol"], r["mode"], r["cost_multiplier"])
            for r in registry["trials"]
            if r["status"] == "REPLAYED"
        }
        if any(
            (arm, symbol, "REDECIDE_FUNDED", "1") not in completed
            for arm in ("F0", "F1", "F2", "F3")
            for symbol in SYMBOLS
        ):
            raise ValueError("F0-F3 must complete before the fixed challengers")
    for symbol in SYMBOLS:
        data = inputs(symbol)
        for arm in arms:
            scenarios = [
                ("REDECIDE_FUNDED", "1"),
                *[
                    (mode, m)
                    for m in ("1.5", "2")
                    for mode in ("FROZEN_ORDERS_FUNDED", "REDECIDE_FUNDED")
                ],
            ]
            for mode, multiplier in scenarios:
                if any(
                    r["arm"] == arm
                    and r["symbol"] == symbol
                    and r["mode"] == mode
                    and r["cost_multiplier"] == multiplier
                    for r in registry["trials"]
                ):
                    continue
                row = run_sleeve(output, arm, symbol, data, mode, multiplier)
                registry["trials"].append(row)
                write_json(registry_path, registry)
    registry["status"] = "REPLAYED" if challengers else "CORE_REPLAYED"
    write_json(registry_path, registry)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "baseline", "matrix", "challengers"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "challengers":
            matrix(args.output.resolve(), challengers=True)
        else:
            {"register": preregister, "baseline": reproduce, "matrix": matrix}[args.command](
                args.output.resolve()
            )
    except Exception:
        if args.output.exists():
            (args.output / "failures").mkdir(exist_ok=True)
            write_json(
                args.output / "failures" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}.json",
                {
                    "command": args.command,
                    "source_sha256": digest(Path(__file__)),
                    "traceback": traceback.format_exc(),
                    "status": "FAILED_NOT_PASSED",
                },
            )
        raise
