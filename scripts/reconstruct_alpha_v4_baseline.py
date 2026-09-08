"""User-authorized reconstruction of missing original candidates, kept separate from originals."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import math
import platform
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from aegisquant.research.validation.public_market_backtest import (
    CANDIDATES,
    DownloadedKlines,
    Kline,
    RealBacktestConfig,
    SymbolRun,
    _aggregate_paths,  # pyright: ignore[reportPrivateUsage] -- reuse the exact historical evaluator
    classification_metrics,
    performance_metrics,
    prepare_samples,
    run_symbol_walk_forward,
    verify_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    legacy = root / "reports/v5/REAL_DATA_BACKTEST"
    output = root / "artifacts/alpha_v4/reconstructed_before"
    if args.check:
        reconstruction = json.loads(
            (output / "reconstruction_manifest.json").read_text(encoding="utf-8")
        )
        for name, digest in reconstruction["frozen_files_sha256"].items():
            path = (output / name).resolve()
            if (
                not path.is_relative_to(output.resolve())
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise ValueError(f"reconstructed prediction hash mismatch: {name}")
        if not reconstruction["all_summary_comparisons_passed"]:
            raise ValueError("reconstructed baseline does not match archived summaries")
        print("RECONSTRUCTED_BASELINE: hashes and 15 original-summary comparisons verified")
        return 0
    if output.exists():
        raise FileExistsError("reconstructed baseline exists; never overwrite frozen evidence")
    verify_evidence(root, legacy / "RUN_MANIFEST.json")
    original = json.loads((legacy / "BACKTEST_REPORT.json").read_text(encoding="utf-8"))
    manifest = json.loads((legacy / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    experiment = manifest["experiment"]
    config_values: dict[str, Any] = {
        field.name: experiment[field.name]
        for field in dataclasses.fields(RealBacktestConfig)
        if field.name in experiment
    }
    config_values["symbols"] = tuple(experiment["symbols"])
    config_values["start_at"] = datetime.fromisoformat(experiment["start_at"])
    config_values["end_at_exclusive"] = datetime.fromisoformat(experiment["end_at_exclusive"])
    config = RealBacktestConfig(**config_values)
    runs: list[SymbolRun] = []
    for symbol in config.symbols:
        path = root / f"data/bronze/real_market_backtest/{symbol}_1h.csv"
        with path.open(encoding="utf-8", newline="") as stream:
            records = list(csv.DictReader(stream))
        rows = tuple(
            Kline(
                open_time_ms=int(record["open_time_ms"]),
                close_time_ms=int(record["close_time_ms"]),
                trade_count=int(record["trade_count"]),
                open=float(record["open"]),
                high=float(record["high"]),
                low=float(record["low"]),
                close=float(record["close"]),
                base_volume=float(record["base_volume"]),
                quote_volume=float(record["quote_volume"]),
                taker_buy_base_volume=float(record["taker_buy_base_volume"]),
                taker_buy_quote_volume=float(record["taker_buy_quote_volume"]),
            )
            for record in records
        )
        download = DownloadedKlines(symbol, rows, path.parent, {})
        print(
            f"Reconstructing {symbol} from verified original bars; seed={config.seed}", flush=True
        )
        runs.append(run_symbol_walk_forward(prepare_samples(download), config))
    candidate_paths, _selected_path = _aggregate_paths(runs, config)
    comparisons: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        # Economic metrics are from the original, unchanged evaluator.
        positions = np.mean(
            np.stack([run.candidate_positions[candidate.candidate_id] for run in runs]), axis=0
        )
        actual_performance: dict[str, Any] = performance_metrics(
            candidate_paths[candidate.candidate_id], positions
        )
        actual_classification: dict[str, Any] = classification_metrics(
            np.concatenate([run.candidate_probabilities[candidate.candidate_id] for run in runs]),
            np.concatenate([run.samples.targets[run.oos_indices] for run in runs]),
        )
        expected_performance = original["candidate_portfolio_performance"][candidate.candidate_id]
        expected_classification = original["candidate_portfolio_classification"][
            candidate.candidate_id
        ]
        for name, actual, expected in (
            (
                "net_compound_return",
                actual_performance["net_compound_return"],
                expected_performance["net_compound_return"],
            ),
            (
                "gross_compound_return",
                actual_performance["gross_compound_return"],
                expected_performance["gross_compound_return"],
            ),
            (
                "direction_accuracy",
                actual_classification["direction_accuracy"],
                expected_classification["direction_accuracy"],
            ),
        ):
            delta = float(actual) - float(expected)
            comparisons.append(
                {
                    "candidate": candidate.candidate_id,
                    "metric": name,
                    "expected": expected,
                    "actual": actual,
                    "difference": delta,
                    "matches_original_summary": math.isclose(
                        float(actual), float(expected), rel_tol=0, abs_tol=1e-12
                    ),
                }
            )
    output.mkdir(parents=True)
    for run in runs:
        for candidate in CANDIDATES:
            indices = run.oos_indices
            samples = run.samples
            probability = run.candidate_probabilities[candidate.candidate_id]
            positions = run.candidate_positions[candidate.candidate_id]
            frame = pl.DataFrame(
                {
                    "sample_id": [samples.sample_ids[int(index)] for index in indices],
                    "instrument_id": [run.symbol] * len(indices),
                    "model_id": [candidate.candidate_id] * len(indices),
                    "feature_time": [samples.timestamps[int(index)] for index in indices],
                    "decision_time": [samples.timestamps[int(index)] for index in indices],
                    "earliest_execution_time": [
                        samples.label_start_times[int(index)] for index in indices
                    ],
                    "target_start_time": [
                        samples.label_start_times[int(index)] for index in indices
                    ],
                    "target_end_time": [samples.label_end_times[int(index)] for index in indices],
                    "prediction_raw": probability,
                    "prediction_direction": [
                        "UP" if value > 0.5 else "DOWN" for value in probability
                    ],
                    "prediction_confidence": np.maximum(probability, 1 - probability),
                    "realized_return": samples.realized_returns[indices],
                    "realized_direction": [
                        "UP" if value > 0 else "DOWN" for value in samples.realized_returns[indices]
                    ],
                    "current_position": np.r_[0.0, positions[:-1]],
                    "target_position": positions,
                    "order_quantity": pl.Series([None] * len(indices), dtype=pl.Float64),
                    "fold_id": list(run.fold_ids),
                    "evidence_origin": ["RECONSTRUCTED_BASELINE"] * len(indices),
                }
            )
            frame.write_parquet(
                output / f"{run.symbol}_{candidate.candidate_id}.parquet", compression="zstd"
            )
    result = {
        "evidence_origin": "RECONSTRUCTED_BASELINE",
        "evidence_tier": "OOS_DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "user_authorized_reconstruction": True,
        "authorization": "2026-09-08: 允许重建，并保留来源标记",
        "original_code_commit": "558f5350247c29749d5bf3b8c92ab1e52a572361",
        "python_version": platform.python_version(),
        "experiment": config.as_payload(),
        "original_artifact_hashes_verified_before_reconstruction": True,
        "originals_overwritten": False,
        "network_used": False,
        "model_refit": True,
        "comparisons": comparisons,
        "all_summary_comparisons_passed": all(
            row["matches_original_summary"] for row in comparisons
        ),
        "frozen_files_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.glob("*.parquet"))
        },
        "limitation": "Matching summary metrics does not turn reconstructed predictions into original archived outputs.",
    }
    (output / "reconstruction_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "evidence_origin": result["evidence_origin"],
                "summary_matches": result["all_summary_comparisons_passed"],
            }
        ),
        flush=True,
    )
    return 0 if result["all_summary_comparisons_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
