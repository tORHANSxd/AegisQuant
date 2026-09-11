"""Audit saved R4/R5 ledgers. No data download, model fitting or candidate selection."""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl

from aegisquant.research.experiments.journal import ExperimentEventJournal, ExperimentEventType
from aegisquant.research.validation.experiment_registry import require_promotion_evidence
from aegisquant.research.validation.paired_bootstrap import (
    LOG_GROWTH_ESTIMAND,
    FloatArray,
    holm_adjust,
    paired_block_bootstrap,
)
from scripts.export_alpha_v4_audit_bundle import digest
from scripts.run_alpha_r4 import read_result
from scripts.run_alpha_v4_audit import SYMBOLS, read_json
from scripts.run_alpha_v4_walkforward import table, write_json
from scripts.run_alpha_v5_research import DEFAULT_OUTPUT, R4, verify_bindings
from scripts.summarize_alpha_r4 import automatic_block, fill_attribution, metrics, shadow_cost


def verify_trials(output: Path, manifest: dict[str, Any]) -> None:
    journal = ExperimentEventJournal(output / "experiment_events.jsonl")
    entries = journal.entries()
    if {e.event.run_id for e in entries} != set(manifest["planned_run_ids"]):
        raise ValueError("missing or undeclared experiment slots; do not omit failed trials")
    for run_id in manifest["planned_run_ids"]:
        last = journal.history(run_id)[-1]
        if last.event_type is not ExperimentEventType.SUCCEEDED:
            raise ValueError(f"incomplete or failed experiment: {run_id}")
        if "artifacts_sha256" not in last.details:
            expected = last.details.get("baseline_result_sha256")
            if digest(output / "baseline_reproduction.json") != expected:
                raise ValueError("baseline evidence hash changed")
            continue
        arm, symbol, cost = (str(last.details[k]) for k in ("arm", "symbol", "cost"))
        for name, expected in cast(dict[str, str], last.details["artifacts_sha256"]).items():
            if digest(output / "runs" / arm / symbol / cost / name) != expected:
                raise ValueError(f"saved run artifacts changed: {run_id}/{name}")


def collect(
    output: Path, manifest: dict[str, Any]
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    from decimal import Decimal

    equity: list[pl.DataFrame] = []
    fills: list[dict[str, Any]] = []
    sleeves: list[dict[str, Any]] = []
    shadow: list[dict[str, Any]] = []
    for trial in manifest["planned_runs"]:
        arm, symbol, cost = (trial[k] for k in ("arm", "symbol", "cost"))
        folder = output / "runs" / arm / symbol / cost
        result = read_result(folder)
        trace = pl.read_parquet(folder / "decision_trace.parquet").to_dicts()
        equity.append(pl.read_parquet(folder / "equity.parquet"))
        rows = fill_attribution(result, trace, arm, symbol)
        fills.extend({**r, "cost": cost} for r in rows)
        sleeves.append(
            {
                **trial,
                "final_equity": str(result.equity_curve[-1].equity),
                "cost_paid": str(sum((f.cost_breakdown.total for f in result.fills), Decimal("0"))),
                "traded_notional": str(
                    sum((f.cost_breakdown.gross_notional for f in result.fills), Decimal("0"))
                ),
                "fills": len(result.fills),
                "orders": len(result.orders),
                "rejections": sum(bool(o.rejection_code) for o in result.orders),
                "cost_identity_residual": str(result.cost_identity_residual),
                "terminal_quantity": str(result.positions[-1].quantity),
            }
        )
        if cost == "1":
            base_cost = sum((f.cost_breakdown.total for f in result.fills), Decimal("0"))
            for multiplier in ("1", "1.5", "2"):
                stressed = sum(
                    (shadow_cost(f, Decimal(multiplier)) for f in result.fills), Decimal("0")
                )
                if stressed + Decimal("1e-8") < base_cost:
                    raise ValueError("same-fill worse costs improved net wealth")
                shadow.append(
                    {
                        "arm": arm,
                        "symbol": symbol,
                        "cost": multiplier,
                        "final_equity": str(result.equity_curve[-1].equity + base_cost - stressed),
                        "total_cost": str(stressed),
                        "funded": False,
                    }
                )
    table(output / "sleeve_results.parquet", sleeves)
    table(output / "same_fill_cost_shadow.parquet", shadow)
    table(output / "execution_reason_attribution.parquet", fills)
    frame = pl.concat(equity).with_columns(
        *(pl.col(k).cast(pl.Float64) for k in ("equity", "cash", "position_value"))
    )
    combined = (
        frame.group_by("arm", "cost", "time")
        .agg(
            pl.col("equity").sum(),
            pl.col("cash").sum(),
            pl.col("position_value").sum(),
            pl.col("symbol").sort().alias("symbols"),
        )
        .sort("arm", "cost", "time")
    )
    if any(s != sorted(SYMBOLS) for s in combined["symbols"].to_list()):
        raise ValueError("portfolio is missing a funded sleeve or contains duplicate observations")
    legacy = (
        pl.read_parquet(R4 / "portfolio_equity.parquet")
        .filter((pl.col("mode") == "REDECIDE_FUNDED") & (pl.col("cost_multiplier") == "1"))
        .rename({"cost_multiplier": "cost"})
        .select(combined.columns)
    )
    combined = pl.concat([combined, legacy]).sort("arm", "cost", "time")
    table(output / "portfolio_equity.parquet", combined.to_dicts())
    legacy_sleeves = (
        pl.read_parquet(R4 / "sleeve_results.parquet")
        .filter((pl.col("mode") == "REDECIDE_FUNDED") & (pl.col("cost_multiplier") == "1"))
        .rename({"cost_multiplier": "cost", "total_cost": "cost_paid"})
    )
    totals = pl.concat([pl.DataFrame(sleeves), legacy_sleeves], how="diagonal_relaxed")
    attributes = pl.concat(
        [
            pl.DataFrame(fills),
            pl.read_parquet(R4 / "execution_reason_attribution.parquet").with_columns(
                pl.lit("1").alias("cost")
            ),
        ],
        how="diagonal_relaxed",
    )
    return combined, totals, attributes


def summarize(
    portfolio: pl.DataFrame, sleeves: pl.DataFrame, fills: pl.DataFrame
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (arm, cost), frame in portfolio.partition_by("arm", "cost", as_dict=True).items():
        trial = sleeves.filter((pl.col("arm") == arm) & (pl.col("cost") == cost))
        attribution = fills.filter((pl.col("arm") == arm) & (pl.col("cost") == cost))
        ordinary = attribution.filter(
            pl.col("reason_primary").is_in(["ORDINARY_RISK_REDUCE", "ORDINARY_RISK_RESTORE"])
        )
        frame = frame.sort("time")
        quarter = (
            frame.with_columns(
                (pl.col("equity") / pl.col("equity").shift(1)).alias("gross_return"),
                (pl.col("time") - pl.duration(microseconds=1)).dt.year().alias("year"),
                (pl.col("time") - pl.duration(microseconds=1)).dt.quarter().alias("quarter"),
            )
            .filter(pl.col("gross_return").is_not_null())
            .group_by("year", "quarter")
            .agg((pl.col("gross_return").product() - 1).alias("return"))
        )
        rows.append(
            {
                "arm": arm,
                "cost": cost,
                **metrics(frame),
                "total_cost": float(trial["cost_paid"].cast(pl.Float64).sum()),
                "traded_notional": float(trial["traded_notional"].cast(pl.Float64).sum()),
                "fills": int(trial["fills"].sum()),
                "risk_resize_fills": ordinary.height,
                "resize_fill_share": ordinary.height / attribution.height
                if attribution.height
                else None,
                "quarter_count": quarter.height,
                "positive_quarter_fraction": float(np.mean(quarter["return"].to_numpy() > 0)),
                "median_quarter_return": float(np.median(quarter["return"].to_numpy())),
            }
        )
    return rows


def paired_statistics(portfolio: pl.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    selected = portfolio.filter((pl.col("cost") == "1") & (pl.col("time").dt.hour() == 0))
    frame = selected.pivot(on="arm", index="time", values="equity").sort("time")
    if frame.select(pl.any_horizontal(pl.all().is_null())).to_series().any():
        raise ValueError("benchmark comparison requires the same complete daily clock")
    frame = frame.with_columns(
        pl.lit(float(config["initial_cash_per_symbol"]) * len(SYMBOLS)).alias("CASH")
    )
    arms = sorted(c for c in frame.columns if c != "time")
    wealth = frame.select(arms).to_numpy()
    returns = wealth[1:] / wealth[:-1] - 1
    block = max(
        2,
        min(
            len(returns) // 4,
            math.ceil(
                max(
                    automatic_block(series)
                    for i in range(len(arms))
                    for series in (returns[:, i], returns[:, i] ** 2)
                )
            ),
        ),
    )
    draw = paired_block_bootstrap(
        returns,
        repetitions=config["statistics"]["repetitions"],
        block_bars=block,
        seed=config["statistics"]["seed"],
    )
    comparisons: dict[str, Any] = {}
    for name in config["statistics"]["comparisons"]:
        left, right = name.split("-")
        i, j = arms.index(left), arms.index(right)
        comparisons[name] = {
            **draw.difference(i, j),
            "terminal_wealth_difference_usdt": float(wealth[-1, i] - wealth[-1, j]),
        }
    adjusted = holm_adjust(
        {name: row["one_sided_mean_p_value"] for name, row in comparisons.items()}
    )
    for name, value in adjusted.items():
        comparisons[name]["holm_adjusted_p_value"] = value
    return {
        "evidence_tier": "DEVELOPMENT_UNCERTAINTY_ONLY",
        "block_days": block,
        "comparisons": comparisons,
        "dsr": None,
        "pbo": None,
        "dsr_pbo_status": "INSUFFICIENT_COMPLETE_HISTORICAL_INDEPENDENT_TRIAL_HISTORY",
    }


def report(output: Path) -> dict[str, Any]:
    manifest = verify_bindings(output)
    verify_trials(output, manifest)
    baseline = read_json(output / "baseline_reproduction.json")
    if baseline["status"] != "PASS" or len(baseline["partitions"]) != 70:
        raise ValueError("complete exact baseline reproduction is required")
    config = manifest["config"]
    portfolio, sleeves, fills = collect(output, manifest)
    summary = summarize(portfolio, sleeves, fills)
    stats = paired_statistics(portfolio, config)
    indexed = {(r["arm"], r["cost"]): r for r in summary}
    f0, g1 = indexed["F0", "1"], indexed["G1", "1"]
    targets = config["churn_acceptance"]
    checks = {
        "resize_fill_share_le_50pct": g1["resize_fill_share"] is not None
        and g1["resize_fill_share"] <= targets["maximum_resize_fill_share"],
        "turnover_reduction_ge_40pct": g1["traded_notional"]
        <= f0["traded_notional"] * targets["maximum_turnover_relative_to_f0"],
        "cost_reduction_ge_30pct": g1["total_cost"]
        <= f0["total_cost"] * targets["maximum_cost_relative_to_f0"],
        "cagr_degradation_le_1pp": g1["cagr"]
        >= f0["cagr"] - targets["maximum_cagr_degradation_pp"] / 100,
        "mdd_degradation_le_2pp": g1["maximum_drawdown"]
        <= f0["maximum_drawdown"] + targets["maximum_mdd_degradation_pp"] / 100,
    }
    admission_reason = None
    try:
        require_promotion_evidence(
            point_in_time_universe=False, verified_execution=False, unused_holdout_months=0
        )
    except PermissionError as error:
        admission_reason = str(error)
    root = fills.filter(pl.col("arm") == "F0")
    reasons = root.group_by("reason_primary").agg(
        pl.len().alias("fills"),
        pl.col("filled_notional").cast(pl.Float64).sum().alias("notional"),
        pl.col("total_cost").cast(pl.Float64).sum().alias("cost"),
    )
    result = {
        "generation": config["generation"],
        "scope": config["scope"],
        "research_conclusion": "NO_PROVEN_ALPHA",
        "production_policy": "CASH",
        "primary_candidate": "G1",
        "candidate_selected": False,
        "production_ml_enabled": False,
        "paper_trading_admitted": False,
        "live_trading": False,
        "order_submission_enabled": False,
        "new_model_fits": 0,
        "new_calibration_fits": 0,
        "final_holdout_accesses": 0,
        "baseline_partitions": len(baseline["partitions"]),
        "continuous_engine_runs": len(manifest["planned_runs"]),
        "original_f3_sleeves_reproduced": len(SYMBOLS),
        "f0_resize_fill_share": f0["resize_fill_share"],
        "f0_reason_attribution": reasons.to_dicts(),
        "churn_checks": checks,
        "churn_all_passed": all(checks.values()),
        "neighbor_scope": "3/5/10d smoothing and 24/48/72h review only; no result-based parameter selection",
        "summary": summary,
        "statistics": stats,
        "admission_block": admission_reason,
        "remaining_stages": [
            "verified PIT membership and liquidity history",
            "real fee/rule/orderbook/latency evidence",
            "portfolio covariance risk and capacity/empirical execution tests",
            "episode labels, nested CV and OOF uncertainty",
            "benchmark superiority and complete trial-history statistics",
            "candidate freeze and unused >=12-month holdout",
            "separately admitted shadow/paper/live review",
        ],
        "ml_missed_opportunity_evidence": str(R4 / "go_no_go.md"),
        "limitations": [
            "all observations previously used for development",
            "fixed five surviving assets",
            "risk-benefit and execution costs remain declared proxies",
            "no new PIT-wide evaluation",
            "first-batch diagnostics do not satisfy the full taskbook acceptance chain",
        ],
    }
    write_json(output / "root_cause_audit.json", result)
    write_json(output / "paired_statistics.json", stats)
    lines = [
        "# 深度审计任务书首批修改与验证",
        "",
        "结论：**NO_PROVEN_ALPHA；生产 CASH，ML/纸面/实盘/订单继续关闭。**",
        "",
        "范围：研究有效性与调仓 churn。模型重训、最终留出及后续交易准入未执行。",
        "",
        "已冻结独立 generation、代码/任务书/数据哈希及全部试验槽位；复用追加式实验日志、PIT 快照和原有单次留出保险库。开发入口在读取行情前校验实际路径、哈希、OHLCV 和绝对日期。",
        "",
        "真实历史：2022-04-01 至 2025-10-01，五币各 10,000 USDT。新入口复现原 A1 的 70 个季度分区及原 F3 的 5 个连续 sleeve，逐单/成交/完整 MTM 对照。",
        "",
        "G1：5 天目标平滑、48 小时复核、加仓/减仓半宽 20%/10%、3% 绝对缓冲与最小调仓权重、50 USDT 最小调仓。按权益比例比较实际舍入增量成本与复核期方差偏离损失下降；该收益量是风险效用代理，不代表预测 alpha。",
        "",
        "| 配置 | 成本 | 期末净值 USDT | CAGR | Sharpe | 最大回撤 | 成本 USDT | 成交 | resize 占比 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        if row["arm"] in {"F0", "F3", "F5"} or row["arm"].startswith("G1"):
            sharpe = f"{row['sharpe']:.3f}" if row["sharpe"] is not None else "N/A"
            share = (
                f"{row['resize_fill_share']:.1%}" if row["resize_fill_share"] is not None else "N/A"
            )
            lines.append(
                f"| {row['arm']} | {row['cost']}× | {row['final_equity']:,.2f} | {row['cagr']:.2%} | {sharpe} | {row['maximum_drawdown']:.2%} | {row['total_cost']:,.2f} | {row['fills']} | {share} |"
            )
    lines += ["", "首批 churn 验收：", ""] + [
        f"- {key}：{'PASS' if passed else 'FAIL'}" for key, passed in checks.items()
    ]
    lines += [
        "",
        f"配对统计使用共同日历、{stats['block_days']} 天 block、10,000 次 bootstrap 和 Holm 校正；所有比较与失败结果保留于 paired_statistics.json。相邻配置只验证平滑/复核参数，不重新选择主候选。G1_PASSIVE 使用相同新风险/执行规则和持续多头基准信号。",
        "",
        "PIT 选样组件已覆盖上市/退市修订可用时间、30 天成交额、最小历史和过期数据；真实 PIT membership/liquidity 历史尚缺，本批仍明确是固定存活五币开发诊断。",
        "",
        "完整未使用十二个月留出、历史真实执行证据和独立试验历史仍缺。DSR/PBO 返回证据不足；本批不产生生产晋级证据。后续组合风险、成本实证、ML 标签/OOF/nested CV 仍是未完成阶段。",
        "",
        "验证执行记录见 validation/；研究回放完成与测试通过均不构成交易授权。",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def benchmark_factorial_attribution(
    simple_net_returns: FloatArray, cells: Sequence[tuple[str, str]]
) -> dict[str, Any]:
    """Descriptive balanced 2x3 decomposition; no fit, resampling, prices or file writes."""
    signals = ("ALWAYS_HOLD", "TREND_10_40")
    controls = ("G0", "G1", "FIXED_QTY")
    expected = {(signal, control) for signal in signals for control in controls}
    if (
        len(cells) != 6
        or set(cells) != expected
        or simple_net_returns.ndim != 2
        or simple_net_returns.shape[1] != 6
        or not len(simple_net_returns)
        or not np.all(np.isfinite(simple_net_returns))
        or np.any(simple_net_returns <= -1)
    ):
        raise ValueError("B3 attribution requires six complete aligned 2x3 net-return cells")
    means = dict(zip(cells, map(float, np.mean(np.log1p(simple_net_returns), axis=0)), strict=True))
    grand = math.fsum(means.values()) / 6
    signal_effects = {
        signal: math.fsum(means[signal, control] for control in controls) / 3 - grand
        for signal in signals
    }
    control_effects = {
        control: math.fsum(means[signal, control] for signal in signals) / 2 - grand
        for control in controls
    }
    return {
        "kind": "DESCRIPTIVE_FACTORIAL_DECOMPOSITION_NOT_CAUSAL_ALPHA",
        "estimand_id": LOG_GROWTH_ESTIMAND,
        "observations": len(simple_net_returns),
        "grand_mean": grand,
        "signal_main_effects": signal_effects,
        "control_main_effects": control_effects,
        "cells": [
            {
                "signal": signal,
                "control": control,
                "mean_log_return": means[signal, control],
                "interaction": means[signal, control]
                - grand
                - signal_effects[signal]
                - control_effects[control],
            }
            for signal in signals
            for control in controls
        ],
        "trend_minus_always_by_control": {
            control: means["TREND_10_40", control] - means["ALWAYS_HOLD", control]
            for control in controls
        },
        "market_factor_regression": "NOT_RUN_NO_PIT_FACTOR_EVIDENCE",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    report(parser.parse_args().output.resolve())
