"""Replay the current fixed R2 policies with continuous funded cash and frozen forecasts."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from aegisquant.backtest.models import ClosedTrade
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import RunId, StrategyVersionId
from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.research.validation.cat_replay import replay_cat
from scripts.export_alpha_v4_audit_bundle import check, digest, git
from scripts.run_alpha_v4_audit import (
    OUTPUT as PREVIOUS,
)
from scripts.run_alpha_v4_audit import (
    ROOT,
    SYMBOLS,
    frozen,
    inputs,
    make_spec,
    read_json,
    save_result,
    trial_collections,
)
from scripts.run_alpha_v4_audit_r2 import OUTPUT as R2
from scripts.run_alpha_v4_audit_r2 import components, policies
from scripts.run_alpha_v4_walkforward import path_metrics, table, write_json

ARMS = ("CASH", "A1", "A3", "A7")
LABELS = {
    "CASH": "当前生产配置：现金",
    "A1": "风险控制趋势（无 ML）",
    "A3": "ML 入场与成本过滤",
    "A7": "完整研究版本（概率/分位/置信仓位）",
}


def summarize(output: Path) -> dict[str, Any]:
    equity = pl.read_parquet(output / "mtm_equity.parquet")
    duplicate_groups = equity.group_by("level", "symbol", "time").agg(
        pl.col("equity"), pl.col("cash"), pl.col("position_value")
    )
    for row in duplicate_groups.filter(pl.col("equity").list.len() > 1).to_dicts():
        for key in ("equity", "cash", "position_value"):
            if len({Decimal(v) for v in row[key]}) != 1:
                raise ValueError("quarter boundary contains conflicting account balances")
    equity = equity.sort("fold_id").unique(["level", "symbol", "time"], keep="last")
    equity = equity.with_columns(
        *(pl.col(k).cast(pl.Float64) for k in ("equity", "cash", "position_value"))
    ).sort("level", "symbol", "time")
    combined = (
        equity.group_by("level", "time")
        .agg(
            pl.col("equity").sum(),
            pl.col("cash").sum(),
            pl.col("position_value").sum(),
            pl.col("symbol").sort().alias("symbols"),
        )
        .sort("level", "time")
    )
    if any(symbols != sorted(SYMBOLS) for symbols in combined["symbols"].to_list()):
        raise ValueError("portfolio clock does not contain exactly the five funded sleeves")
    transitions = pl.read_parquet(output / "cash_transitions.parquet")
    if transitions.height != len(ARMS) * len(SYMBOLS) * 14:
        raise ValueError("continuous backtest is missing a funded quarter partition")
    fold_statistics = pl.read_parquet(output / "fold_stability.parquet")
    trades = pl.read_parquet(output / "trades.parquet").to_dicts()
    summaries: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    annual: list[dict[str, Any]] = []
    quarters: list[dict[str, Any]] = []
    for arm in ARMS:
        local = transitions.filter(pl.col("arm") == arm).sort("fold_id", "symbol")
        terminal = Decimal("0")
        for symbol in SYMBOLS:
            chain = local.filter(pl.col("symbol") == symbol).to_dicts()
            cash = Decimal("10000")
            for row in chain:
                if (
                    Decimal(row["initial_cash"]) != cash
                    or row["external_flows"] != "0"
                    or not row["flat_after_costed_exit"]
                ):
                    raise ValueError("continuous cash chain contains a reset or free transfer")
                cash = Decimal(row["final_cash"])
            terminal += cash
            path = equity.filter((pl.col("level") == arm) & (pl.col("symbol") == symbol))
            values = path["equity"].to_numpy()
            if values[0] != 10000 or not np.isclose(values[-1], float(cash), atol=1e-8, rtol=0):
                raise ValueError("asset MTM endpoints disagree with cash ledger")
            assets.append(
                {
                    "arm": arm,
                    "symbol": symbol,
                    "initial_cash": 10000,
                    "final_cash": str(cash),
                    **path_metrics(values[1:] / values[:-1] - 1),
                }
            )
        frame = combined.filter(pl.col("level") == arm)
        values = frame["equity"].to_numpy()
        if values[0] != 50000 or not np.isclose(values[-1], float(terminal), atol=1e-8, rtol=0):
            raise ValueError("portfolio MTM endpoints disagree with funded cash")
        changes = values[1:] / values[:-1] - 1
        outcomes = [
            ClosedTrade.model_validate_json(r["payload_json"]) for r in trades if r["level"] == arm
        ]
        if (
            len(outcomes)
            != fold_statistics.filter(pl.col("level") == arm)["closed_trade_count"].sum()
        ):
            raise ValueError("closed trade rows disagree with engine trade counts")
        quarter_results: list[float] = []
        for (fold,), part in local.partition_by("fold_id", as_dict=True).items():
            initial = sum(Decimal(v) for v in part["initial_cash"].to_list())
            final = sum(Decimal(v) for v in part["final_cash"].to_list())
            value = float(final / initial - 1)
            quarter_results.append(value)
            quarters.append({"arm": arm, "fold_id": fold, "net_return": value})
        summaries.append(
            {
                "arm": arm,
                "label": LABELS[arm],
                "initial_cash": "50000",
                "final_cash": str(terminal),
                "net_profit": str(terminal - 50000),
                **path_metrics(changes),
                "closed_trades": len(outcomes),
                "win_rate": sum(t.net_pnl > 0 for t in outcomes) / len(outcomes)
                if outcomes
                else None,
                "mean_holding_days": float(
                    sum((t.holding_seconds for t in outcomes), Decimal("0")) / len(outcomes) / 86400
                )
                if outcomes
                else None,
                "total_cost": str(sum(Decimal(v) for v in local["total_cost"].to_list())),
                "orders": int(local["orders"].sum()),
                "fills": int(local["fills"].sum()),
                "rejections": int(local["rejections"].sum()),
                "positive_quarters": sum(v > 0 for v in quarter_results),
                "capital_weighted_exposure": float(
                    np.mean(frame["position_value"].to_numpy() / values)
                ),
                "maximum_actual_participation": max(
                    float(v) for v in local["maximum_actual_participation"].to_list()
                ),
            }
        )
        previous = 50000.0
        for (year,), part in frame.with_columns(pl.col("time").dt.year().alias("year")).group_by(
            "year", maintain_order=True
        ):
            last = float(part["equity"][-1])
            annual.append({"arm": arm, "year": year, "net_return": last / previous - 1})
            previous = last
    cash_summary = summaries[0]
    if Decimal(cash_summary["final_cash"]) != 50000 or cash_summary["orders"] != 0:
        raise ValueError("CASH policy must preserve initial cash and submit no orders")
    table(output / "portfolio_equity.parquet", combined.to_dicts())
    table(output / "quarter_returns.parquet", quarters)
    result = {
        "status": "COMPLETE_RESEARCH_BACKTEST_NOT_TRADING_ADMISSION",
        "test_start": "2022-04-01T00:00:00Z",
        "test_end_exclusive": "2025-10-01T00:00:00Z",
        "symbols": SYMBOLS,
        "accounting": "actual continuous cash, paid quarterly liquidation, no external flows or reweighting",
        "new_model_fits": 0,
        "new_calibration_fits": 0,
        "final_holdout_access_count": 0,
        "portfolio": summaries,
        "assets": assets,
        "year_returns": annual,
        "cash_transitions_verified": transitions.height,
        "maximum_cost_identity_residual": str(
            max(abs(Decimal(v)) for v in transitions["cost_identity_residual"].to_list())
        ),
    }
    write_json(output / "results.json", result)
    return result


def run(output: Path) -> None:
    if output.exists():
        raise FileExistsError("backtest output already exists; preserve the recorded run")
    if git(ROOT, "branch", "--show-current") != "main":
        raise ValueError("backtest requires the existing main checkout")
    original = check(ROOT, PREVIOUS / "before")
    registered = read_json(R2 / "preregistration.json")
    for name, expected in registered["source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("current implementation differs from the verified R2 policy")
    source_hashes = {
        **registered["source_sha256"],
        "scripts/run_current_system_backtest.py": digest(Path(__file__)),
    }
    config = {
        "version": "current-r2-continuous-backtest-v1",
        "registered_at": datetime.now(UTC).isoformat(),
        "source_head": git(ROOT, "rev-parse", "HEAD"),
        "source_sha256": source_hashes,
        "source_r2_manifest": digest(R2 / "preregistration.json"),
        "source_evidence_check": original,
        "arms": {k: policies()[k].model_dump(mode="json") for k in ARMS if k != "CASH"},
        "gate": registered["gate"],
        "initial_cash_per_asset": "10000",
        "test_start": registered["test_start"],
        "test_end_exclusive": registered["test_end_exclusive"],
        "symbols": SYMBOLS,
        "accounting": "actual continuous sleeve cash with paid quarterly exits; no free reweighting",
        "forecast_policy": "reuse original mature walk-forward XGBoost forecasts; no fitting or tuning",
        "evidence_tier": "PREVIOUSLY_USED_DEVELOPMENT_HISTORY",
        "production_policy": "CASH",
        "production_ml_enabled": False,
        "live_trading": False,
        "order_submission_enabled": False,
    }
    config["sha256"] = canonical_sha256(config)
    output.mkdir(parents=True)
    write_json(output / "run_manifest.json", config)
    collection = trial_collections()
    transitions: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    capital = {arm: {symbol: Decimal("10000") for symbol in SYMBOLS} for arm in ARMS}
    gate = EconomicGatePolicy.model_validate_json(json.dumps(config["gate"]))
    for symbol in SYMBOLS:
        source, market, bars, features, _, _, folds, indices, trend = inputs(symbol)
        for number, fold in enumerate(folds, 1):
            print(f"{symbol} {number}/14 {fold.fold_id}: CASH / A1 / A3 / A7", flush=True)
            values, _, meta = frozen(symbol, fold)
            evidence_hash = digest(
                PREVIOUS / symbol / fold.fold_id / "forecast_diagnostics.parquet"
            )
            forecasts = {
                t: components(v, meta, evidence_hash) for t, v in values.get("XGBOOST", {}).items()
            }
            allowed = set(fold.test_indices)
            for arm in ARMS:
                initial = capital[arm][symbol]
                spec = make_spec(symbol, fold, arm, source, config, initial).model_copy(
                    update={
                        "run_id": RunId(f"current-r2-{symbol}-{fold.fold_id}-{arm}"),
                        "strategy_version_id": StrategyVersionId("current-r2-fixed-replay-v1"),
                        "code_sha256": digest(Path(__file__)),
                        "reproduction_command": "python -m scripts.run_current_system_backtest --output <new-version-directory>",
                    }
                )
                result, trace = replay_cat(
                    root=ROOT,
                    spec=spec,
                    bars=tuple(b for b in bars if fold.test_start <= b.event_time < fold.test_end),
                    features=features,
                    feature_indices=indices,
                    trend_by_time={t: v and indices[t] in allowed for t, v in trend.items()},
                    forecasts=forecasts if arm in {"A3", "A7"} else {},
                    level="B0" if arm == "CASH" else arm,
                    audit_policy=None if arm == "CASH" else policies()[arm],
                    gate_policy=gate,
                    market_spec=market,
                )
                final = result.mark_to_market_final_equity
                if final is None or result.positions[-1].quantity != 0:
                    raise ValueError("quarter transition requires a paid flat position")
                if abs(result.cost_identity_residual) > result.cost_identity_tolerance:
                    raise ValueError("backtest accounting identity failed")
                capital[arm][symbol] = final
                counts = {name: len(rows) for name, rows in collection.items()}
                save_result(collection, result, fold, arm)
                for name, rows in collection.items():
                    for row in rows[counts[name] :]:
                        row["symbol"] = symbol
                transitions.append(
                    {
                        "arm": arm,
                        "symbol": symbol,
                        "fold_id": fold.fold_id,
                        "initial_cash": str(initial),
                        "final_cash": str(final),
                        "external_flows": "0",
                        "flat_after_costed_exit": True,
                        "total_cost": str(
                            result.pnl_attribution[-1].gross_trading_pnl
                            - result.pnl_attribution[-1].net_pnl
                        ),
                        "orders": len(result.orders),
                        "fills": len(result.fills),
                        "rejections": sum(bool(o.rejection_code) for o in result.orders),
                        "maximum_actual_participation": str(
                            max(
                                (f.quantity.amount / f.available_liquidity for f in result.fills),
                                default=Decimal("0"),
                            )
                        ),
                        "cost_identity_residual": str(result.cost_identity_residual),
                    }
                )
                traces.extend(
                    {"arm": arm, "symbol": symbol, "fold_id": fold.fold_id, **row} for row in trace
                )
    for name, rows in collection.items():
        table(output / f"{name}.parquet", rows)
    table(output / "cash_transitions.parquet", transitions)
    table(output / "decision_trace.parquet", traces)
    result = summarize(output)
    write_json(
        output / "completion.json",
        {
            "status": result["status"],
            "files": {f.name: digest(f) for f in sorted(output.iterdir()) if f.is_file()},
        },
    )
    print(json.dumps(result["portfolio"], ensure_ascii=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
