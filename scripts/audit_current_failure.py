"""Freeze existing public OOS evidence without training, network access, or strategy changes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl
import yaml

from aegisquant.research.validation.public_market_backtest import (
    FloatArray,
    ReturnPath,
    classification_metrics,
    performance_metrics,
    return_path,
    verify_evidence,
)

SPEC = "AegisQuant_盈利导向重构任务书_v4.md"
LEGACY = "reports/v5/REAL_DATA_BACKTEST"
PREDICTIONS = "data/gold/real_market_backtest/OOS_PREDICTIONS.csv"
OUTPUT = "artifacts/alpha_v4/before"
FAILED_CANDIDATE = "logistic_core"
BLOCKER = "MISSING_ORIGINAL_FAILED_CANDIDATE_PREDICTIONS"
FROZEN_COLUMNS = (
    "sample_id",
    "instrument_id",
    "feature_time",
    "decision_time",
    "earliest_execution_time",
    "target_start_time",
    "target_end_time",
    "prediction_raw",
    "prediction_direction",
    "prediction_confidence",
    "realized_return",
    "realized_direction",
    "current_position",
    "target_position",
    "order_quantity",
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return cast("dict[str, Any]", value)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def frozen_frame(csv_path: Path) -> pl.DataFrame:
    """Preserve exported values; do not synthesize unexported candidate probabilities/orders."""
    frame = pl.read_csv(csv_path).sort("symbol", "decision_time_utc")
    required = {
        "sample_id",
        "symbol",
        "decision_time_utc",
        "label_start_time_utc",
        "label_end_time_utc",
        "positive_probability",
        "position",
        "realized_return",
        "selected_candidate",
        "fold_id",
        "threshold",
        "gross_return",
        "cost_return",
        "net_return",
    }
    if not required.issubset(frame.columns) or frame.height == 0:
        raise ValueError("incomplete original selected-policy export")
    if frame.n_unique(["symbol", "sample_id"]) != frame.height:
        raise ValueError("duplicate original sample id")
    for name in ("positive_probability", "position", "realized_return"):
        if frame[name].null_count() or not frame[name].is_finite().all():
            raise ValueError(f"non-finite original {name}")
    for name in ("positive_probability", "position"):
        if not frame[name].is_between(0, 1).all():
            raise ValueError(f"invalid original {name}")
    probability = pl.col("positive_probability")
    frame = frame.with_columns(
        pl.col("symbol").alias("instrument_id"),
        pl.col("decision_time_utc").str.to_datetime(time_zone="UTC").alias("decision_time"),
        pl.col("label_start_time_utc").str.to_datetime(time_zone="UTC").alias("target_start_time"),
        pl.col("label_end_time_utc").str.to_datetime(time_zone="UTC").alias("target_end_time"),
        probability.alias("prediction_raw"),
        pl.when(probability > 0.5)
        .then(pl.lit("UP"))
        .otherwise(pl.lit("DOWN"))
        .alias("prediction_direction"),
        pl.max_horizontal(probability, 1.0 - probability).alias("prediction_confidence"),
        pl.when(pl.col("realized_return") > 0)
        .then(pl.lit("UP"))
        .otherwise(pl.lit("DOWN"))
        .alias("realized_direction"),
        pl.col("position").shift(1).over("symbol").fill_null(0.0).alias("current_position"),
        pl.col("position").alias("target_position"),
        pl.lit(None, dtype=pl.Float64).alias("order_quantity"),
        pl.lit("SELECTED_POLICY_ONLY").alias("prediction_scope"),
    ).with_columns(
        pl.col("decision_time").alias("feature_time"),
        pl.col("target_start_time").alias("earliest_execution_time"),
    )
    if not frame.select(
        (
            (pl.col("decision_time") < pl.col("target_start_time"))
            & (pl.col("target_start_time") < pl.col("target_end_time"))
        ).all()
    ).item():
        raise ValueError("original prediction window is not strictly executable in the future")
    return frame.select(
        *FROZEN_COLUMNS, *[name for name in frame.columns if name not in FROZEN_COLUMNS]
    )


def replay_selected(csv_path: Path) -> dict[str, Any]:
    """A0: call the unchanged original evaluator on the already exported signal."""
    rows: dict[str, list[dict[str, str]]] = {}
    with csv_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            rows.setdefault(row["symbol"], []).append(row)
    paths: list[ReturnPath] = []
    positions: list[FloatArray] = []
    probabilities: list[float] = []
    returns: list[float] = []
    timelines: list[list[str]] = []
    for symbol_rows in rows.values():
        realized = np.array([float(row["realized_return"]) for row in symbol_rows])
        position = np.array([float(row["position"]) for row in symbol_rows])
        # The source run explicitly assumed 10 bps fee + 3 bps execution per turnover.
        path = return_path(realized, position, 0.0013)
        for column, actual in (
            ("gross_return", path.gross),
            ("cost_return", path.costs),
            ("net_return", path.net),
        ):
            exported = np.array([float(row[column]) for row in symbol_rows])
            if not np.allclose(actual, exported, rtol=0, atol=1e-14):
                raise ValueError(f"original {column} cannot be reproduced without retraining")
        paths.append(path)
        positions.append(position)
        probabilities.extend(float(row["positive_probability"]) for row in symbol_rows)
        returns.extend(realized.tolist())
        timelines.append([row["label_start_time_utc"] for row in symbol_rows])
    if not paths or any(timeline != timelines[0] for timeline in timelines):
        raise ValueError("unaligned cross-asset selected-policy paths")
    aggregate = ReturnPath(
        *(
            np.mean(np.stack([getattr(path, attribute) for path in paths]), axis=0)
            for attribute in ("gross", "costs", "net", "turnover")
        )
    )
    performance = performance_metrics(aggregate, np.mean(np.stack(positions), axis=0))
    classification = classification_metrics(
        np.array(probabilities), np.where(np.array(returns) > 0, 1.0, -1.0)
    )
    return {
        "scope": "SELECTED_POLICY_ONLY",
        "model_retrained": False,
        "classification": classification,
        "performance": performance,
        "arithmetic_return": float(np.sum(aggregate.net)),
        "normalized_initial_equity": 1.0,
        "normalized_final_equity": 1.0 + cast("float", performance["net_compound_return"]),
    }


def verify_frozen(root: Path) -> dict[str, Any]:
    directory = root / OUTPUT
    manifest = read_json(directory / "run_manifest.json")
    for relative, expected in manifest["frozen_files_sha256"].items():
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory.resolve()) or sha256(path) != expected:
            raise ValueError(f"frozen evidence hash mismatch: {relative}")
    frame = pl.read_parquet(directory / "frozen_predictions.parquet")
    if frame.height != manifest["frozen_prediction_rows"]:
        raise ValueError("frozen prediction row count mismatch")
    if not set(FROZEN_COLUMNS).issubset(frame.columns):
        raise ValueError("frozen prediction schema mismatch")
    if frame["order_quantity"].null_count() != frame.height:
        raise ValueError("original run did not export executable order quantities")
    return manifest


def freeze(root: Path, git_commit_sha: str) -> dict[str, Any]:
    directory = root / OUTPUT
    if directory.exists():
        # A frozen run is immutable. An incomplete directory requires inspection, not overwrite.
        return verify_frozen(root)
    verify_evidence(root, root / LEGACY / "RUN_MANIFEST.json")
    source_manifest = read_json(root / LEGACY / "RUN_MANIFEST.json")
    report = read_json(root / LEGACY / "BACKTEST_REPORT.json")
    experiment = source_manifest["experiment"]
    if (
        experiment["assumed_fee_bps_per_turnover"],
        experiment["assumed_execution_bps_per_turnover"],
    ) != (10.0, 3.0):
        raise ValueError("source cost configuration differs from frozen evaluator")
    frame = frozen_frame(root / PREDICTIONS)
    replay = replay_selected(root / PREDICTIONS)
    original = report["aggregate_selected_policy"]
    for section, field in (
        ("classification", "direction_accuracy"),
        ("performance", "net_compound_return"),
    ):
        if not math.isclose(replay[section][field], original[section][field], abs_tol=1e-12):
            raise ValueError(f"A0 replay differs from original report: {field}")
    failed_performance = report["candidate_portfolio_performance"][FAILED_CANDIDATE]
    failed_classification = report["candidate_portfolio_classification"][FAILED_CANDIDATE]
    sources = [entry["path"] for entry in source_manifest["artifacts"]]
    sources.extend([f"{LEGACY}/RUN_MANIFEST.json", "uv.lock", SPEC])
    source_hashes = {path: sha256(root / path) for path in sources}
    directory.mkdir(parents=True)
    frame.write_parquet(directory / "frozen_predictions.parquet", compression="zstd")
    shutil.copyfile(
        root / LEGACY / "BACKTEST_REPORT.json", directory / "original_backtest_report.json"
    )
    shutil.copyfile(root / LEGACY / "RUN_MANIFEST.json", directory / "original_run_manifest.json")
    write_json(directory / "a0_selected_policy_replay.json", replay)
    config = {
        "original_experiment": experiment,
        "audit": {
            "model_retrained": False,
            "network_access": False,
            "frozen_scope": "SELECTED_POLICY_ONLY",
            "failed_candidate": FAILED_CANDIDATE,
        },
        "safety": {"live_trading": False, "order_submission_enabled": False},
    }
    (directory / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=True), encoding="utf-8"
    )
    lineage: dict[str, Any] = {
        "metrics_are_from_different_policies": True,
        "direction_accuracy": {
            "field": "aggregate_selected_policy.classification.direction_accuracy",
            "value": original["classification"]["direction_accuracy"],
            "formula": "mean((selected_positive_probability > 0.5) == (realized_open_to_open_return > 0))",
            "source": f"{LEGACY}/BACKTEST_REPORT.json",
            "implementation": "src/aegisquant/research/validation/public_market_backtest.py:1015",
            "is_curve_accuracy": False,
            "is_closed_trade_win_rate": False,
        },
        "loss_below_40_percent": {
            "field": f"candidate_portfolio_performance.{FAILED_CANDIDATE}.net_compound_return",
            "value": failed_performance["net_compound_return"],
            "direction_accuracy": failed_classification["direction_accuracy"],
            "formula": "prod(1 + mean_across_symbols(position * realized_return - abs(position_change) * 0.0013)) - 1; final exit included",
            "source": f"{LEGACY}/BACKTEST_REPORT.json",
            "implementation": "src/aegisquant/research/validation/public_market_backtest.py:1072",
            "original_per_sample_predictions_available": False,
        },
        "evaluation_engine": "public_market_backtest.return_path + performance_metrics; not EventBacktestEngine, VectorBacktestEngine or baselines.evaluate_predictions",
        "position_semantics": "long/flat weights in [0, 1]; equal-weight BTC/ETH returns per timestamp; not an order/fill account simulation",
        "time_semantics": {
            "feature_time": "latest completed feature bar close, equal to exported decision_time_utc",
            "decision_time": "bar t close_time (UTC)",
            "earliest_execution_time": "bar t+1 open, exported label_start_time_utc",
            "target_start_time": "bar t+1 open",
            "target_end_time": "bar t+2 open",
            "target": "open[t+2] / open[t+1] - 1 (arithmetic one-hour return)",
        },
        "frozen_field_semantics": {
            "prediction_raw": "exported positive_probability, NOT a return forecast",
            "prediction_confidence": "derived max(p, 1-p); not calibrated confidence",
            "realized_direction": "legacy binary label; exact zero is DOWN",
            "current_position": "previous exported position by symbol; preserves original cross-fold continuity",
            "order_quantity": "null: original evaluator has no account size, prices/quantities or actual orders",
        },
        "blocking_missing_evidence": [BLOCKER],
        "unidentifiable_cost_components": [
            "spread",
            "slippage",
            "impact",
            "latency_adverse_selection",
        ],
        "cost_limitation": "3 bps execution is a combined assumption; cannot decompose into actual TCA components",
    }
    write_json(directory / "metric_lineage.json", lineage)
    report_text = f"""# Alpha v4 当前失败证据冻结

EvidenceTier: `OOS_DEVELOPMENT`。Phase A 状态：`BLOCKED_MISSING_FAILED_PREDICTIONS`。
本次只读原始公开数据并冻结现有输出，没有重新训练、调用网络或修改策略。

## 指标已定位

- `50.0810%` 来自所选元策略的逐样本二分类方向准确率，不是价格曲线成功率或完整交易胜率。
- 同一元策略净复合收益为 `{original["performance"]["net_compound_return"]:.6%}`，最大回撤为 `{original["performance"]["maximum_drawdown"]:.6%}`。
- `-38.8225%` 来自 `{FAILED_CANDIDATE}` 候选，其方向准确率为 `{failed_classification["direction_accuracy"]:.6%}`。两个用户指标不能拼成同一运行。
- 上述字段均来自 `reports/v5/REAL_DATA_BACKTEST/BACKTEST_REPORT.json`；具体公式及源码位置见 `metric_lineage.json`。
- 使用独立的公开市场研究收益向量评估器，已采用 LONG/FLAT、逐期复合和最终退出成本。任务书对旧 baselines evaluator 的缺陷描述不能直接归因到该运行。

## 已冻结与 A0 复现

保存 {frame.height:,} 行所选元策略逐样本数据，BTC/ETH 各 30,240 行。
`frozen_predictions.parquet` 的每行标记 `SELECTED_POLICY_ONLY`；它不是亏损候选的完整预测。
使用原始 `return_path` 和 `performance_metrics`，不重新拟合模型，复现每行毛收益、成本、净收益以及报告的准确率和净复合收益（误差阈值 `1e-12`）。
账户初始资金未记录；`initial_equity=1` 仅为复核复合收益的归一化净值单位。
原流程无订单数量，`order_quantity` 保留 null，不用仓位权重伪造订单。

## 尚不能进行的归因

原 OOS CSV 只记录 selected policy；原 RUN_MANIFEST 与 TRIAL_LEDGER 未登记候选的完整逐样本预测或模型文件。
因此无法冻结 `{FAILED_CANDIDATE}` 的完整原始预测，也无法在相同预测条件下完成亏损候选的 A0–A10。
冻结文件中即使包含少量 selected_candidate={FAILED_CANDIDATE} 的行，也不代表未选中时的完整序列。
原成本是每单位换手 10 bps 手续费和 3 bps 合并执行成本假设。点差、滑点、冲击、资金费和借币的实际分项没有观测证据；不能反推出它们各占原亏损多少。

## 继续条件

优先提供原运行 `{FAILED_CANDIDATE}` 的逐样本预测导出（sample_id、概率或原始预测、仓位及时间）。
如原数据确实未保存，需要用户明确允许按原提交、数据、配置和 seed 重建候选，并标注 `RECONSTRUCTED_BASELINE`；重建结果不能声称是原预测。
依据任务书 §2.2“冻结当前预测，不允许重新训练”和 §14 提交顺序，当前不进入策略修改、参数优化或最终 holdout。
实盘交易及订单提交继续锁定；现有数据已经用于开发 OOS，不能重新命名为未读过的最终 holdout。
"""
    (directory / "current_failure_report.md").write_text(report_text, encoding="utf-8")
    manifest: dict[str, Any] = {
        "schema_version": "alpha-v4-failure-freeze-v1",
        "git_commit_sha": git_commit_sha,
        "python_version": platform.python_version(),
        "lockfile_sha256": source_hashes["uv.lock"],
        "ssot": SPEC,
        "ssot_sha256": source_hashes[SPEC],
        "evidence_tier": "OOS_DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "phase_a_status": "BLOCKED_MISSING_FAILED_PREDICTIONS",
        "blocking_reason_codes": [BLOCKER],
        "frozen_scope": "SELECTED_POLICY_ONLY",
        "failed_candidate": FAILED_CANDIDATE,
        "failed_candidate_predictions_frozen": False,
        "model_retrained": False,
        "frozen_prediction_rows": frame.height,
        "source_files_sha256": source_hashes,
        "dataset_paths": [path for path in sources if path.startswith("data/")],
        "dataset_sha256": {
            path: digest for path, digest in source_hashes.items() if path.startswith("data/")
        },
        "venue": "BINANCE",
        "instrument_id": experiment["symbols"],
        "instrument_type": "SPOT",
        "timeframe": "1h",
        "start_time": experiment["start_at"],
        "end_time": experiment["end_at_exclusive"],
        "oos_start_time": str(frame["target_start_time"].min()),
        "oos_end_time": str(frame["target_end_time"].max()),
        "warmup_range": {
            "minimum_feature_lookback_bars": 168,
            "train_hours": 8760,
            "validation_hours": 720,
            "calibration_hours": 720,
            "per_fold_ledger": f"{LEGACY}/TRIAL_LEDGER.json",
        },
        "prediction_horizon": experiment["forecast_horizon"],
        "execution_delay": experiment["execution_delay"],
        "initial_equity": 1.0,
        "final_equity": replay["normalized_final_equity"],
        "equity_units": "NORMALIZED_NAV_NOT_ORIGINAL_ACCOUNT_CAPITAL",
        "arithmetic_return": replay["arithmetic_return"],
        "compounded_return": replay["performance"]["net_compound_return"],
        "reported_accuracy_name": "direction_accuracy",
        "reported_accuracy_formula": lineage["direction_accuracy"]["formula"],
        "fee_schedule_version": "ASSUMED_10_BPS_PER_TURNOVER_NOT_VERIFIED_VENUE_TIER",
        "spread_model": "UNRESOLVED_WITHIN_COMBINED_3_BPS_EXECUTION_ASSUMPTION",
        "slippage_model": "UNRESOLVED_WITHIN_COMBINED_3_BPS_EXECUTION_ASSUMPTION",
        "impact_model": "UNRESOLVED_WITHIN_COMBINED_3_BPS_EXECUTION_ASSUMPTION",
        "funding_model": "NOT_APPLICABLE_SPOT_LONG_FLAT",
        "borrow_model": "NOT_APPLICABLE_NO_SHORT",
        "leverage": 1.0,
        "position_mode": "LONG_FLAT",
        "random_seeds": [experiment["seed"]],
        "failed_candidate_archived_summary": {
            "performance": failed_performance,
            "classification": failed_classification,
        },
        "live_trading": False,
        "order_submission_enabled": False,
        "frozen_files_sha256": {
            path.name: sha256(path) for path in sorted(directory.iterdir()) if path.is_file()
        },
    }
    write_json(directory / "run_manifest.json", manifest)
    return verify_frozen(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify immutable frozen evidence only"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.check:
        manifest = verify_frozen(root)
    else:
        git = shutil.which("git")
        if git is None:
            raise RuntimeError("git is required to identify the unchanged source baseline")
        # The resolved Git executable receives literal arguments, without a shell or user input.
        revision = subprocess.run(  # noqa: S603  # nosec B603
            [git, "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        manifest = freeze(root, revision)
    print(
        json.dumps(
            {
                "integrity": "VERIFIED",
                "phase_a_status": manifest["phase_a_status"],
                "frozen_prediction_rows": manifest["frozen_prediction_rows"],
                "failed_candidate_predictions_frozen": manifest[
                    "failed_candidate_predictions_frozen"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
