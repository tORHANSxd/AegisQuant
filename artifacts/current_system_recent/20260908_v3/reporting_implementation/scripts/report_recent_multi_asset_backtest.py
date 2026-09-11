"""Summarize the frozen recent R4 account replays, without selecting parameters."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from scripts.run_alpha_r4 import read_result
from scripts.run_alpha_v4_audit import ROOT, SYMBOLS, read_json
from scripts.run_alpha_v4_walkforward import digest, table, write_json
from scripts.summarize_alpha_r4 import metrics, paired_statistics

KEYS = ["arm", "mode", "cost_multiplier"]
LABELS = {
    "CASH": "当前生产：现金",
    "F2": "连续趋势、无缓冲",
    "F3": "R4 主候选：连续趋势＋10%缓冲",
    "F4": "固定多周期趋势",
    "F5": "同风险政策持有",
    "BUY_HOLD": "买入持有（原 B1，99%目标）",
}


def period_slices(frame: pl.DataFrame, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Slice an existing funded path; never reset cash or replay selected months."""
    boundaries = [start]
    year, month = start.year, start.month
    while True:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        value = datetime(year, month, 1, tzinfo=UTC)
        if value >= end:
            break
        boundaries.append(value)
    boundaries.append(end)
    output: list[dict[str, Any]] = []
    for first, last in pairwise(boundaries):
        selected = frame.filter(pl.col("time").is_between(first, last)).sort("time")
        if selected["time"][0] != first or selected["time"][-1] != last:
            raise ValueError("monthly boundary missing from funded path")
        output.append(
            {
                "month": first.strftime("%Y-%m"),
                "start": first,
                "end": last,
                "partial_month": first.day != 1 or last.day != 1 or last.hour != 0,
                "start_equity": float(selected["equity"][0]),
                "end_equity": float(selected["equity"][-1]),
                **metrics(selected),
            }
        )
    return output


def render_chart(output: Path, portfolio: pl.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    from matplotlib.ticker import PercentFormatter

    font = FontProperties(fname="C:/Windows/Fonts/msyh.ttc")
    selected = portfolio.filter(
        (pl.col("mode") == "REDECIDE_FUNDED") & (pl.col("cost_multiplier") == "1")
    )
    colors = {
        "F3": "#007F73",
        "F4": "#3266B0",
        "F5": "#B07A18",
        "BUY_HOLD": "#9C557D",
        "F2": "#81938E",
        "CASH": "#8793A2",
    }
    fig, axes = plt.subplots(
        2, 1, figsize=(12, 7.5), sharex=True, gridspec_kw={"height_ratios": [2, 1]}
    )
    for arm in ("BUY_HOLD", "F5", "F2", "F4", "F3", "CASH"):
        part = selected.filter(pl.col("arm") == arm).sort("time")
        wealth = part["equity"].to_numpy()
        times = part["time"].to_list()
        line = "--" if arm == "CASH" else "-"
        for axis, values in zip(
            axes, (wealth / 50000 - 1, wealth / np.maximum.accumulate(wealth) - 1), strict=True
        ):
            axis.plot(
                times,
                values,
                line,
                color=colors[arm],
                linewidth=2.4 if arm == "F3" else 1.3,
                label=LABELS[arm],
                alpha=1 if arm in {"F3", "F4"} else 0.8,
            )
    for axis in axes:
        axis.yaxis.set_major_formatter(PercentFormatter(1))
        axis.grid(alpha=0.18)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("成本后累计收益", fontproperties=font)
    axes[1].set_ylabel("相对历史高点回撤", fontproperties=font)
    axes[0].legend(prop=font, loc="best", ncol=2, frameon=False)
    axes[1].xaxis.set_major_locator(mdates.MonthLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    canvas: Any = fig  # Matplotlib's text/export kwargs have incomplete third-party stubs.
    canvas.suptitle(
        "近期五币历史回测｜固定 R4 策略", fontproperties=font, fontsize=17, x=0.08, ha="left"
    )
    canvas.text(
        0.08,
        0.914,
        "BTC / ETH / BNB / SOL / XRP · 初始合计 50,000 USDT · 基准全成本 · UTC 时间",
        fontproperties=font,
        fontsize=10,
        color="#586174",
    )
    canvas.text(
        0.08,
        0.02,
        "每币独立子账户，预热不计收益；末端已扣退出成本。研究回放，生产仍为 CASH。",
        fontproperties=font,
        fontsize=9,
        color="#586174",
    )
    fig.subplots_adjust(top=0.88, bottom=0.10, left=0.08, right=0.98, hspace=0.12)
    canvas.savefig(output / "equity_and_drawdown.png", dpi=160, facecolor="white")
    canvas.savefig(output / "equity_and_drawdown.svg", facecolor="white")
    plt.close(fig)


def summarize(output: Path) -> dict[str, Any]:
    config = read_json(output / "effective_config.json")
    registry = read_json(output / "experiment_registry.json")["runs"]
    frame = pl.read_parquet(output / "mtm_equity.parquet").sort(*KEYS, "symbol", "time")
    counts = frame.group_by(*KEYS, "symbol", "time").len()
    if counts["len"].max() != 1:
        raise ValueError("duplicate sleeve clock")
    portfolio = (
        frame.group_by(*KEYS, "time")
        .agg(
            pl.col("equity").sum(),
            pl.col("cash").sum(),
            pl.col("position_value").sum(),
            pl.col("symbol").sort().alias("symbols"),
        )
        .sort(*KEYS, "time")
    )
    if any(v != sorted(SYMBOLS) for v in portfolio["symbols"].to_list()):
        raise ValueError("portfolio does not contain exactly five simultaneous sleeves")
    portfolio.write_parquet(output / "portfolio_equity.parquet")
    start = datetime.fromisoformat(config["test_start"])
    end = datetime.fromisoformat(config["test_end_exclusive"])
    summaries: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    monthly: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    cost_detail: list[dict[str, Any]] = []
    for key, group in portfolio.partition_by(KEYS, as_dict=True).items():
        identity = dict(zip(KEYS, key, strict=True))
        runs = [r for r in registry if all(r[k] == v for k, v in identity.items())]
        if len(runs) != len(SYMBOLS):
            raise ValueError("missing funded sleeve result")
        capital = sum(Decimal(r["final_cash"]) for r in runs)
        if group["equity"][0] != 50000 or abs(float(capital) - group["equity"][-1]) > 1e-7:
            raise ValueError("portfolio endpoints disagree with Decimal ledgers")
        n_trades = sum(r["closed_trades"] for r in runs)
        summaries.append(
            {
                **identity,
                **metrics(group),
                "final_cash_decimal": str(capital),
                "total_cost": float(sum(Decimal(r["total_cost"]) for r in runs)),
                "fills": sum(r["fills"] for r in runs),
                "closed_trades": n_trades,
                "win_rate": sum(r["winning_trades"] for r in runs) / n_trades if n_trades else None,
                "rejections": sum(r["rejections"] for r in runs),
            }
        )
        if identity["mode"] != "REDECIDE_FUNDED" or identity["cost_multiplier"] != "1":
            continue
        arm = identity["arm"]
        monthly.extend({"arm": arm, **r} for r in period_slices(group, start, end))
        for months, since in (
            (6, start),
            (3, datetime(2026, 6, 8, tzinfo=UTC)),
            (1, datetime(2026, 8, 8, tzinfo=UTC)),
        ):
            part = group.filter(pl.col("time") >= since)
            windows.append(
                {
                    "arm": arm,
                    "months": months,
                    "start": since,
                    "end": end,
                    "identity": "SLICE_OF_CONTINUOUS_SIX_MONTH_ACCOUNT",
                    **metrics(part),
                }
            )
        for r in runs:
            part = frame.filter(
                (pl.col("arm") == arm)
                & (pl.col("symbol") == r["symbol"])
                & (pl.col("mode") == "REDECIDE_FUNDED")
                & (pl.col("cost_multiplier") == "1")
            )
            result = read_result(output / r["output"])
            if result.equity_curve[-1].equity != Decimal(r["final_cash"]):
                raise ValueError("saved result no longer agrees with registry")
            stats = result.metrics.trade_statistics
            assets.append(
                {
                    "arm": arm,
                    "symbol": r["symbol"],
                    **metrics(part),
                    "final_cash_decimal": r["final_cash"],
                    "closed_trades": r["closed_trades"],
                    "win_rate": r["winning_trades"] / r["closed_trades"]
                    if r["closed_trades"]
                    else None,
                    "total_cost": float(Decimal(r["total_cost"])),
                    "fills": r["fills"],
                    "mean_holding_days": float(stats.average_holding_seconds) / 86400,
                    "terminal_mtm_at_exit_reference": r["terminal_mtm_at_exit_reference"],
                    "exit_reference_time": r["exit_reference_time"],
                }
            )
            cost_detail.append(
                {
                    "arm": arm,
                    "symbol": r["symbol"],
                    **{
                        name: float(
                            sum((getattr(f.cost_breakdown, name) for f in result.fills), Decimal(0))
                        )
                        for name in ("fee", "spread", "slippage", "impact", "total")
                    },
                }
            )
    for name, rows in (
        ("portfolio_summary", summaries),
        ("per_asset", assets),
        ("monthly", monthly),
        ("recent_windows", windows),
        ("cost_components", cost_detail),
    ):
        table(output / f"{name}.parquet", rows)
        pl.DataFrame(rows, infer_schema_length=None).write_csv(output / f"{name}.csv")
    statistics = paired_statistics(output, portfolio)
    same = (
        pl.read_parquet(output / "same_fill_shadow.parquet")
        .with_columns(pl.col("final_equity", "total_cost").cast(pl.Float64))
        .group_by("arm", "cost_multiplier")
        .agg(pl.col("final_equity").sum(), pl.col("total_cost").sum())
    )
    for part in same.partition_by("arm"):
        ordered = part.with_columns(pl.col("cost_multiplier").cast(pl.Float64)).sort(
            "cost_multiplier"
        )
        if np.any(np.diff(ordered["final_equity"].to_numpy()) > 1e-7):
            raise ValueError("same-fill shadow improves when costs rise")
    same.write_csv(output / "same_fill_shadow_summary.csv")
    render_chart(output, portfolio)
    result = {
        "status": "COMPLETED_FIXED_POLICY_RECENT_TEST",
        "decision": "NO_PROVEN_ALPHA",
        "test_start": config["test_start"],
        "test_end_exclusive": config["test_end_exclusive"],
        "engine_runs": len(registry),
        "portfolio": summaries,
        "per_asset": assets,
        "monthly": monthly,
        "recent_windows": windows,
        "paired_statistics": statistics,
        "production_policy": "CASH",
        "new_model_fits": 0,
        "final_holdout_access_count": 0,
    }
    write_json(output / "summary.json", result)
    return result


def report(output: Path, result: dict[str, Any]) -> None:
    base = {
        r["arm"]: r
        for r in result["portfolio"]
        if r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == "1"
    }

    def pct(value: float) -> str:
        return f"{value:.2%}"

    def number(value: float | None) -> str:
        return "—" if value is None else f"{value:.2f}"

    lines = [
        "# 当前量化系统：最近六个月五币历史测试",
        "",
        f"评估区间：{result['test_start']} 至 {result['test_end_exclusive']}（UTC，右端不含）。",
        "北京时间为 2026-03-08 08:00 至 2026-09-08 20:00。末根完整4h K线收盘为 19:59:59.999；当前未完成K线不参与。",
        "末端付费平仓参考为2026-09-08北京时间16:00（最后完整K线开盘），最终4小时保持现金；未使用20:00之后的价格。",
        "",
        f"固定主候选 F3：净收益 **{pct(base['F3']['net_compound_return'])}**，最大回撤 **{pct(base['F3']['maximum_drawdown'])}**，"
        f"50,000 USDT 变为 **{base['F3']['final_equity']:,.2f} USDT**。研究结论仍为 `NO_PROVEN_ALPHA`，生产策略仍为 CASH。",
        f"缓冲比F2节省费用 {base['F2']['total_cost'] - base['F3']['total_cost']:.2f} USDT，"
        f"但最终净利润少 {base['F2']['final_equity'] - base['F3']['final_equity']:.2f} USDT。"
        "8月单月增加4,161.88 USDT，高于全段净利润3,035.49 USDT，利润集中而非稳定逐月增长。",
        "",
        "## 固定测试口径",
        "",
        "BTC/ETH/BNB/SOL/XRP，各10,000 USDT，子账户独立，无跨币转资，无外部入金；4h决策、下一事件成交、现货LONG/FLAT。"
        "评估起点前365天仅用于因果指标预热，不计入收益。F3为此前已固定的主候选，不按本轮赢家重新选择。",
        "",
        "F2为连续趋势且无缓冲；F3增加10%数量缓冲；F4固定10/40、20/80、40/160天等权信号预算；"
        "F5采用与F3相同的风险、缓冲和成本规则持有市场。每币风险目标20%年化是软目标，不是组合保证。"
        "BUY_HOLD复用原B1的99%入场目标，没有风险再平衡；它与低暴露策略承担的风险不同。",
        "",
        "没有新收益模型、校准器或标准化器拟合。A3/A7没有近期冻结预测，未伪造预测或暗中重训。"
        "F0/F1的旧季度边界诊断不重复；本次重点是当前连续运行版本。",
        "",
        "版本身份：本轮开始时冻结的R4，源HEAD为 `d8c6d4013097f6323ab8b7a424c860ba0ccbd62b`。"
        "回放期间工作区出现其他策略改动，均予保留；本报告不覆盖这些后续修改。"
        "已从 `implementation/` 隔离导入冻结源码，额外180次复现的完整结果与原180个场景逐项一致。"
        "21项冻结策略契约测试和8项近期入口测试通过；未将全仓旧测试数量冒充本轮执行数。",
        "",
        "## 基准全成本结果",
        "",
        "| 配置 | 净收益 | 期末USDT | 最大回撤 | 年化Sharpe | 平均资金暴露 | 闭合交易 | 胜率 | 总成本USDT |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ("CASH", "F2", "F3", "F4", "F5", "BUY_HOLD"):
        r = base[arm]
        lines.append(
            f"| {LABELS[arm]} | {pct(r['net_compound_return'])} | {r['final_equity']:,.2f} | "
            f"{pct(r['maximum_drawdown'])} | {number(r['sharpe'])} | {pct(r['capital_weighted_exposure'])} | "
            f"{r['closed_trades']} | {'—' if r['win_rate'] is None else pct(r['win_rate'])} | {r['total_cost']:,.2f} |"
        )
    lines += [
        "",
        "Sharpe按完整4h MTM权益计算、零无风险收益；半年年化值仅作诊断。闭合交易指完整flat-to-flat持仓周期，调仓成交不单算交易。",
        "",
        "## F3 分币结果",
        "",
        "| 币种 | 净收益 | 期末USDT | 最大回撤 | 平均资金暴露 | 闭合交易 | 成本USDT |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol in SYMBOLS:
        r = next(r for r in result["per_asset"] if r["arm"] == "F3" and r["symbol"] == symbol)
        lines.append(
            f"| {symbol} | {pct(r['net_compound_return'])} | {r['final_equity']:,.2f} | "
            f"{pct(r['maximum_drawdown'])} | {pct(r['capital_weighted_exposure'])} | {r['closed_trades']} | {r['total_cost']:,.2f} |"
        )
    lines += [
        "",
        "## 月度与近期切片",
        "",
        "月度从同一连续资金路径切片，不清仓、不重置本金。3月和9月为不完整月份。",
        "",
        "| 月份 | F3净收益 | F4净收益 | F5净收益 | 买入持有净收益 |",
        "|---|---:|---:|---:|---:|",
    ]
    for month in sorted({r["month"] for r in result["monthly"]}):
        values = [
            next(
                r["net_compound_return"]
                for r in result["monthly"]
                if r["arm"] == a and r["month"] == month
            )
            for a in ("F3", "F4", "F5", "BUY_HOLD")
        ]
        lines.append(f"| {month} | " + " | ".join(pct(v) for v in values) + " |")
    lines += ["", "| F3连续账户区间 | 区间净收益 | 区间内最大回撤 |", "|---|---:|---:|"]
    for r in result["recent_windows"]:
        if r["arm"] == "F3":
            lines.append(
                f"| 最近{r['months']}个月 | {pct(r['net_compound_return'])} | {pct(r['maximum_drawdown'])} |"
            )
    lines += [
        "",
        "最近1/3个月保留此前的实际持仓和资金，不代表各自在起点重新投入50,000 USDT的独立回测。",
        "",
        "## 成本压力与费用含义",
        "",
        "基准单边手续费10 bps，半点差1 bps，滑点底值2 bps＋前一已完成K线NATR项，另计延迟不利1 bps与参与率冲击。"
        "现货没有资金费与借币成本。沿用代理精度、最小名义10 USDT及1%参与率上限；没有用当前费率折扣倒填历史。",
        "",
        "| 配置 | 0×毛成本诊断 | 0.5× | 1× | 1.5× | 2× |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in ("F2", "F3", "F4", "F5", "BUY_HOLD"):
        values = [
            next(
                r["net_compound_return"]
                for r in result["portfolio"]
                if r["arm"] == arm and r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == m
            )
            for m in ("0", "0.5", "1", "1.5", "2")
        ]
        lines.append(f"| {arm} | " + " | ".join(pct(v) for v in values) + " |")
    lines += [
        "",
        "上表为各成本环境下完整重决策的资金回放，成交路径可能变化，不能把0×与1×的收益差全归为同成交费用。"
        "另有1.5×/2×冻结原订单的资金回放（保留拒单与库存约束），以及固定原成交的不可交易影子成本，详见CSV。",
        "",
        "## 统计与证据边界",
        "",
        "使用原R4共同UTC日轴的10,000次配对区块重采样，保留跨策略、跨币同时相关性；自动区块长度沿用已固定规则。"
        "统计只用完整UTC日，末尾半天收益与退出仍计入完整账户结果；统计差额与全段期末差额因此可能不同。",
        "",
        "| 事前固定比较 | 日轴复合收益差 | 95%区间 | Holm校正p |",
        "|---|---:|---|---:|",
    ]
    for name, r in result["paired_statistics"]["comparisons"].items():
        lines.append(
            f"| {name} | {pct(r['observed_compound_return_difference'])} | "
            f"[{pct(r['ci95_lower'])}, {pct(r['ci95_upper'])}] | {r['holm_adjusted_p_value']:.4f} |"
        )
    lines += [
        "",
        "这六个月不是预先封存满12个月的最终留出集。固定存活五币不代表全市场可交易清单；"
        "历史账户费率、盘口排队和真实容量未验证。DSR/PBO所需完整独立试验历史仍不齐全，不能用本轮少量配置代替。"
        "正收益或单个较好的币种也不能自动证明alpha，亦未改变纸面/实盘准入。",
        "",
        "## 验证与可复现材料",
        "",
        f"完成{result['engine_runs']}次实际引擎运行。逐运行检查成本恒等式、非负现金、LONG/FLAT、"
        "权益=现金+持仓市值、严格下一事件成交、末端真实付费退出，以及保存结果重读。"
        "组合每个时点必须包含相同五币，累计资金与Decimal账本核对。",
        "",
        "每币完整4h时间轴、预热与三周期就绪数量见 `data_quality.json`；来源页及SHA-256在 `source_manifest.json` / `raw/`。"
        "官方数据格式见 [Binance Kline 文档](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)。",
        "",
        "`runs/`保存完整逐订单、逐成交、仓位、成本、权益与闭合交易JSON及决策追踪；`portfolio_summary.csv`、`per_asset.csv`、"
        "`monthly.csv`、`recent_windows.csv`、`same_fill_shadow_summary.csv`提供易读表格。"
        "`implementation/`保存运行源码，`effective_config.json`冻结参数与日期。验证记录见 `validation/`。",
        "",
        "复现：使用新目录执行 `python -m scripts.run_recent_multi_asset_backtest prepare --output <new-dir>`，随后执行 `run`。"
        "精确重放本次日期须使用本目录保存的数据与冻结配置，不能用未来下载的新增日期冒充同一运行。",
        "",
        "v1在配置序列化时失败；v2在回放初始化的严格Decimal解析时失败；均发生在引擎运行前，未产生收益试验。"
        "原失败目录和日志保留；v3只修正输入序列化适配，没有修改R4策略或引擎。",
        "",
        "![权益与回撤](equity_and_drawdown.png)",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    target = parser.parse_args().output.resolve()
    outcome = summarize(target)
    report(target, outcome)
    write_json(
        target / "reporting_manifest.json",
        {
            "script": Path(__file__).relative_to(ROOT).as_posix(),
            "sha256": digest(Path(__file__)),
            "source_ledger": digest(target / "experiment_registry.json"),
            "report_sha256": digest(target / "report.md"),
        },
    )
    print(
        json.dumps(
            [
                r
                for r in outcome["portfolio"]
                if r["mode"] == "REDECIDE_FUNDED" and r["cost_multiplier"] == "1"
            ],
            ensure_ascii=True,
        ),
        flush=True,
    )
