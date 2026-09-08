"""Summarize sealed multi-asset paths; this command never fits a model or creates orders."""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from aegisquant.backtest.models import EquityPoint
from aegisquant.research.validation.multi_asset import combine_independent_sleeves
from aegisquant.research.validation.paired_bootstrap import (
    FloatArray,
    holm_adjust,
    paired_block_bootstrap,
)
from scripts.run_alpha_v4_multi_asset import point_from_row, read_json
from scripts.run_alpha_v4_walkforward import digest, path_metrics, table, write_json

PORTFOLIO = "EQUAL_FIVE"
NAMES = {
    "B0": "现金",
    "B1": "每季买入持有",
    "B3": "透明趋势",
    "B4": "趋势＋动态门槛",
    "B5": "XGBoost 过滤",
    "B6": "XGBoost＋成本门槛",
    "B7": "XGBoost＋波动率仓位",
    "LIGHTGBM": "LightGBM 过滤",
    "ELASTIC_NET": "Elastic Net 过滤",
}


def returns(curve: tuple[EquityPoint, ...]) -> FloatArray:
    values = np.asarray([float(p.equity) for p in curve], dtype=np.float64)
    return values[1:] / values[:-1] - 1


def summarize(parent: Path) -> None:
    manifest = read_json(parent / "run_manifest.json")
    policy = manifest["policy"]
    symbols: list[str] = policy["symbols"]
    levels: list[str] = policy["levels"]
    scenarios = [f"cost_{cost}" for cost in policy["cost_multipliers"]]
    output = parent / "summary"
    output.mkdir(exist_ok=True)
    inputs: dict[str, str] = {"run_manifest.json": digest(parent / "run_manifest.json")}
    asset_status = {
        symbol: read_json(parent / symbol / "asset_manifest.json") for symbol in symbols
    }
    inputs.update(
        {
            f"{symbol}/asset_manifest.json": digest(parent / symbol / "asset_manifest.json")
            for symbol in symbols
        }
    )
    if any(
        row["status"] != "COMPLETED" or row["completed_folds"] != 14
        for row in asset_status.values()
    ):
        raise ValueError("all five assets and 14 preregistered folds must be completed")
    folders = sorted((parent / symbols[0]).glob("*/completion.json"))
    if len(folders) != 14:
        raise ValueError("the completed fold set must contain all 14 calendar tests")
    btc_coverage_path = parent.parent / "alpha_v4/walkforward/fold_manifest.parquet"
    inputs["../alpha_v4/walkforward/fold_manifest.parquet"] = digest(btc_coverage_path)
    btc_coverage = {
        row["fold_id"]: {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in row.items()
        }
        for row in pl.read_parquet(btc_coverage_path).to_dicts()
    }
    paths: dict[tuple[str, str, str], list[FloatArray]] = {}
    fold_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    attribution_checks: list[dict[str, Any]] = []
    portfolio_paths: list[dict[str, Any]] = []
    counts: list[dict[str, Any]] = []
    endpoint_residual = Decimal("0")
    for completed in folders:
        fold_id = completed.parent.name
        frames: dict[str, pl.DataFrame] = {}
        summaries: dict[str, pl.DataFrame] = {}
        for symbol in symbols:
            folder = parent / symbol / fold_id
            seal = read_json(folder / "completion.json")
            for name, value in seal["files"].items():
                path = folder / name
                if digest(path) != value:
                    raise ValueError(f"sealed asset evidence changed: {path}")
                inputs[path.relative_to(parent).as_posix()] = value
            frames[symbol] = pl.read_parquet(folder / "mtm_equity.parquet")
            summaries[symbol] = pl.read_parquet(folder / "fold_stability.parquet")
            counts.append(
                {
                    **(btc_coverage[fold_id] if symbol == "BTCUSDT" else {}),
                    **read_json(folder / "fold_manifest.json"),
                    "symbol": symbol,
                }
            )
            terminal = pl.read_parquet(folder / "terminal_attribution.parquet")
            if terminal.height:
                for row in terminal.to_dicts():
                    with localcontext() as context:
                        context.prec = 100
                        # Verify the saved full ledger identity independently at Decimal precision 100.
                        net = Decimal(row["gross_trading_pnl"])
                        for key in (
                            "trading_fees",
                            "spread_cost",
                            "slippage_cost",
                            "impact_cost",
                            "borrow_interest",
                            "settlement_fees",
                            "liquidation_penalties",
                        ):
                            net -= Decimal(row[key])
                        net -= Decimal(row["funding"])
                        residual = abs(net - Decimal(row["net_pnl"]))
                    if residual > Decimal("1e-8"):
                        raise ValueError("saved multi-asset cost identity failed")
                    attribution_checks.append(
                        {
                            "symbol": symbol,
                            "fold_id": fold_id,
                            "level": row["level"],
                            "scenario": row["scenario"],
                            "absolute_residual": residual,
                        }
                    )
        fold = read_json(parent / symbols[0] / fold_id / "fold_manifest.json")
        start, end = (
            datetime.fromisoformat(fold["test_start"]),
            datetime.fromisoformat(fold["test_end"]),
        )
        expected_count = int((end - start).total_seconds() / 14400) + 1
        for level in levels:
            for scenario in scenarios:
                match = (pl.col("level") == level) & (pl.col("scenario") == scenario)
                curves = {
                    symbol: tuple(
                        point_from_row(row)
                        for row in frames[symbol].filter(match).sort("time").to_dicts()
                    )
                    for symbol in symbols
                }
                for symbol, curve in curves.items():
                    if (
                        len(curve) != expected_count
                        or curve[0].time != start
                        or curve[-1].time != end
                    ):
                        raise ValueError(
                            "a sleeve does not cover the complete shared reporting clock"
                        )
                    if curve[0].equity != Decimal("10000") or curve[-1].position_value != 0:
                        raise ValueError(
                            "every fold requires an equal funded start and costed flat end"
                        )
                    row = summaries[symbol].filter(match).to_dicts()
                    if len(row) != 1:
                        raise ValueError("missing or duplicate asset fold summary")
                    endpoint_residual = max(
                        endpoint_residual,
                        abs(curve[-1].equity - Decimal(row[0]["mtm_final_equity"])),
                    )
                    if endpoint_residual > Decimal("1e-8"):
                        raise ValueError("saved equity path endpoint differs from ledger summary")
                    fold_rows.append({"symbol": symbol, **row[0]})
                    paths.setdefault((symbol, level, scenario), []).append(returns(curve))
                combined = combine_independent_sleeves(curves)
                portfolio_returns = returns(combined)
                paths.setdefault((PORTFOLIO, level, scenario), []).append(portfolio_returns)
                portfolio_paths.extend(
                    {
                        "fold_id": fold_id,
                        "level": level,
                        "scenario": scenario,
                        **point.model_dump(mode="python"),
                    }
                    for point in combined
                )
                constituent = [summaries[symbol].filter(match).to_dicts()[0] for symbol in symbols]
                fold_rows.append(
                    {
                        "symbol": PORTFOLIO,
                        "fold_id": fold_id,
                        "level": level,
                        "scenario": scenario,
                        **path_metrics(portfolio_returns),
                        "mtm_final_equity": str(combined[-1].equity),
                        "forced_close_final_equity": str(combined[-1].equity),
                        "forced_close_status": "NO_POSITION",
                        "closed_trade_count": sum(row["closed_trade_count"] for row in constituent),
                        "total_cost": sum(row["total_cost"] for row in constituent),
                        "same_fill_topology": all(
                            row["same_fill_topology"] is not False for row in constituent
                        ),
                        "rejections": sum(row["rejections"] for row in constituent),
                    }
                )
                if scenario == "cost_1":
                    equity_rows.extend(
                        {
                            "fold_id": fold_id,
                            "symbol": symbol,
                            "level": level,
                            "time": point.time,
                            "equity": point.equity,
                        }
                        for symbol, curve in {**curves, PORTFOLIO: combined}.items()
                        for point in curve
                    )
    table(output / "fold_stability.parquet", fold_rows)
    table(output / "portfolio_mtm_equity.parquet", portfolio_paths)
    table(output / "base_equity.parquet", equity_rows)
    table(output / "sample_coverage.parquet", counts)
    table(output / "cost_identity.parquet", attribution_checks)
    concatenated = {key: np.concatenate(value) for key, value in paths.items()}
    summaries_out: list[dict[str, Any]] = []
    fold_frame = pl.DataFrame(fold_rows, infer_schema_length=None)
    for (symbol, level, scenario), changes in concatenated.items():
        frame = fold_frame.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("level") == level)
            & (pl.col("scenario") == scenario)
        )
        summaries_out.append(
            {
                "symbol": symbol,
                "level": level,
                "scenario": scenario,
                **path_metrics(changes),
                "winning_folds": sum(value > 0 for value in frame["net_compound_return"]),
                "fold_count": frame.height,
                "closed_trade_count": frame["closed_trade_count"].sum(),
                "rejections": frame["rejections"].sum(),
                "changed_fill_folds": sum(value is False for value in frame["same_fill_topology"]),
            }
        )
    table(output / "aggregate_stress.parquet", summaries_out)
    bootstrap_keys = [
        (symbol, level, "cost_1") for symbol in [*symbols, PORTFOLIO] for level in levels
    ]
    bootstrap = paired_block_bootstrap(
        np.column_stack([concatenated[key] for key in bootstrap_keys]),
        repetitions=policy["bootstrap_repetitions"],
        block_bars=policy["bootstrap_block_bars"],
        seed=policy["seed"],
    )
    uncertainty: list[dict[str, Any]] = []
    comparisons: dict[str, dict[str, float]] = {}
    for i, (symbol, level, _) in enumerate(bootstrap_keys):
        low, high = np.quantile(bootstrap.compound_returns[:, i], (0.025, 0.975))
        uncertainty.append(
            {"symbol": symbol, "level": level, "ci95_lower": float(low), "ci95_upper": float(high)}
        )
        for reference in ("B0", "B1", "B3"):
            if level != reference:
                j = bootstrap_keys.index((symbol, reference, "cost_1"))
                comparisons[f"{symbol}/{level}_vs_{reference}"] = bootstrap.difference(i, j)
        if symbol == PORTFOLIO and level != "B0":
            j = bootstrap_keys.index(("BTCUSDT", level, "cost_1"))
            comparisons[f"{PORTFOLIO}/{level}_vs_BTC_same_strategy"] = bootstrap.difference(i, j)
    adjusted = holm_adjust(
        {key: value["one_sided_mean_p_value"] for key, value in comparisons.items()}
    )
    for key, value in comparisons.items():
        value["holm_adjusted_p_value"] = adjusted[key]
    write_json(
        output / "bootstrap_results.json",
        {
            "repetitions": bootstrap.repetitions,
            "block_bars": bootstrap.block_bars,
            "column_order": [list(key[:2]) for key in bootstrap_keys],
            "return_intervals": uncertainty,
            "comparisons": comparisons,
            "holm_comparison_count": len(comparisons),
            "reality_check_p_value": bootstrap.reality_check_p_value,
            "limitation": "Conditional circular block inference on fixed survivor assets; no new final holdout or full matched-random test.",
        },
    )
    table(output / "return_intervals.parquet", uncertainty)
    write_json(
        output / "validation.json",
        {
            "all_assets_complete": True,
            "assets": asset_status,
            "asset_fold_scenarios": len(symbols) * len(folders) * len(levels) * len(scenarios),
            "portfolio_fold_scenarios": len(folders) * len(levels) * len(scenarios),
            "new_model_fits": sum(row["actual_model_fits"] for row in asset_status.values()),
            "planned_new_fit_slots": sum(row["planned_fit_slots"] for row in asset_status.values()),
            "independent_saved_cost_identity_checks": len(attribution_checks),
            "maximum_cost_identity_residual": str(
                max(row["absolute_residual"] for row in attribution_checks)
            ),
            "maximum_path_endpoint_residual": str(endpoint_residual),
            "all_fold_end_positions_flat": True,
            "shared_complete_clock": True,
            "btc_original_base_reused": True,
            "btc_stress_endpoints_match_original": True,
            "btc_stress_manifest": "../btc_execution_manifest.json",
            "btc_execution_code_difference": "Before non-BTC fits, a typing.cast annotation was added to the exact AssetId decoder; runtime calculation unchanged.",
            "production_ml_enabled": False,
            "live_trading": False,
            "final_holdout_access_count": 0,
        },
    )
    write_json(
        output / "summary_manifest.json",
        {
            "input_sha256": inputs,
            "summary_code_sha256": digest(Path(__file__).resolve()),
            "output_sha256": {
                p.name: digest(p)
                for p in sorted(output.iterdir())
                if p.name != "summary_manifest.json" and p.suffix in (".parquet", ".json")
            },
        },
    )
    print(
        pl.DataFrame(summaries_out)
        .filter((pl.col("symbol") == PORTFOLIO) & (pl.col("scenario") == "cost_1"))
        .select(
            "level",
            "net_compound_return",
            "sharpe",
            "maximum_drawdown",
            "winning_folds",
            "closed_trade_count",
        )
        .write_csv()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    parent = Path(__file__).resolve().parents[1] / "artifacts/alpha_v4_multi_asset"
    if args.check:
        summary = read_json(parent / "summary/summary_manifest.json")
        if summary["summary_code_sha256"] != digest(Path(__file__).resolve()):
            raise ValueError("summary calculation code changed")
        for name, value in summary["input_sha256"].items():
            if digest(parent / name) != value:
                raise ValueError(f"summary input changed: {name}")
        for name, value in summary["output_sha256"].items():
            if digest(parent / "summary" / name) != value:
                raise ValueError(f"summary output changed: {name}")
        print("multi-asset summary inputs and outputs verified without model fitting")
    else:
        summarize(parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
