"""Finite R4 research, using the existing event ledger and frozen public inputs."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import RunId
from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.research.validation.cat_replay import replay_cat
from scripts.export_alpha_v4_audit_bundle import digest, git
from scripts.run_alpha_v4_audit import (
    ROOT,
    SYMBOLS,
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
            expected = read_json(BASELINE / "aggregation_manifest.json")[
                "source_sha256"
            ]
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


def reproduce(output: Path) -> None:
    config = read_json(output / "audit_manifest.json")
    original = read_json(BASELINE / "run_manifest.json")
    folder = output / "baseline"
    if folder.exists():
        raise FileExistsError("baseline evidence already exists")
    folder.mkdir()
    expected = {
        name: pl.read_parquet(BASELINE / f"{name}.parquet").filter(pl.col("level") == "A1")
        for name in ("orders", "fills", "mtm_equity")
    }
    transitions = pl.read_parquet(BASELINE / "cash_transitions.parquet")
    checks: list[dict[str, Any]] = []
    collection = trial_collections()
    traces: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        source, market, bars, features, _, _, folds, indices, trend = inputs(symbol)
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
                gate_policy=EconomicGatePolicy.model_validate(config["gate"]),
                market_spec=market,
            )
            for name, rows in (("orders", result.orders), ("fills", result.fills)):
                prior = expected[name].filter(
                    (pl.col("symbol") == symbol) & (pl.col("fold_id") == fold.fold_id)
                )
                if [json.loads(p) for p in prior["payload_json"]] != [
                    r.model_dump(mode="json") for r in rows
                ]:
                    raise ValueError(f"A1 exact {name} identity/payload mismatch {symbol}/{fold.fold_id}")
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
            prior_equity = expected["mtm_equity"].filter(
                (pl.col("symbol") == symbol) & (pl.col("fold_id") == fold.fold_id)
            ).to_dicts()
            actual = result.equity_curve
            if len(actual) != len(prior_equity) or any(
                p.time != r["time"]
                or any(getattr(p, k) != Decimal(r[k]) for k in ("equity", "cash", "position_value"))
                for p, r in zip(actual, prior_equity, strict=True)
            ):
                raise ValueError("A1 complete MTM differs")
            checks.append({"symbol": symbol, "fold_id": fold.fold_id, "status": "PASS", "orders": len(result.orders), "fills": len(result.fills), "mtm_points": len(actual), "final_cash": str(cash)})
            counts = {name: len(rows) for name, rows in collection.items()}
            save_result(collection, result, fold, "F0")
            for name, rows in collection.items():
                for row in rows[counts[name]:]:
                    row["symbol"] = symbol
            traces.extend({"arm": "F0", "fold_id": fold.fold_id, **r} for r in trace)
    for name, rows in collection.items():
        table(folder / f"{name}.parquet", rows)
    table(folder / "decision_trace.parquet", traces)
    write_json(output / "baseline_reproduction.json", {"status": "PASS", "exact_order_and_fill_identity": True, "complete_mtm_and_cash_chain": True, "partitions": checks})
    print("A1 exact reproduction PASS: 70 partitions", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "baseline"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    (preregister if args.command == "register" else reproduce)(args.output.resolve())
