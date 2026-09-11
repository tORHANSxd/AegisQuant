"""A0-A10 attribution of immutable reconstructed predictions; never fits a model."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from aegisquant.research.validation.failure_attribution import (
    FloatArray,
    LongFlatPath,
    long_flat_path,
    matched_random_offsets,
    path_summary,
)
from aegisquant.research.validation.public_market_backtest import (
    moving_block_mean_interval,
    return_path,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT")
COST = 0.0013
SEED = 20260903


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    before = root / "artifacts/alpha_v4/reconstructed_before"
    output = root / "artifacts/alpha_v4/diagnostics"
    reconstruction = json.loads(
        (before / "reconstruction_manifest.json").read_text(encoding="utf-8")
    )
    for name, expected in reconstruction["frozen_files_sha256"].items():
        source = (before / name).resolve()
        if not source.is_relative_to(before.resolve()) or digest(source) != expected:
            raise ValueError("frozen reconstructed predictions changed")
    if args.check:
        manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        for name, expected in manifest["files_sha256"].items():
            path = (output / name).resolve()
            if not path.is_relative_to(output.resolve()) or digest(path) != expected:
                raise ValueError(f"diagnostic artifact mismatch: {name}")
        print("A0-A10 evidence hashes verified; original predictions unchanged")
        return 0
    output.mkdir(parents=True, exist_ok=True)
    legacy = root / "reports/v5/REAL_DATA_BACKTEST"
    original = json.loads((legacy / "BACKTEST_REPORT.json").read_text(encoding="utf-8"))
    ledger = json.loads((legacy / "TRIAL_LEDGER.json").read_text(encoding="utf-8"))
    thresholds = {
        (row["symbol"], row["fold_id"]): row["calibration_thresholds"]["logistic_core"]
        for row in ledger["folds"]
    }
    frames = tuple(
        pl.read_parquet(before / f"{symbol}_logistic_core.parquet") for symbol in SYMBOLS
    )
    start: datetime = frames[0]["target_start_time"][0]
    end: datetime = frames[0]["target_end_time"][-1]
    count = int((end - start).total_seconds() // 3600)
    grid = np.arange(count + 1, dtype=np.int64) * 3_600_000 + int(start.timestamp() * 1000)
    source_hashes: dict[str, str] = {}
    returns: list[FloatArray] = []
    original_weights: list[FloatArray] = []
    reversed_weights: list[FloatArray] = []
    raw_probabilities: list[FloatArray] = []
    frozen_indices: list[np.ndarray[Any, np.dtype[np.int64]]] = []
    missing_bars: dict[str, int] = {}
    alignment_checks: dict[str, int] = {}
    for symbol, frame in zip(SYMBOLS, frames, strict=True):
        path = root / f"data/bronze/real_market_backtest/{symbol}_1h.csv"
        source_hashes[str(path.relative_to(root)).replace("\\", "/")] = digest(path)
        raw = pl.read_csv(path).select("open_time_ms", "open")
        aligned = pl.DataFrame({"open_time_ms": grid}).join(raw, on="open_time_ms", how="left")
        missing_bars[symbol] = aligned["open"].null_count()
        prices: FloatArray = aligned["open"].fill_null(strategy="forward").to_numpy()
        if np.any(~np.isfinite(prices)):
            raise ValueError("initial market price unavailable")
        returns.append(prices[1:] / prices[:-1] - 1)
        index = np.asarray(
            [
                int((time - start).total_seconds() // 3600)
                for time in frame["target_start_time"].to_list()
            ],
            dtype=np.int64,
        )
        frozen_indices.append(index)
        if not np.allclose(
            returns[-1][index], frame["realized_return"].to_numpy(), atol=1e-12, rtol=0
        ):
            raise ValueError("frozen target differs from executable open-to-open return")
        for row in frame.select(
            "feature_time", "decision_time", "target_start_time", "target_end_time"
        ).iter_rows(named=True):
            if (
                not row["feature_time"]
                <= row["decision_time"]
                < row["target_start_time"]
                < row["target_end_time"]
            ):
                raise ValueError("frozen target or execution time is misaligned")
        alignment_checks[symbol] = len(frame)
        probability: FloatArray = frame["prediction_raw"].to_numpy()
        raw_probabilities.append(probability)

        def expand(
            values: FloatArray, at_indices: np.ndarray[Any, np.dtype[np.int64]]
        ) -> FloatArray:
            full = np.full(count, np.nan)
            full[at_indices] = values
            return (
                pl.Series(full, nan_to_null=True)
                .fill_null(strategy="forward")
                .fill_null(0)
                .to_numpy()
            )

        weights: FloatArray = frame["target_position"].to_numpy()
        original_weights.append(expand(weights, index))
        calibrated = np.asarray(
            [thresholds[(symbol, fold)] for fold in frame["fold_id"].to_list()], dtype=np.float64
        )
        if not np.array_equal(weights, (probability > calibrated).astype(np.float64)):
            raise ValueError("frozen predictions do not reproduce original calibrated positions")
        reversed_weights.append(expand(((1 - probability) > calibrated).astype(np.float64), index))
    for name in ("BACKTEST_REPORT.json", "TRIAL_LEDGER.json"):
        source_hashes[f"reports/v5/REAL_DATA_BACKTEST/{name}"] = digest(legacy / name)

    def paths(
        weights: tuple[FloatArray, ...] | list[FloatArray], cost: float = COST
    ) -> tuple[LongFlatPath, ...]:
        return tuple(long_flat_path(r, w, cost) for r, w in zip(returns, weights, strict=True))

    all_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []

    def experiment(
        name: str, selected: tuple[LongFlatPath, ...], *, note: str = ""
    ) -> dict[str, Any]:
        combined: dict[str, Any] = {}
        for symbol, subset in (
            *[(s, (p,)) for s, p in zip(SYMBOLS, selected, strict=True)],
            ("PORTFOLIO", selected),
        ):
            row = {
                "experiment": name,
                "instrument": symbol,
                "evidence_origin": "RECONSTRUCTED_BASELINE",
                "scope": "FUNDED_NAV_SIGNAL_SCREEN",
                "note": note,
                **path_summary(subset),
            }
            all_rows.append(row)
            if symbol == "PORTFOLIO":
                combined = row
        if name in ("A1", "A2", "A10"):
            for i in range(count):
                trace_rows.append(
                    {
                        "experiment": name,
                        "time": start + timedelta(hours=i + 1),
                        "equity": float(np.mean([p.equity[i] for p in selected])),
                        "gross_equity": float(np.mean([p.gross_equity[i] for p in selected])),
                        "cash_cost": float(np.mean([p.cash_costs[i] for p in selected])),
                    }
                )
        return combined

    # A0 replays the archived evaluator, including its per-hour equal-weight portfolio.
    old_paths = [
        return_path(f["realized_return"].to_numpy(), f["target_position"].to_numpy(), COST)
        for f in frames
    ]
    a0_net = float(np.prod(1 + np.mean(np.stack([p.net for p in old_paths]), axis=0)) - 1)
    expected = original["candidate_portfolio_performance"]["logistic_core"]["net_compound_return"]
    if abs(a0_net - expected) > 1e-12:
        raise ValueError("A0 failed to reproduce original -38.8225% result")
    old_funded_net = float(np.mean([np.prod(1 + p.net) for p in old_paths]) - 1)
    corrected_sample_paths = tuple(
        long_flat_path(f["realized_return"].to_numpy(), f["target_position"].to_numpy(), COST)
        for f in frames
    )
    corrected_sample_net = float(np.mean([p.equity[-1] for p in corrected_sample_paths]) - 1)
    all_rows.append(
        {
            "experiment": "A0",
            "instrument": "PORTFOLIO",
            "evidence_origin": "RECONSTRUCTED_BASELINE",
            "scope": "ORIGINAL_UNCHANGED_EVALUATOR",
            "net_compound_return": a0_net,
            "gross_compound_return": original["candidate_portfolio_performance"]["logistic_core"][
                "gross_compound_return"
            ],
            "note": "原始逐小时等权平均收益；原始预测行之外的价格变化未计入",
        }
    )
    repaired, zero = paths(original_weights), paths(original_weights, 0)
    a1 = experiment(
        "A1",
        repaired,
        note="现金在两个资产账户初始各分配50%；持仓空档按原始市场价格估值；逐期复利与现金成本闭合",
    )
    a2 = experiment("A2", zero)
    experiment("A3", repaired, note="原策略本来就是 LONG/FLAT，故与 A1 相同")
    experiment(
        "A4",
        paths([np.zeros(count), np.zeros(count)]),
        note="原策略没有负目标仓位；只保留原有空头后为空仓。不能据此证明做空没有优势",
    )
    a5 = experiment(
        "A5",
        paths(reversed_weights),
        note="p -> 1-p，保持每折原校准门槛，仍为 LONG/FLAT；仅归因，不得作为上线反转方案",
    )
    shift_rows: list[dict[str, Any]] = []
    for shift in (-2, -1, 0, 1, 2):
        shifted: list[FloatArray] = []
        for weight in original_weights:
            adjusted = np.roll(weight, shift)
            if shift > 0:
                adjusted[:shift] = 0
            elif shift < 0:
                adjusted[shift:] = 0
            shifted.append(adjusted)
        row = experiment(
            f"A6_shift_{shift:+d}",
            paths(shifted),
            note="正数为延迟，负数使用未来预测，全部仅限时间归因",
        )
        shift_rows.append({**row, "shift_bars": shift, "tradable": shift >= 0})
    confidence_rows: list[dict[str, Any]] = []
    for fraction in (0.5, 0.3, 0.2, 0.1, 0.05):
        filtered: list[FloatArray] = []
        cutoffs: list[float] = []
        for i in range(2):
            score = np.abs(2 * raw_probabilities[i] - 1)
            cutoff = float(np.quantile(score, 1 - fraction))
            cutoffs.append(cutoff)
            full = np.full(count, np.nan)
            full[frozen_indices[i]] = frames[i]["target_position"].to_numpy() * (score >= cutoff)
            filtered.append(
                pl.Series(full, nan_to_null=True)
                .fill_null(strategy="forward")
                .fill_null(0)
                .to_numpy()
            )
        row = experiment(
            f"A7_top_{int(fraction * 100)}pct",
            paths(filtered),
            note="样本外全段分位数仅用于诊断；不得将此阈值投入生产或返回调参",
        )
        confidence_rows.append(
            {
                **row,
                "top_fraction": fraction,
                "BTCUSDT_cutoff": cutoffs[0],
                "ETHUSDT_cutoff": cutoffs[1],
                "threshold_fit_scope": "DIAGNOSTIC_ONLY_OOS_NOT_DEPLOYABLE",
            }
        )
    experiment("A9", paths([np.zeros(count), np.zeros(count)]))
    experiment("A10", paths([np.ones(count), np.ones(count)]))
    offsets = matched_random_offsets(tuple(original_weights), count=1000, seed=SEED)
    random_rows: list[dict[str, Any]] = []
    for number, offset in enumerate(offsets):
        selected = paths([np.roll(w, -offset) for w in original_weights])
        for old, new in zip(repaired, selected, strict=True):
            if sorted(old.holding_bars) != sorted(new.holding_bars) or np.sum(
                old.transition_units
            ) != np.sum(new.transition_units):
                raise ValueError("random baseline holding/turnover matching failed")
        random_rows.append(
            {"replicate": number, "offset_hours": offset, "seed": SEED, **path_summary(selected)}
        )
        if (number + 1) % 250 == 0:
            print(f"A8 matched random {number + 1}/1000", flush=True)
    distribution = np.asarray([row["net_compound_return"] for row in random_rows], dtype=np.float64)
    random_p = float((np.count_nonzero(distribution >= a1["net_compound_return"]) + 1) / 1001)
    random_summary = {
        "replicates": 1000,
        "median_net_return": float(np.median(distribution)),
        "strategy_one_sided_rank_p_value": random_p,
        "outperforms_random_at_5pct": random_p < 0.05,
        "matching": "exact complete holding runs, long/flat ratio and transition units; same cross-asset shift; cash-notional turnover is outcome dependent",
    }
    all_rows.append(
        {
            "experiment": "A8",
            "instrument": "PORTFOLIO",
            "net_compound_return": random_summary["median_net_return"],
            "evidence_origin": "RECONSTRUCTED_BASELINE",
            "scope": "1000_MATCHED_RANDOM_NAV_SCREENS",
            "note": random_summary["matching"],
        }
    )
    nav_zero = np.mean(np.stack([p.equity for p in zero]), axis=0)
    return_zero = np.diff(np.r_[1.0, nav_zero]) / np.r_[1.0, nav_zero[:-1]]
    zero_ci = moving_block_mean_interval(return_zero, block_length=24, repetitions=10000, seed=SEED)
    findings: list[str] = []
    if a2["net_compound_return"] < 0:
        findings.append("NO_VISIBLE_GROSS_EDGE_DO_NOT_RESCUE_WITH_TRADING_PARAMETERS")
    if random_p >= 0.05:
        findings.append("NO_DEMONSTRATED_PREDICTIVE_EDGE")
    best_shift = max(shift_rows, key=lambda row: row["net_compound_return"])["shift_bars"]
    if best_shift != 0:
        findings.append("TARGET_EXECUTION_ALIGNMENT_FAILURE_REQUIRES_INVESTIGATION")
    reversal_improvement = a5["net_compound_return"] - a1["net_compound_return"]
    # Better PnL alone is not a significance test and does not license reversal.
    if reversal_improvement > 0:
        findings.append("REVERSE_SIGNAL_IMPROVES_DIAGNOSTIC_PNL_NOT_PROVEN_SIGN_ERROR")
    waterfall = {
        "a0_original_net": a0_net,
        "a1_funded_full_clock_net": a1["net_compound_return"],
        "a2_zero_cost_net": a2["net_compound_return"],
        "attribution_bridge": {
            "original_hourly_equal_weight_return_aggregation": a0_net,
            "same_original_cost_formula_initial_funded_sleeves": old_funded_net,
            "corrected_cost_timing_same_prediction_rows": corrected_sample_net,
            "complete_market_clock_same_frozen_targets": a1["net_compound_return"],
            "allocation_change_delta": old_funded_net - a0_net,
            "self_financing_cost_timing_delta": corrected_sample_net - old_funded_net,
            "missing_prediction_interval_valuation_delta": a1["net_compound_return"]
            - corrected_sample_net,
        },
        "frozen_rows_matching_executable_raw_price_targets_and_time_order": alignment_checks,
        "shift_scan_interpretation": "nonzero best shift triggers investigation, but all original executable targets match raw prices; no demonstrated timestamp implementation error",
        "cash_cost_paid_initial_nav": a1["cash_cost_paid"],
        "compound_cost_drag": a1["cost_drag"],
        "all_in_cost_bps_one_way": 13,
        "fee_assumption_bps": 10,
        "combined_execution_assumption_bps": 3,
        "execution_components": "3bps spread/slippage/impact not separately identifiable from original evidence; no invented allocation",
        "funding_borrow": "not applicable to original SPOT LONG/FLAT",
        "missing_market_hours": missing_bars,
        "full_clock_observations": count,
        "frozen_prediction_observations_per_asset": len(frames[0]),
        "random_baseline": random_summary,
        "zero_cost_hourly_mean_95pct_moving_block_bootstrap": list(zero_ci),
        "bootstrap_repetitions": 10000,
        "bootstrap_block_hours": 24,
        "findings": findings,
        "alpha_promotion_eligible": False,
        "not_proven_by_this_diagnostic": [
            "exact historical fee tier",
            "orderbook liquidity",
            "actual original account order quantities",
            "unused final holdout",
        ],
    }
    pl.DataFrame(all_rows, infer_schema_length=None).write_parquet(
        output / "failure_attribution.parquet"
    )
    pl.DataFrame(shift_rows).write_parquet(output / "shift_scan.parquet")
    pl.DataFrame(confidence_rows).write_parquet(output / "confidence_buckets.parquet")
    pl.DataFrame(random_rows).write_parquet(output / "random_baseline.parquet")
    pl.DataFrame(trace_rows).write_parquet(output / "equity_paths.parquet")
    write_json(output / "cost_waterfall.json", waterfall)
    summary_lines = [
        "# 当前失败归因",
        "",
        "来源：RECONSTRUCTED_BASELINE；只读取已冻结的旧模型预测，没有再训练或调整校准门槛。所有结果都是开发样本外证据，不能替代最终封存集。",
        "",
        f"旧报告的 53.5086% 是 logistic_core 方向准确率，其原始净收益为 {a0_net:.6%}。另一个被选组合报告 50.0810% 和 +20.6379%，二者不是同一模型。",
        "",
        "| 实验 | 复合净收益 | 说明 |",
        "|---|---:|---|",
    ]
    for row in all_rows:
        if row["instrument"] == "PORTFOLIO":
            summary_lines.append(
                f"| {row['experiment']} | {row['net_compound_return']:.4%} | {row.get('note', '')} |"
            )
    summary_lines.extend(
        [
            "",
            f"修复后相对 1,000 个匹配随机策略的单侧秩检验 p={random_p:.4f}；随机中位数={random_summary['median_net_return']:.4%}。零成本小时平均收益的 10,000 次分块 bootstrap 95% 区间为 {zero_ci}，不能把微小点估计当成显著优势。",
            "",
            f"最佳诊断 shift 为 {best_shift}；负 shift 使用未来信号，不能交易。冻结记录中的 feature/decision/entry/target 时间另有明确顺序，shift 峰值本身不能证明代码存在符号或对齐错误。",
            "",
            "A1 保留原已校准目标和完整行情时钟，以两个等额资金账户消除逐小时免费跨资产再平衡；缺预测时持有现有仓位，缺行情时沿用最后可得估值，恢复后反映价格变化。原始市场缺失小时数："
            + str(missing_bars)
            + "。",
            "",
            "本文件的回测修正针对旧报告实际使用的归一化收益路径。事件/向量引擎、保证金、借贷、OCO、逐市场事件 MTM 和成本恒等式的正确性另见 correctness 证据；不能把那些旧路径未调用的缺陷全归为本次 -38.8% 的根因。缺少原始账户规模和订单数量，因此不会把此 NAV 诊断包装为已经通过真实执行容量的策略。",
            "",
            f"收益变化拆解：改为初始等额资金账户后的旧成本结果为 {old_funded_net:.6%}；进一步修正自融资成本时点为 {corrected_sample_net:.6%}；补全市场时钟后为 {a1['net_compound_return']:.6%}。缺失区间的账户影响据此单列，不笼统归因。全部 {sum(alignment_checks.values())} 条冻结目标均与原始 next-open 价格和 feature ≤ decision < entry < exit 时间顺序一致。",
            "",
            "A7 的全样本置信度分位数只用于归因，任何后续门槛必须只在训练/验证段确定。原策略本来没有做空，A4 空仓不能解释为空头负 alpha。",
            "",
            "判定：" + "; ".join(findings),
            "",
            "当前模型无已证明的可交易优势；停止围绕该旧模型扩大参数搜索。继续以预注册透明趋势基线核验新策略，不以旧方向准确率作为准入条件。",
        ]
    )
    (output / "failure_attribution.md").write_text(
        "\n".join(summary_lines) + "\n", encoding="utf-8", newline="\n"
    )
    manifest = {
        "schema_version": "alpha-v4-failure-attribution-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "model_refit": False,
        "evidence_origin": "RECONSTRUCTED_BASELINE",
        "scope": "FROZEN_SIGNAL_FULL_CLOCK_NAV_ATTRIBUTION",
        "source_hashes": source_hashes,
        "code_sha256": {
            name: digest(root / name)
            for name in (
                "scripts/run_alpha_v4_diagnostics.py",
                "src/aegisquant/research/validation/failure_attribution.py",
                "src/aegisquant/research/return_evaluation.py",
            )
        },
        "frozen_prediction_hashes": reconstruction["frozen_files_sha256"],
        "files_sha256": {
            p.name: digest(p)
            for p in sorted(output.iterdir())
            if p.is_file() and p.name != "run_manifest.json"
        },
        "live_trading": False,
        "order_submission_enabled": False,
    }
    write_json(output / "run_manifest.json", manifest)
    print(
        json.dumps(
            {
                "A0": a0_net,
                "A1": a1["net_compound_return"],
                "A2": a2["net_compound_return"],
                "random_p_value": random_p,
                "findings": findings,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
