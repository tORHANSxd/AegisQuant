"""Causal audit aggregation and explicit evidence gaps; never selects a winning arm."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from aegisquant.backtest.models import BacktestFill, ClosedTrade
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.validation.cat_replay import decimal
from aegisquant.research.validation.paired_bootstrap import holm_adjust, paired_block_bootstrap
from scripts.export_alpha_v4_audit_bundle import check, digest
from scripts.run_alpha_v4_audit import OUTPUT, ROOT, SEED, SYMBOLS, inputs
from scripts.run_alpha_v4_walkforward import path_metrics, table, write_json


def rows_for(name: str, root: Path = OUTPUT) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for symbol in SYMBOLS:
        for folder in sorted((root / symbol).iterdir()):
            if not (folder / "completion.json").exists():
                raise ValueError(f"incomplete fold: {folder}")
            frame = pl.read_parquet(folder / f"{name}.parquet")
            if len(frame):
                frames.append(
                    frame.with_columns(
                        pl.lit(symbol).alias("symbol"), pl.lit(folder.name).alias("fold_id")
                    )
                )
    return pl.concat(frames, how="diagonal_relaxed")


def portfolio_paths(
    equity: pl.DataFrame,
) -> tuple[dict[tuple[str, str], dict[str, Any]], pl.DataFrame, list[dict[str, Any]]]:
    numeric = equity.with_columns(
        *(pl.col(name).cast(pl.Float64) for name in ("cash", "position_value", "equity"))
    )
    combined = (
        numeric.group_by("level", "scenario", "fold_id", "time")
        .agg(
            pl.col("symbol").n_unique().alias("sleeves"),
            pl.col("cash").sum(),
            pl.col("position_value").sum(),
            pl.col("equity").sum(),
        )
        .sort("level", "scenario", "fold_id", "time")
    )
    if combined["sleeves"].min() != 5:
        raise ValueError("portfolio comparison requires every symbol on the complete common clock")
    paths: dict[tuple[str, str], dict[str, Any]] = {}
    curves: list[dict[str, Any]] = []
    for (arm, scenario), frame in combined.partition_by("level", "scenario", as_dict=True).items():
        changes: list[float] = []
        quarter_returns: list[float] = []
        clock: list[datetime] = []
        nav = 1.0
        for (fold,), group in frame.partition_by("fold_id", as_dict=True).items():
            values = group["equity"].to_numpy()
            returns = values[1:] / values[:-1] - 1
            changes.extend(returns)
            clock.extend(group["time"].to_list()[1:])
            quarter_returns.append(values[-1] / values[0] - 1)
            for time, value, exposure in zip(
                group["time"].to_list()[1:],
                values[1:],
                group["position_value"].to_numpy()[1:],
                strict=True,
            ):
                curves.append(
                    {
                        "arm": arm,
                        "scenario": scenario,
                        "fold_id": fold,
                        "time": time,
                        "research_nav": nav * value / values[0],
                        "funded_fold_equity": value,
                        "funded_fold_exposure": exposure / value,
                    }
                )
            nav *= values[-1] / values[0]
        paths[arm, scenario] = {
            "returns": np.asarray(changes),
            "quarters": np.asarray(quarter_returns),
            "clock": clock,
        }
    return paths, combined, curves


def statistics(
    paths: dict[tuple[str, str], dict[str, Any]], output: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    names = sorted(arm for arm, scenario in paths if scenario == "1")
    clock = paths[names[0], "1"]["clock"]
    if any(paths[name, "1"]["clock"] != clock for name in names):
        raise ValueError("paired inference clocks differ")
    names += ["CASH"]
    matrix = np.column_stack(
        [paths[name, "1"]["returns"] for name in names[:-1]] + [np.zeros(len(clock))]
    )
    questions = [
        ("C0", "A0"),
        ("A1", "C0"),
        ("A2", "A1"),
        ("A3", "A2"),
        ("A4", "A3"),
        ("A5", "A3"),
        ("A6", "A5"),
        ("A7", "A6"),
        ("A1", "CASH"),
        ("A3", "A1"),
        ("A3", "NULL_A3"),
        ("A3", "EN_A3"),
    ]
    records: list[dict[str, Any]] = []
    for block in (6, 18, 42, 84):
        boot = paired_block_bootstrap(matrix, block_bars=block, repetitions=10000, seed=SEED)
        group: list[dict[str, Any]] = [
            {
                "candidate": a,
                "baseline": b,
                "block_days": block / 6,
                **boot.difference(names.index(a), names.index(b)),
            }
            for a, b in questions
        ]
        corrected = holm_adjust(
            {f"{r['candidate']}-{r['baseline']}": r["one_sided_mean_p_value"] for r in group}
        )
        for row in group:
            row["holm_p_value"] = corrected[f"{row['candidate']}-{row['baseline']}"]
        records.extend(group)
    quarters = np.column_stack(
        [paths[name, "1"]["quarters"] for name in names[:-1]] + [np.zeros(14)]
    )
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, 14, (10000, 14))
    sampled = np.prod(1 + quarters[draws], axis=1) - 1
    cluster: list[dict[str, Any]] = []
    for a, b in questions:
        delta = sampled[:, names.index(a)] - sampled[:, names.index(b)]
        lo, hi = np.quantile(delta, (0.025, 0.975))
        cluster.append(
            {
                "candidate": a,
                "baseline": b,
                "clusters": 14,
                "ci95_lower": float(lo),
                "ci95_upper": float(hi),
            }
        )
    write_json(
        output / "paired_statistics.json",
        {
            "paired_common_clock": True,
            "synchronous_across_assets_and_arms": True,
            "development_only": True,
            "block_sensitivity": records,
            "quarter_clusters": cluster,
            "dsr_pbo": {
                "status": "INSUFFICIENT_EVIDENCE",
                "reason": "independent historical selection attempts not completely logged; no fabricated trial count",
            },
            "parameter_neighborhood": {
                "status": "NOT_INHERITED_FROM_BTC",
                "reason": "no outcome-based search; retain NO_PROVEN_ALPHA before any further preregistered validation",
            },
            "fully_funded_matched_random": {
                "status": "INSUFFICIENT_EVIDENCE",
                "reason": "historical random diagnostic does not match five-sleeve fractional risk and all funding constraints",
            },
        },
    )
    return records, cluster


def attribution(
    trace: pl.DataFrame, trades: pl.DataFrame, fills: pl.DataFrame, output: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    early: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for row in trades.filter(pl.col("scenario") == "1").to_dicts():
        value = ClosedTrade.model_validate_json(row["payload_json"])
        trade_rows.append(
            {
                "symbol": row["symbol"],
                "fold_id": row["fold_id"],
                "arm": row["level"],
                **value.model_dump(mode="python"),
            }
        )
    table(output / "all_trade_outcomes.parquet", trade_rows)
    b3 = [r for r in trade_rows if r["arm"] == "A0"]
    total = sum((r["net_pnl"] for r in b3), Decimal("0"))
    ranked = sorted(b3, key=lambda r: r["net_pnl"], reverse=True)
    concentration: dict[str, Any] = {
        "scope": "five fixed independent 10000 USDT accounts per quarter; fixed-trade accounting diagnostic, not financed counterfactual",
        "trades": len(b3),
        "net_pnl_sum": str(total),
        "winner_removals": [],
    }
    for count in (1, 3, 5):
        removed = sum((r["net_pnl"] for r in ranked[:count]), Decimal("0"))
        concentration["winner_removals"].append(
            {
                "removed_winners": count,
                "removed_net_pnl": str(removed),
                "remaining_fixed_trade_pnl": str(total - removed),
                "removed_share_of_total": float(removed / total),
                "trades": [{k: str(v) for k, v in r.items()} for r in ranked[:count]],
            }
        )
    quarters: dict[str, Decimal] = {}
    for row in b3:
        quarters[row["fold_id"]] = quarters.get(row["fold_id"], Decimal("0")) + row["net_pnl"]
    best = max(quarters, key=lambda key: quarters[key])
    concentration["largest_quarter"] = {
        "fold": best,
        "net_pnl": str(quarters[best]),
        "share": float(quarters[best] / total),
        "remaining_fixed_pnl": str(total - quarters[best]),
    }
    write_json(output / "concentration.json", concentration)
    traces = {
        (row["symbol"], row["fold_id"], row["arm"], row["time"]): row for row in trace.to_dicts()
    }
    by_order = {row["order_id"]: row for row in traces.values() if row.get("order_id")}
    by_arm: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in traces.values():
        by_arm[row["symbol"], row["fold_id"], row["arm"]].append(row)
    fill_by_entry: dict[tuple[str, str, datetime], BacktestFill] = {}
    for row in fills.filter((pl.col("scenario") == "1") & (pl.col("level") == "A0")).to_dicts():
        fill = BacktestFill.model_validate_json(row["payload_json"])
        if fill.side.value == "BUY":
            fill_by_entry[row["symbol"], row["fold_id"], fill.available_time] = fill
    # Exact B3 candidate entries with the common primary exit; outcome columns remain retrospective.
    for row in b3:
        entry = row["opened_at"]
        source_fill = fill_by_entry.get((row["symbol"], row["fold_id"], entry))
        # Decision is the preceding completed bar; use recorded order identity for gaps.
        selected = by_order.get(str(source_fill.backtest_order_id)) if source_fill else None
        if selected is None or source_fill is None:
            raise ValueError("B3 trade cannot be traced back to its entry decision")
        time = selected["time"]
        candidate: dict[str, Any] = {
            "symbol": row["symbol"],
            "fold_id": row["fold_id"],
            "decision_time": time,
            "entry_time": source_fill.event_time,
            "exit_time": row["closed_at"] - timedelta(hours=4, milliseconds=-1),
            "label_available_time": row["closed_at"],
            "net_pnl_reference_B3": str(row["net_pnl"]),
            "gross_pnl_reference_B3": str(row["gross_pnl"]),
            "status": "CLOSED_MATURE_AT_EXIT_NOT_AT_ENTRY",
            "outcome_is_not_strategy_input": True,
        }
        for arm in ("A2", "A3", "A4", "A7", "NULL_A3", "EN_A3"):
            decision = traces[row["symbol"], row["fold_id"], arm, time]
            candidate[f"{arm}_reason"] = decision["reason"]
            candidate[f"{arm}_planned_notional"] = decision["planned_order_notional"]
            candidate[f"{arm}_model_pass"] = decision.get("signal_filter_pass")
        labels.append(candidate)
    for row in trace.to_dicts():
        if row["reason"] not in {
            "ECONOMIC_VALUE_LOST_AFTER_EXIT_COST",
            "MISSING_CAUSAL_FORECAST_OR_DATA",
            "RISK_OR_DATA_VETO",
        }:
            continue
        if Decimal(row["current_quantity"]) <= 0 or Decimal(row["actual_fill_notional"]) == 0:
            continue
        later = [
            r
            for r in by_arm[row["symbol"], row["fold_id"], row["arm"]]
            if r["time"] > row["time"]
            and Decimal(r["signed_planned_quantity"]) > 0
            and Decimal(r["actual_fill_notional"]) > 0
        ]
        next_entry = min(later, key=lambda r: r["time"], default=None)
        early.append(
            {
                "symbol": row["symbol"],
                "fold_id": row["fold_id"],
                "arm": row["arm"],
                "decision_time": row["time"],
                "reason": row["reason"],
                "exit_execution_cost": row["realized_execution_cost"],
                "next_entry_time": next_entry["time"] if next_entry else None,
                "next_entry_cost": next_entry["realized_execution_cost"] if next_entry else None,
                "same_episode": bool(
                    next_entry
                    and row.get("trend_episode_id")
                    and row.get("trend_episode_id") == next_entry.get("trend_episode_id")
                ),
                "causal_cost_contribution": "not additive attribution; compare complete paired arm ledgers",
            }
        )
    table(output / "candidate_trade_labels.parquet", labels)
    table(output / "early_exit_reentry.parquet", early)
    misses: dict[str, Any] = {}
    for arm in ("A2", "A3", "A7", "NULL_A3", "EN_A3"):
        rejected = [
            row
            for row in labels
            if Decimal(row[f"{arm}_planned_notional"]) == 0
            and row[f"{arm}_reason"] != "INSIDE_RISK_REBALANCE_BAND"
        ]
        misses[arm] = {
            "rejected_reference_entries": len(rejected),
            "missed_reference_winner_pnl": str(
                sum(
                    (max(Decimal(r["net_pnl_reference_B3"]), Decimal("0")) for r in rejected),
                    Decimal("0"),
                )
            ),
            "avoided_reference_loser_pnl": str(
                sum(
                    (min(Decimal(r["net_pnl_reference_B3"]), Decimal("0")) for r in rejected),
                    Decimal("0"),
                )
            ),
        }
    write_json(
        output / "candidate_rejections.json",
        {
            "reference": "B3 fixed candidate quantity and primary exit; NOT a funded strategy PnL decomposition",
            "arms": misses,
        },
    )
    return concentration, misses


def calibration(forecasts: pl.DataFrame, output: Path) -> None:
    rows: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    known_cost = {}
    for symbol in SYMBOLS:
        _, _, bars, features, *_ = inputs(symbol)
        for i, bar in enumerate(bars):
            if np.isfinite(features.values[i, 9]) and bar.volume > 0:
                known_cost[symbol, bar.available_time] = float(
                    estimate_spot_transition_costs(
                        available_time=bar.available_time,
                        natr=decimal(float(features.values[i, 9])),
                        quote_volume=bar.close * bar.volume,
                        order_notional=Decimal("10000"),
                    ).round_trip
                )
    usable = forecasts.filter(
        pl.col("is_trend_candidate") & pl.col("realized_short_label").is_not_null()
    )
    for (family, symbol, fold, month), frame in (
        usable.with_columns(pl.col("available_time").dt.strftime("%Y-%m").alias("month"))
        .partition_by("family", "symbol", "fold_id", "month", as_dict=True)
        .items()
    ):
        point = frame["expected_gross_return"].cast(pl.Float64).to_numpy()
        truth = frame["realized_short_label"].to_numpy()
        prob = np.clip(frame["p_net_positive"].cast(pl.Float64).to_numpy(), 1e-12, 1 - 1e-12)
        cost = np.asarray([known_cost[symbol, time] for time in frame["available_time"].to_list()])
        positive = truth > cost
        raw = frame["raw_prediction"].cast(pl.Float64).to_numpy()
        rows.append(
            {
                "family": family,
                "symbol": symbol,
                "fold_id": fold,
                "month": month,
                "rows": len(frame),
                "trend_episodes": frame["trend_episode_id"].n_unique(),
                "nonoverlap_label_upper_bound": len(frame) // 5,
                "prediction_std": float(np.std(point)),
                "raw_prediction_std": float(np.std(raw)) if np.all(np.isfinite(raw)) else None,
                "mean_prediction": float(np.mean(point)),
                "mean_residual": float(np.mean(truth - point)),
                "brier_net_short_event": float(np.mean((prob - positive) ** 2)),
                "log_loss_net_short_event": float(
                    -np.mean(positive * np.log(prob) + (1 - positive) * np.log(1 - prob))
                ),
                "probability_target_warning": "same short-horizon NET event and original 10000 USDT known proxy cost; not full trend trade calibration",
                "raw_bias_evidence": "AVAILABLE_NEW_NULL_ONLY"
                if family == "CONSTANT"
                else "NOT_PERSISTED_NO_RECONSTRUCTION",
            }
        )
        for low in np.arange(0, 1, 0.1):
            mask = (prob >= low) & (prob < low + 0.1)
            if np.any(mask):
                curve.append(
                    {
                        "family": family,
                        "symbol": symbol,
                        "fold_id": fold,
                        "month": month,
                        "bin_lower": float(low),
                        "n": int(np.sum(mask)),
                        "mean_probability": float(np.mean(prob[mask])),
                        "net_short_event_positive_frequency": float(np.mean(positive[mask])),
                    }
                )
    table(output / "monthly_calibration.parquet", rows)
    table(output / "calibration_curve.parquet", curve)
    write_json(
        output / "model_research_gate.json",
        {
            "candidate": "risk-controlled primary trend; ML entry only",
            "minimum_meaningful_annual_increment": 0.02,
            "full_trend_labels": "retrospective matured candidate_trade_labels.parquet",
            "training_decision": "NO_NEW_RETURN_MODEL_FIT",
            "reason": "104 historical B3 trades with temporal/cross-coin clustering; no evidence of power for 2% annual incremental effect",
            "elastic_net_coefficients": "NOT_PERSISTED_IN_ORIGINAL_FIT; new code saves coefficients/intercept/target/regularization scales for future authorized fits",
            "short_vs_trend_target": "SHORT_HORIZON_PROBABILITY_CANNOT_BE_CALLED_TREND_TRADE_CALIBRATION",
            "calendar_grouping": "one shared fold clock across all five coins, labels mature before each partition",
            "new_model_fits": 0,
        },
    )


def report(
    output: Path,
    summaries: list[dict[str, Any]],
    stats: list[dict[str, Any]],
    concentration: dict[str, Any],
    misses: dict[str, Any],
) -> None:
    lines = [
        "# Alpha v4 审计归因与修复结果",
        "",
        "结论：`NO_PROVEN_ALPHA`；生产保持 `CASH`，ML、纸面准入、实盘和订单提交均关闭。",
        "",
        "本报告只使用已查看的五币开发期（2022-04-01 至 2025-10-01），不构成新样本外或最终盲测。旧目录按哈希保全；旧 B3/B7 在全部 70 个币种季度中先复现再消融。",
        "",
        "## 合同与证据",
        "",
        "旧 h=6 明确为决策后第六根开盘退出，实际持有五个4小时区间。新增显式 holding_intervals 合同可表达24小时，不重标原预测。",
        "",
        "配置偏离旧 v1 的任意字段都会拒绝；v2 通过不可变配置传入成本、资金预留、风险再平衡和八个开关。退出成本按持仓估计，两边延迟口径一致。资金预留含已知费用、价格风险及挂单占用；跳空后资金不足由账本拒单。",
        "",
        "风险仓位和概率乘数分开。风险目标使用20%年化比较锚点、2%权重容忍带、一天冷却，并受估计成本约束双向调仓；这不是最大回撤保证。缺预测禁止模型新入场，持仓仍由趋势和风险规则管理。",
        "",
        "## 固定预测消融",
        "",
        "| 版本 | 净复合收益 | Sharpe | 最大回撤 | 平均资金暴露 | 盈利季度 | 闭合交易 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        if row["scenario"] == "1":
            lines.append(
                f"| {row['arm']} | {row['net_compound_return']:.2%} | {row['sharpe'] or 0:.3f} | {row['maximum_drawdown']:.2%} | {row['capital_weighted_exposure']:.2%} | {row['positive_quarters']}/14 | {row['closed_trades']} |"
            )
    lines += [
        "",
        "A0=旧B3，C0=仅改可解释资金预留的桥接组，A1=无ML风险趋势，A2=模型仅入场，A3=加入成本入场门槛，A4=经济退出，A5=概率门槛，A6=不确定性门槛，A7=概率仓位乘数。A4与A5各自以A3为基准。NULL_A3为同校准零模型；EN_A3使用冻结Elastic Net。LEGACY_B7保留原行为。",
        "",
        "每个版本均扣实际费用。A0→C0是执行合同影响，C0→A1是风险层影响；主比较A3→A1保持相同风险规则和资金约束，实际实现波动率可能不同，未事后缩放净值。",
        "",
        "## 配对与集中度",
        "",
        f"B3五币共有 {concentration['trades']} 笔闭合交易，按旧季度固定资金求和净利润为 {Decimal(concentration['net_pnl_sum']):,.2f} USDT；这不是复合账户利润。",
        "",
    ]
    for row in concentration["winner_removals"]:
        lines.append(
            f"- 去掉最大 {row['removed_winners']} 笔赢家的固定交易会计诊断：剩余 {Decimal(row['remaining_fixed_trade_pnl']):,.2f} USDT，移除利润占总净利润 {row['removed_share_of_total']:.1%}。"
        )
    lines += [
        "",
        "上述移除是集中度诊断，不是重新按资金约束执行的策略。逐候选拒绝、错失赢家和避开亏损见 candidate_trade_labels.parquet、candidate_rejections.json；完整反事实收益以各臂账本为准，禁止把参考交易盈亏直接相加声称独立贡献。",
        "",
        "主要比较的配对区间（同步区块重采样）：",
        "",
        "| 比较 | 区块天数 | 增量复合收益95%区间 | Holm p |",
        "|---|---:|---:|---:|",
    ]
    for row in stats:
        if (row["candidate"], row["baseline"]) in {("A1", "CASH"), ("A3", "A1"), ("A3", "NULL_A3")}:
            lines.append(
                f"| {row['candidate']} − {row['baseline']} | {row['block_days']:g} | [{row['ci95_lower']:.2%}, {row['ci95_upper']:.2%}] | {row['holm_p_value']:.4f} |"
            )
    lines += [
        "",
        "## 成本、连续资金与校准",
        "",
        "成本压力分三类保存：同成交影子账本只改变非负费用；冻结订单资金账本保留拒单/部分成交和成交路径变化；重新决策压力允许门槛和交易变化。三种口径不能混为成本稳健性。",
        "",
        "连续资金与协方差研究另见 continuous/；按上季实际已扣费现金继续运行，未把已实现净值事后缩放成可交易结果。容量仍依赖4小时成交量代理，不能外推到任意资金规模。",
        "",
        "月度校准输出分段样本数、趋势聚类和残差漂移。旧原始预测、均值修正和Elastic Net系数没有保存，不能恢复后冒充原证据；新拟合接口已保存这些字段。短期净正收益概率与完整趋势交易结果并非同一目标，零模型对照不解决这一合同差异。",
        "",
        "## 未满足的准入条件",
        "",
        "- 没有经访问记录确认的12个月未使用最终留出集；未分配、访问次数0。BTC/ETH既有历史文件已包含2025-10之后资料，不能只看报告截止日期推断盲测可用。",
        "- 历史独立研究尝试记录不完整，DSR/PBO不伪造通过；原BTC邻域和不完全资金匹配随机对照不能继承给新五币候选。",
        "- 候选趋势交易样本少且跨币种同市场事件相关，没有支持2%年化增量的检验能力证据，因此不再拟合新收益模型或扩大参数网格。",
        "- 固定存活币种仍是条件资产池；缺完整历史上市/退市、费率档位、订单簿和真实执行证据。",
        "",
        "## 验收与生产状态",
        "",
        "工程复现、账本核对、合同修复和开发期归因与经济晋级分开。以上缺口使最终验证保持不足；无ML风险趋势只能保留为研究基线，ML没有获得生产候选资格。生产：CASH / selected_model_id=null / production_ml_enabled=false / LIVE_TRADING=false / ORDER_SUBMISSION_ENABLED=false。",
        "",
        "数据接口依据：[Binance公共归档与时间戳/校验说明](https://github.com/binance/binance-public-data)、[官方费用定义](https://developers.binance.com/en/docs/products/spot/faqs/commission_faq)。仅采用接口与费用定义，未访问交易账户。",
        "",
    ]
    (output / "alpha_attribution.md").write_text("\n".join(lines), encoding="utf-8")


def summarize(root: Path = OUTPUT) -> None:
    output = root / "summary"
    if output.exists():
        raise FileExistsError("summary exists; preserve versioned research evidence")
    check(ROOT, OUTPUT / "before")
    output.mkdir()
    equity, folds, trace = (
        rows_for("mtm_equity", root),
        rows_for("fold_stability", root),
        rows_for("decision_trace", root),
    )
    paths, combined, curves = portfolio_paths(equity)
    table(output / "portfolio_curves.parquet", curves)
    summaries: list[dict[str, Any]] = []
    for (arm, scenario), values in sorted(paths.items()):
        accounting = folds.filter((pl.col("level") == arm) & (pl.col("scenario") == scenario))
        clock_rows = combined.filter((pl.col("level") == arm) & (pl.col("scenario") == scenario))
        exposures = clock_rows["position_value"].to_numpy() / clock_rows["equity"].to_numpy()
        summaries.append(
            {
                "arm": arm,
                "scenario": scenario,
                **path_metrics(values["returns"]),
                "realized_annual_volatility": float(np.std(values["returns"]) * np.sqrt(2191.5)),
                "capital_weighted_exposure": float(np.mean(exposures)),
                "time_holding_rate": float(np.mean(exposures > 0)),
                "positive_quarters": int(np.count_nonzero(values["quarters"] > 0)),
                "median_quarter_return": float(np.median(values["quarters"])),
                "closed_trades": accounting["closed_trade_count"].sum(),
                "total_cost": accounting["total_cost"].sum(),
                "turnover": accounting["turnover"].sum(),
                "orders": accounting["orders"].sum(),
                "fills": accounting["fills"].sum(),
                "rejections": accounting["rejections"].sum(),
                "changed_fill_partitions": accounting.filter(~pl.col("same_fill_topology")).height,
            }
        )
    table(output / "ablation_results.parquet", summaries)
    table(output / "fold_stability.parquet", folds.to_dicts())
    table(
        output / "reason_counts.parquet",
        trace.group_by("arm", "reason").len().sort("arm", "reason").to_dicts(),
    )
    stats, _cluster = statistics(paths, output)
    concentration, misses = attribution(
        trace, rows_for("trades", root), rows_for("fills", root), output
    )
    calibration(rows_for("forecast_diagnostics", root), output)
    table(output / "same_fill_shadow.parquet", rows_for("same_fill_shadow", root).to_dicts())
    report(output, summaries, stats, concentration, misses)
    write_json(
        output / "completion.json",
        {
            "status": "NO_PROVEN_ALPHA",
            "folds": 70,
            "final_holdout_access_count": 0,
            "files": {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(
        json.dumps(
            {
                "status": "NO_PROVEN_ALPHA",
                "arms": len(summaries),
                "B3_trades": concentration["trades"],
            }
        )
    )


if __name__ == "__main__":
    summarize()
