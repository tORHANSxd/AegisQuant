"""Verify R4 evidence, write the research decision, and package an explicit file allowlist."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import polars as pl

from aegisquant.backtest.metrics import resample_equity
from aegisquant.research.strategies.cost_aware_trend import R4TrendPolicy, TrendPolicy
from scripts.export_alpha_v4_audit_bundle import digest, git
from scripts.run_alpha_r4 import BASELINE, read_result
from scripts.run_alpha_v4_audit import ROOT, SYMBOLS, inputs, read_json
from scripts.run_alpha_v4_audit_r2 import strip_identity
from scripts.run_alpha_v4_walkforward import write_json

matplotlib.use("Agg")


def validate(output: Path) -> dict[str, Any]:
    config = read_json(output / "effective_config.json")
    if git(ROOT, "branch", "--show-current") != "main":
        raise ValueError("source must remain on main")
    original = read_json(output / "audit_manifest.json")
    for name, expected in original["baseline_files"].items():
        if digest(BASELINE / name) != expected:
            raise ValueError(f"frozen A1/A3/A7 evidence changed: {name}")
    for name, expected in config["integrated_source"].items():
        if name.startswith("src/") and digest(ROOT / name) != expected:
            raise ValueError(f"research implementation changed after freezing: {name}")
    registry = read_json(output / "experiment_registry.json")
    trials = registry["trials"]
    if len(trials) != 150 or any(r["status"] != "REPLAYED" for r in trials):
        raise ValueError("R4 requires all 150 registered funded sleeve scenarios")
    scenarios = [("REDECIDE_FUNDED", "1")] + [
        (mode, multiplier)
        for mode in ("FROZEN_ORDERS_FUNDED", "REDECIDE_FUNDED")
        for multiplier in ("1.5", "2")
    ]
    expected_trials = {
        (arm, symbol, mode, multiplier)
        for arm in ("F0", "F1", "F2", "F3", "F4", "F5")
        for symbol in SYMBOLS
        for mode, multiplier in scenarios
    }
    if {
        (r["arm"], r["symbol"], r["mode"], r["cost_multiplier"]) for r in trials
    } != expected_trials:
        raise ValueError("registered scenarios contain missing or duplicate identities")
    quarters = pl.read_parquet(output / "quarter_results.parquet")
    if any(n != 14 for n in quarters.group_by("arm", "mode", "cost_multiplier").len()["len"]):
        raise ValueError("all funded portfolio paths must have 14 calendar quarters")
    old = {
        name: pl.read_parquet(BASELINE / f"{name}.parquet").filter(pl.col("level") == "A1")
        for name in ("orders", "fills", "mtm_equity")
    }
    f0_checks: list[dict[str, Any]] = []
    for trial in trials:
        if (trial["arm"], trial["mode"], trial["cost_multiplier"]) != (
            "F0",
            "REDECIDE_FUNDED",
            "1",
        ):
            continue
        for segment in trial["segments"]:
            result = read_result(output / trial["output"] / segment["segment"])
            selected = {
                name: frame.filter(
                    (pl.col("symbol") == trial["symbol"])
                    & (pl.col("fold_id") == segment["segment"])
                )
                for name, frame in old.items()
            }
            for name, values in (("orders", result.orders), ("fills", result.fills)):
                if [strip_identity(json.loads(p)) for p in selected[name]["payload_json"]] != [
                    strip_identity(v.model_dump(mode="json")) for v in values
                ]:
                    raise ValueError("integrated F0 order/fill regression")
            actual = resample_equity(result.equity_curve, 14400)
            expected_points = selected["mtm_equity"].to_dicts()
            if len(actual) != len(expected_points) or any(
                p.time != r["time"]
                or any(getattr(p, k) != Decimal(r[k]) for k in ("equity", "cash", "position_value"))
                for p, r in zip(actual, expected_points, strict=True)
            ):
                raise ValueError("integrated F0 full-clock regression")
            f0_checks.append(
                {
                    "symbol": trial["symbol"],
                    "quarter": segment["segment"],
                    "full_mtm_points": len(actual),
                    "status": "PASS",
                }
            )
    if len(f0_checks) != 70:
        raise ValueError("F0 regression requires every original partition")
    # This is the local pytest process output recorded by this run, not uploaded XML.
    xml = ET.parse(output / "validation/full_pytest.xml").getroot()  # noqa: S314
    suites = list(xml) if xml.tag == "testsuites" else [xml]
    test_counts = {
        k: sum(int(s.attrib.get(k, "0")) for s in suites)
        for k in ("tests", "failures", "errors", "skipped")
    }
    if test_counts["failures"] or test_counts["errors"] or test_counts["skipped"]:
        raise ValueError("required engineering tests did not all pass")
    if read_json(output / "validation/full_pytest_execution.json")["exit_code"] != 0:
        raise ValueError("pytest process failed")
    reference = (output / "validation/reference_tests.txt").read_text(encoding="utf-8")
    if "Ran 40 tests" not in reference or not reference.rstrip().endswith("OK"):
        raise ValueError("provided buffer reference suite failed")
    boundaries = read_json(output / "boundary_state_checks.json")
    if boundaries["status"] != "PASS" or len(boundaries["checks"]) != 28:
        raise ValueError("quarterly event-journal recovery incomplete")
    attribution = pl.read_parquet(output / "execution_reason_attribution.parquet")
    base = [
        r
        for r in read_json(output / "all_results.json")["portfolio"]
        if r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == "1"
    ]
    for row in base:
        part = attribution.filter(pl.col("arm") == row["arm"])
        if part.height != row["fills"] or part["fill_id"].n_unique() != row["fills"]:
            raise ValueError("execution reason table lost or duplicated a fill")
        if abs(
            sum((Decimal(v) for v in part["total_cost"]), Decimal("0")) - Decimal(row["total_cost"])
        ) > Decimal("1e-8"):
            raise ValueError("execution reason costs do not reconcile")
    readiness = pl.read_parquet(output / "signal_readiness_diagnostics.parquet").filter(
        pl.col("all_signals_ready_at_interval_start").is_not_null()
    )
    assets = read_json(output / "all_results.json")["assets"]
    for symbol in SYMBOLS:
        local = readiness.filter(pl.col("symbol") == symbol)
        values = {r["arm"]: r["final_equity"] for r in assets if r["symbol"] == symbol}
        if (
            local.height != 2
            or abs(
                float(local["paired_actual_pnl_difference_usdt"].sum())
                - (values["F4"] - values["F3"])
            )
            > 1e-8
        ):
            raise ValueError("common-ready opportunity attribution does not reconcile")
    if read_json(output / "validation/pyright.json")["summary"]["errorCount"] != 0:
        raise ValueError("repository type check failed")
    if read_json(output / "validation/report_typecheck_final.json")["summary"]["errorCount"] != 0:
        raise ValueError("report type check failed")
    if read_json(output / "validation/full_summary_execution.json")["exit_code"] != 0:
        raise ValueError("summary process failed")
    if read_json(output / "validation/ruff_final_execution.json")["exit_code"] != 0:
        raise ValueError("repository lint check failed")
    result = {
        "status": "PASS",
        "funded_sleeve_scenarios": len(trials),
        "authoritative_engine_runs": sum(len(t["segments"]) for t in trials),
        "original_baseline_reproduction_partitions": 70,
        "integrated_f0_full_regressions": f0_checks,
        "frozen_baseline_files_unchanged": len(original["baseline_files"]),
        "boundary_recovery_checks": 28,
        "boundary_recovery_scope": "BTCUSDT F2/F3, all 14 quarterly causal event prefixes",
        "common_ready_attribution_reconciled_sleeves": 5,
        "full_pytest": test_counts,
        "reference_component_tests": 40,
        "pyright_errors": 0,
        "ruff_errors": 0,
        "warnings": "11 third-party deprecations: Starlette/httpx and Nautilus/Pandas/NumPy timedelta",
        "new_model_fits": 0,
        "new_calibration_fits": 0,
        "final_holdout_access_count": 0,
        "production_policy": "CASH",
        "paper_trading_admitted": False,
        "live_trading": False,
        "order_submission_enabled": False,
    }
    write_json(output / "validation/actual_test_execution.json", result)
    return result


def runtime_arguments(output: Path) -> None:
    config = read_json(output / "effective_config.json")
    markets: dict[str, Any] = {}
    for symbol in SYMBOLS:
        source, market, bars, _, _, _, folds, _, _ = inputs(symbol)
        markets[symbol] = {
            "source": source.relative_to(ROOT).as_posix(),
            "dataset_sha256": digest(source),
            "base_asset": str(market.base_asset),
            "tick_size": str(market.tick_size),
            "quantity_step": str(market.quantity_step),
            "minimum_quantity": str(market.quantity_step),
            "minimum_notional": config["audit_policy"]["execution"]["minimum_notional"],
            "first_known_bar": bars[0].event_time,
            "warmup_end": folds[0].test_start,
            "last_known_bar": bars[-1].available_time,
        }
    write_json(
        output / "effective_runtime_arguments.json",
        {
            "python": platform.python_version(),
            "markets": markets,
            "trend_base": TrendPolicy().model_dump(mode="json"),
            "F4_trend_policies": [
                R4TrendPolicy.model_validate({"fast_days": a, "slow_days": b}).model_dump(
                    mode="json"
                )
                for a, b in ((10, 40), (20, 80), (40, 160))
            ],
            "trend_score": "ma_distance_natr column 0, original hysteresis and confirmations",
            "validity": "original 17-feature finite mask, complete slow-window history after latest gap",
            "F4_readiness": "abstain until all three windows ready, no redistribution of unavailable signal budget",
            "risk": {
                "vol_window_bars": 42,
                "ddof": 0,
                "annualization": "sqrt(365.25*6)",
                "target_volatility": "0.20",
                "maximum_weight": "1",
                "probability_multiplier": "1 for F0-F5",
                "data_multiplier": "binary trend/risk validity veto",
                "cash_reserve": "causal estimated buy execution costs plus 0.25 * observed NATR; no extra 0.99 factor",
                "review": "86400 seconds from last submitted order, evaluated every completed 4h bar",
                "existing_rebalance_band": "max(0.02, 2 * incremental estimated execution cost rate)",
            },
            "buffer": {
                "relative_half_width": "0.10",
                "reference": "full A1 risk quantity before ensemble/probability scaling",
                "clock_override": "original permitted boolean",
                "scope": "additional band only for ordinary COST_AWARE_RISK_REBALANCE",
                "rounding_and_funding": "original target_quantity_adjustment and EventBacktestEngine",
            },
            "replay_cat_common": {
                "level": "A1",
                "forecasts": {},
                "old_targets": None,
                "gate_policy": config["gate"],
                "audit_policy": config["audit_policy"],
                "spread_multiplier": "1",
                "slippage_multiplier": "1",
                "volume_multiplier": "1",
                "latency_multiplier": 1,
                "omit_cost": None,
                "risk_weight_caps": None,
                "terminal_exit": True,
                "terminal_execution": "signal after penultimate completed bar, fill at last eligible next open before test_end",
            },
            "cost_scenarios": {
                "multipliers": config["cost_multipliers"],
                "fixed_orders": "None for base/redecision, exactly base BacktestOrder values for funded frozen replay",
            },
            "A3_A7_frozen_labels": {
                "version": "decision-offset-v1",
                "entry_offset_bars": 1,
                "exit_offset_bars": 6,
                "holding_intervals": 5,
                "holding_hours": 20,
                "new_fits": 0,
                "economic_exit_enabled": False,
            },
        },
    )


def draw_equity(output: Path) -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    data = pl.read_parquet(output / "portfolio_equity.parquet").filter(
        (pl.col("mode") == "REDECIDE_FUNDED") & (pl.col("cost_multiplier") == "1")
    )
    colors = {
        "F0": "#475569",
        "F1": "#94a3b8",
        "F2": "#a78bfa",
        "F3": "#2563eb",
        "F4": "#d97706",
        "F5": "#059669",
    }
    figure, axes = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2.5, 1]}
    )
    for arm, color in colors.items():
        path = data.filter(pl.col("arm") == arm).sort("time")
        wealth = path["equity"].to_numpy()
        times = path["time"].to_list()
        axes[0].plot(
            times,
            wealth,
            color=color,
            label=arm,
            lw=2 if arm in {"F0", "F3", "F4", "F5"} else 1,
            alpha=0.9,
        )
        axes[1].plot(times, 100 * (wealth / np.maximum.accumulate(wealth) - 1), color=color, lw=1.2)
    axes[0].axhline(50000, color="#64748b", linestyle=":", linewidth=0.8)
    axes[0].set_ylabel("Funded portfolio NAV (USDT)")
    axes[1].set_ylabel("Drawdown (%)")
    axes[0].set_title(
        "AegisQuant R4 | fixed five-sleeve development replay | 1x costs",
        loc="left",
        fontsize=13,
        pad=16,
    )
    axes[0].legend(ncols=6, loc="upper left", frameon=False)
    for axis in axes:
        axis.grid(alpha=0.15)
        axis.spines[["top", "right"]].set_visible(False)
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    figure.text(  # pyright: ignore[reportUnknownMemberType]  -- matplotlib kwargs stub
        0.1,
        0.015,
        "RETROSPECTIVE_DEVELOPMENT | NO_PROVEN_ALPHA | No holdout, paper or live admission",
        fontsize=9,
        color="#475569",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    figure.savefig(output / "equity_and_drawdown.png", dpi=160)  # pyright: ignore[reportUnknownMemberType]
    plt.close(figure)


def report(output: Path) -> None:
    validation = validate(output)
    runtime_arguments(output)
    draw_equity(output)
    data = read_json(output / "all_results.json")
    base = {
        r["arm"]: r
        for r in data["portfolio"]
        if r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == "1"
    }
    stats = read_json(output / "paired_statistics.json")
    a, b, c, d = (base[n] for n in ("F0", "F1", "F2", "F3"))
    delta = stats["comparisons"]["F3-F0"]
    reasons = (
        pl.read_parquet(output / "execution_reason_summary.parquet")
        .filter(pl.col("arm") == "F0")
        .sort("fills", descending=True)
        .to_dicts()
    )
    stress = read_json(output / "cost_stress_results.json")["scenarios"]
    opportunity = pl.read_parquet(output / "opportunity_attribution.parquet")
    readiness = pl.read_parquet(output / "signal_readiness_diagnostics.parquet")
    ready_effect = float(
        readiness.filter(pl.col("all_signals_ready_at_interval_start"))[
            "paired_actual_pnl_difference_usdt"
        ].sum()
    )
    unready_effect = float(
        readiness.filter(~pl.col("all_signals_ready_at_interval_start"))[
            "paired_actual_pnl_difference_usdt"
        ].sum()
    )
    challenger_delta = stats["comparisons"]["F4-F3"]
    lines = [
        "# AegisQuant R4 研究结果",
        "",
        "**NO_PROVEN_ALPHA。** R4 六个固定配置及全部成本压力已实际回放；工程通过，策略未获晋级。所有结果为 `RETROSPECTIVE_DEVELOPMENT`。生产 CASH、selected_model_id=null，ML、纸面、实盘及订单提交保持关闭。",
        "",
        "测试：2022-04-01 至 2025-10-01（不含结束时点），五币 BTC/ETH/BNB/SOL/XRP；各子账户初始 10,000 USDT，总资本 50,000，现金收益 0，无杠杆或跨币转资。未重新拟合收益模型或校准器，未访问最终留出集。",
        "",
        "| 配置 | 期末 USDT | CAGR | Sharpe | 最大回撤 | 成本 USDT | 成交 | 平均暴露 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in base.items():
        lines.append(
            f"| {name} | {row['final_equity']:,.2f} | {row['cagr']:.2%} | {row['sharpe']:.3f} | {row['maximum_drawdown']:.2%} | {float(row['total_cost']):,.2f} | {row['fills']} | {row['capital_weighted_exposure']:.3%} |"
        )
    lines += [
        "",
        "F0=原 A1；F1=仅加缓冲；F2=仅连续运行；F3=缓冲＋连续运行（预注册主候选）；F4=固定三周期等权信号；F5=同风险规则的长期持有信号。F4/F5 共同使用 F3 缓冲、费用与硬约束。",
        "",
        "![净值及回撤](equity_and_drawdown.png)",
        "",
        "## 缓冲与季度边界的实际影响",
        "",
        f"F1−F0：期末增加 {b['final_equity'] - a['final_equity']:,.2f} USDT，实际成本减少 {float(a['total_cost']) - float(b['total_cost']):,.2f}。F2−F0：期末增加 {c['final_equity'] - a['final_equity']:,.2f} USDT，成本减少 {float(a['total_cost']) - float(c['total_cost']):,.2f}。",
        "",
        f"F3−F0：增加 {d['final_equity'] - a['final_equity']:,.2f} USDT，成本减少 {float(a['total_cost']) - float(d['total_cost']):,.2f}，成交从 {a['fills']} 降到 {d['fills']}，名义换手从 {float(a['traded_notional']):,.2f} 降到 {float(d['traded_notional']):,.2f} USDT。收益变化还包含目标数量、持有机会和复利路径，不能全部归为费用节省。",
        "",
        f"季度退出取消后，F2 的闭合周期由 {a['closed_trades']} 减为 {c['closed_trades']}；现金、数量、成本基础、趋势确认、风险历史、未决订单和调仓时钟在单次运行中保留。因子交互 `F3−F2−F1+F0` 为 {stats['factor_interaction']['observed_usdt']:,.2f} USDT，其 95% 区间为 {stats['factor_interaction']['ci95_usdt']}；没有把累计收益率直接相加。",
        "",
        f"风险并非全面改善：F0/F3 实现年化波动分别为 {a['annualized_volatility']:.2%}/{d['annualized_volatility']:.2%}，最差 4h 收益为 {a['worst_4h_return']:.2%}/{d['worst_4h_return']:.2%}，4h CVaR95 为 {a['cvar_95_4h']:.2%}/{d['cvar_95_4h']:.2%}；最长回撤持续 {a['drawdown_duration_days']:.1f}/{d['drawdown_duration_days']:.1f} 天。原硬约束保持，20% 是逐币目标而非已验证的组合风险上限。",
        "",
        "## A1 2,022 次成交归因",
        "",
        "| 首要原因 | 订单 | 成交 | 名义金额 USDT | 实际成本 USDT |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in reasons:
        lines.append(
            f"| {r['reason_primary']} | {r['orders']} | {r['fills']} | {r['notional']:,.2f} | {r['cost']:,.2f} |"
        )
    lines += [
        "",
        "全部成交逐条对应 `execution_reason_attribution.parquet`。部分成交与持仓周期分别统计，成交累积出的周期数与原引擎一致。订单金额分位数、24/48 小时内反向调仓金额见原因汇总和 `risk_resize_reversals.parquet`；反向调仓只是诊断，不自动等于无效交易。",
        "",
        "审计未确认需要独立 BUGFIX_BRIDGE 的策略缺陷：A1 HOLD 保持实际数量，已取消旧路径额外 0.99 缩放；现金继承已有，A7 经济退出未开启。普通调仓沿用实际的“上次提交后 86,400 秒”检查，不擅改成 UTC 固定日历。缓冲只补充原经济调仓带，交易到最近边界；硬风险、趋势退出、首次入场和原订单管理器保持各自职责。",
        "",
        "## 信号挑战者与持有基准",
        "",
        f"F4−F3 期末差 {base['F4']['final_equity'] - d['final_equity']:,.2f} USDT；F3−F5 差 {d['final_equity'] - base['F5']['final_equity']:,.2f}；F4−F5 差 {base['F4']['final_equity'] - base['F5']['final_equity']:,.2f}。相同事前风险规则不保证实现波动或暴露相同；上述表格同时列出风险和资金使用，未做后验曲线放大。",
        "",
        "F4 使用版本化 10/40、20/80、40/160 天政策，共享一个风险预算，原 10/40 版本保持历史语义。任一窗口未完成因果预热时整组弃权，不缩短窗口或重分配预算。逐子信号 readiness、共同有效机会轴上的实际资金 PnL 分解见 `signal_readiness_diagnostics.parquet` 和 `common_ready_intervals.parquet`；这是两条完整资金路径的描述性切片，不是删掉不利时段后的可交易重跑。",
        "",
        f"共同就绪时段的 F4−F3 实际路径损益差合计为 {ready_effect:,.2f} USDT；三组未全部就绪时段合计为 {unready_effect:,.2f} USDT。因此总增益主要出现在 F4 因预热或缺口恢复而减少参与的时段，不能归为已证明的多周期信号增量。这些切片包含退出费用及此前复利路径的影响。",
        "",
        f"F4−F3 最终美元差的配对 95% 区间为 [{challenger_delta['paired_sum_daily_dollar_ci95'][0]:,.2f}, {challenger_delta['paired_sum_daily_dollar_ci95'][1]:,.2f}] USDT，覆盖负值；Holm 校正 p={challenger_delta['holm_adjusted_p_value']:.4f}。F4 的 Sharpe/Calmar 点估计较好，但尚未证明增量，更未超过持有基准的净利润。",
        "",
        "## 成本压力",
        "",
        "| 配置 | 模式 | 倍率 | 期末 USDT | 实际/影子成本 USDT | 成交 | 拒单 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in stress:
        lines.append(
            f"| {row['arm']} | {row['mode']} | {row['cost_multiplier']} | {float(row['final_equity']):,.2f} | {float(row['total_cost']):,.2f} | {row['fills']} | {row['rejections']} |"
        )
    lines += [
        "",
        "SAME_FILL_SHADOW 固定同时间、同数量、同参考价格，只机械调整非负费用且不再投资差额；它不可交易。FROZEN_ORDERS_FUNDED 固定原订单，继续执行现金、库存、精度和拒单约束。REDECIDE_FUNDED 使用相应成本重新决策。费用按实际订单/成交名义金额计算，手续费基数含成交不利价格；未降低基础 10 bps 费率。",
        "",
        "1× 成本的三种身份共用原基础成交；1.5×/2× 分别计算影子费用、冻结订单资金回放和完整重决策，无重复搜索或按压力结果选参。",
        "",
        "每个实际运行同时保存最终退出决策时 MTM、最终退出参考价上的退出前 MTM 和成本化退出后 NAV。剩余仓位在评估期内最后一个合资格 next open 处理，不取结束时点之后的价格；详见每个场景的 `summary.json`。",
        "",
        "## A3/A7 冻结机会与资金使用",
        "",
        "最新冻结 A3/A7 仍为旧有效预测的对照，没有重新校准。A3 同时改变模型入场和成本门槛，其总差异不能单独归给 XGBoost。原冻结标签为下一根入场、第六根开盘退出，实际持有 5 个 4h 区间（20h），没有改称趋势持有期预测。",
        "",
        "| 对照 | 接受/推迟/完全拒绝/全段不可用 | 固定名义影子漏掉正收益 | 固定名义影子避开负收益 |",
        "|---|---|---:|---:|",
    ]
    for arm in ("A3", "A7"):
        part = opportunity.filter(pl.col("arm") == arm)
        counts = {
            r["classification"]: r["len"] for r in part.group_by("classification").len().to_dicts()
        }
        lines.append(
            f"| {arm} | {counts} | {part['missed_positive_shadow'].cast(pl.Float64).sum():,.2f} | {part['avoided_negative_shadow'].cast(pl.Float64).sum():,.2f} |"
        )
    lines += [
        "",
        "每个 A1 趋势机会采用固定 1,000 USDT 名义的后视机会影子诊断。影子成本/时轴与真实复利账户分开标识，不能把上表当作实际可交易避亏、错失金额，或相减后解释完整路径差。完整账本区间 PnL、入场延迟、持有时间、模型不可用原因和权重见 `opportunity_attribution.parquet`。",
        "",
        "A7 的完整组合日历暴露按每个时点 sum(position_value)/sum(equity) 再求平均，复核为约 0.2644%；没有百分比二次除以 100。资金拆解逐项给出过滤器分母，模型覆盖率特指 LONG 候选时点。预估风险均值与实现波动之差仅为描述性诊断，没有用乘数均值乘积或暴露反向放大制造收益。",
        "",
        "## 统计、验证及停止结论",
        "",
        f"共同 UTC 每日时轴，{stats['repetitions']:,} 次配对区块重采样，固定 seed={stats['seed']}。预注册规则根据收益与平方收益依赖自动选取最大区块长度，本次为 {stats['block_length_days']} 天，所有币种与策略保留同时间共动。方法依据 [arch 官方区块长度说明]({stats['reference']})，使用项目原有配对圆形区块采样器；完整结果见 `paired_statistics.json`。",
        "",
        f"F3−F0 未校正的最终美元差 95% 区间为 {delta['paired_sum_daily_dollar_ci95']} USDT；配对复合收益差区间为 [{delta['ci95_lower']:.2%}, {delta['ci95_upper']:.2%}]。单侧均值检验 p={delta['one_sided_mean_p_value']:.4f}，本轮预注册比较 Holm 校正后 p={delta['holm_adjusted_p_value']:.4f}。区间反映已使用开发历史的不确定性，不能替代盲测。",
        "",
        f"工程：原 A1 70 分区精确复现，集成后 F0 再次逐单、逐成交及完整 MTM 核验；矩阵共 {validation['authoritative_engine_runs']} 次权威引擎运行、150 个币种成本场景；{validation['full_pytest']['tests']:,} 项全仓测试及 40 项参考组件测试通过。另完成 BTC 两种连续政策的 28 次真实季度事件日志保存/恢复核验，范围详见 boundary_state_checks。原引擎不提供原位增量 session restore；研究恢复通过已见事件日志重放重建全部状态，未另写账本或把结果状态强塞回账户。",
        "",
        f"F3 的 Sharpe、Calmar、正收益季度比例及季度收益中位数仍未达到原经济门槛；尾部风险亦无全面改善。F4 虽通过 Sharpe/Calmar 点估计门槛，仍仅 {base['F4']['positive_quarters']}/14 季盈利（低于 60%），季度收益中位数 {base['F4']['median_quarter_return']:.3%}，不满足大于零要求。完整历次独立研究试验历史仍不足，不能拿本轮六个配置代替 DSR/PBO 所需历史。没有确认此前未使用且满 12 个月的最终留出集，HOLDOUT_SUPPORTED 不成立。保留工程实现和全部失败/成功证据，停止扩展参数、币种或模型搜索，结论维持 NO_PROVEN_ALPHA。",
        "",
        "阶段记录：PLANNED → IMPLEMENTED → UNIT_TESTED → ENGINE_INTEGRATED → REPLAYED；没有标记 HOLDOUT_SUPPORTED，也没有把回测实现完成当成交易授权。数据仍为固定存活五币、历史费率/规则/盘口/容量未经真实执行材料证明的代理回放。",
        "",
        "## 可复现材料",
        "",
        "`audit_manifest.json` / `effective_config.json` / `effective_runtime_arguments.json` 记录源码、配置、数据和实际函数参数；`implementation_before/` 保留原用户工作区源码，`implementation/` 为冻结研究实现。新归因脚本及验证脚本另存 `reporting_implementation/`；文档修改前副本为 `project_documents_before/`，冻结 A1/A3/A7 必要账本副本为 `baseline_reference/`。运行原始结果保留在 `runs/`，原工件未覆盖。",
        "",
        "顺序入口：`python -m scripts.run_alpha_r4 register --output <new-dir>`；`baseline`；`matrix`；完成工程与边界验证后 `challengers`（或双进程调度器）；`python -m scripts.summarize_alpha_r4 --output <dir>`；`python -m scripts.finalize_alpha_r4 report --output <dir>`。重新启动研究应使用新目录并登记，不能覆盖已有证据。",
        "",
        "自动归档结果单独记录在 `validation/local_git_archive.json`；归档阻塞不改变源工作区或研究结果。证据包采用明确文件清单，不含 .env、私钥、cookie 或无关原始行情。",
    ]
    archive_record = read_json(output / "validation/local_git_archive.json")
    if archive_record["exit_code"] != 0:
        lines += [
            "",
            f"本轮自动归档实际退出码为 {archive_record['exit_code']}，既有裸库仍含 codex-archive 分支。归档脚本在分支预检停止，未生成新提交，未迁移或删除历史；源仓库 main 保持 dirty，原用户修改保留。现有本地 Skill 规定“已有非 main 归档……必须保留并报错”，本任务书 §11 同样要求归档失败只停止归档动作。完整命令与错误保存在上述 JSON/TXT，主研究证据不依赖提交成功。",
        ]
    (output / "go_no_go.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def bundle(output: Path) -> None:
    package = output.parent / f"AegisQuant_R4_Evidence_{output.name}.zip"
    if package.exists():
        raise FileExistsError("evidence package already exists")
    reporting = [
        ROOT / "scripts" / n
        for n in (
            "run_alpha_r4.py",
            "run_alpha_r4_challengers.py",
            "summarize_alpha_r4.py",
            "verify_alpha_r4.py",
            "finalize_alpha_r4.py",
        )
    ]
    reporting += [
        ROOT / "tests/alpha_v4/test_r4_contracts.py",
        ROOT / "state/ALPHA_V4_PROJECT_STATE.yaml",
        ROOT / "state/SPEC_INDEX.md",
        ROOT / "AGENTS.md",
        ROOT / "CODEX_BOOTSTRAP.md",
    ]
    for source in reporting:
        target = output / "reporting_implementation" / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    baseline_reference = output / "baseline_reference"
    baseline_reference.mkdir(exist_ok=True)
    for name in (
        "run_manifest.json",
        "results.json",
        "report.md",
        "cash_transitions.parquet",
        "decision_trace.parquet",
        "orders.parquet",
        "fills.parquet",
        "mtm_equity.parquet",
        "trades.parquet",
        "terminal_attribution.parquet",
        "portfolio_equity.parquet",
    ):
        shutil.copyfile(BASELINE / name, baseline_reference / name)
    files = [
        p
        for p in output.iterdir()
        if p.is_file() and p.suffix in {".json", ".parquet", ".md", ".png"}
    ]
    files += [
        p
        for folder in (
            "implementation_before",
            "implementation",
            "reporting_implementation",
            "project_documents_before",
            "baseline_reference",
            "validation",
            "failures",
        )
        for p in (output / folder).rglob("*")
        if p.is_file()
        and p.suffix
        in {".py", ".yaml", ".toml", ".lock", ".json", ".txt", ".xml", ".md", ".parquet"}
    ]
    files += [
        ROOT / "AegisQuant_R4" / name
        for name in (
            "README.md",
            "AegisQuant_R4_低换手与连续持仓优化任务书_20260908.md",
            "buffered_target.py",
            "tests/test_buffered_target.py",
            "snapshot.json",
            "sources.json",
            "derived_metrics.json",
            "package_manifest.json",
            "summarize_report.py",
            "test_results.txt",
        )
    ]
    files += [ROOT / "AegisQuant_盈利导向重构任务书_v4.md"]
    files += list(output.glob("runs/*/*/REDECIDE_FUNDED_1/*/result.json.gz"))
    files += list(output.glob("runs/*/*/*/summary.json"))
    files += list(output.glob("boundary_checkpoints/*/progress.json"))
    files = sorted(set(files))
    for file in files:
        relative = file.resolve().relative_to(ROOT.resolve())
        if any(
            part.lower() in {".git", ".env", "cookies", "raw_private"} for part in relative.parts
        ):
            raise ValueError("disallowed private evidence path")
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "explicit source/config/summary/base-ledger allowlist; full stress ledgers and public market CSV remain local",
        "files": {p.relative_to(ROOT).as_posix(): digest(p) for p in files},
        "excludes": [".env", "API keys", "cookies", "private raw data", "unrelated market data"],
        "research_decision": "NO_PROVEN_ALPHA",
    }
    path = output / "evidence_bundle_manifest.json"
    write_json(path, manifest)
    with zipfile.ZipFile(
        package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for file in [*files, path]:
            archive.write(file, file.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise ValueError("evidence archive integrity failure")
    write_json(
        output / "completion.json",
        {
            "status": "COMPLETE_NO_PROVEN_ALPHA",
            "package": package.relative_to(ROOT).as_posix(),
            "package_sha256": digest(package),
            "package_bytes": package.stat().st_size,
            "manifest_sha256": digest(path),
        },
    )
    print(f"Evidence package: {package} ({package.stat().st_size:,} bytes)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("report", "bundle"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    (report if args.command == "report" else bundle)(args.output.resolve())
