"""Persist R2 evidence checks and component diagnostics without fitting return models."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl

from aegisquant.backtest.models import BacktestFill, ClosedTrade, PnLAttributionPoint
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.strategies.cost_aware_trend import (
    TrainingRobustScaler,
    fit_training_scaler,
)
from scripts.export_alpha_v4_audit_bundle import check, digest
from scripts.run_alpha_v4_audit import END, ROOT, SOURCE, SYMBOLS, inputs, read_json
from scripts.run_alpha_v4_audit_r2 import OUTPUT, PREVIOUS, verify_files
from scripts.run_alpha_v4_walkforward import path_metrics, table, write_json
from scripts.summarize_alpha_v4_audit import rows_for


def age_band(days: float | None) -> str:
    if days is None:
        return "NO_CALIBRATION_EVIDENCE"
    for lower, upper in ((0, 30), (30, 60), (60, 90), (90, 120), (120, 180)):
        if lower <= days < upper:
            return f"{lower}-{upper}"
    return "180+"


def main() -> None:
    output = OUTPUT / "verification"
    if output.exists():
        raise FileExistsError("verification already saved; preserve evidence")
    output.mkdir()
    original = check(ROOT, PREVIOUS / "before")
    config = read_json(OUTPUT / "preregistration.json")
    for name, expected in config["source_sha256"].items():
        if digest(ROOT / name) != expected or digest(OUTPUT / "implementation" / name) != expected:
            raise ValueError(f"registered R2 implementation differs: {name}")
    proofs: list[dict[str, Any]] = []
    widths: list[dict[str, Any]] = []
    scaling: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    known_cost: dict[tuple[str, datetime], float] = {}
    checked_files = new_null_fits = 0
    mature_train = mature_calibration = 0
    max_identity = Decimal("0")
    original_status: Counter[str] = Counter()
    # Scaler fits below are preprocessing diagnostics; no predictive model is fitted.
    from sklearn.preprocessing import StandardScaler  # pyright: ignore[reportMissingTypeStubs]

    for symbol in SYMBOLS:
        _, _, bars, features, _, ends, folds, indices, _ = inputs(symbol)
        for i, bar in enumerate(bars):
            if np.isfinite(features.values[i, 9]) and bar.volume > 0:
                known_cost[symbol, bar.available_time] = float(
                    estimate_spot_transition_costs(
                        available_time=bar.available_time,
                        natr=Decimal(str(features.values[i, 9])),
                        quote_volume=bar.close * bar.volume,
                        order_notional=Decimal("10000"),
                    ).round_trip
                )
        for fold in folds:
            folder = OUTPUT / symbol / fold.fold_id
            checked_files += verify_files(folder)
            contract = read_json(folder / "fold_contract.json")
            meta = contract["original_metadata"]
            train_end = datetime.fromisoformat(str(meta["maximum_train_label_end"]))
            calibration_end = datetime.fromisoformat(str(meta["maximum_calibration_label_end"]))
            if train_end >= fold.validation_start or calibration_end >= fold.test_start:
                raise ValueError("immature training/calibration labels")
            for i in fold.train_indices:
                if ends[i] is None or cast(datetime, ends[i]) >= fold.validation_start:
                    raise ValueError("training label overlaps validation")
                mature_train += 1
            mature_calibration += meta["calibration_rows"]
            for r in cast(
                list[dict[str, Any]], json.loads((folder / "reproduction.json").read_text())
            ):
                proofs.append({"symbol": symbol, "fold_id": fold.fold_id, **r})
            if (
                read_json(PREVIOUS / symbol / fold.fold_id / "null_model.json")["status"]
                == "CONSTANT_CALIBRATION_COMPLETED"
            ):
                new_null_fits += 1
            accounting = pl.read_parquet(folder / "fold_stability.parquet")
            for r in accounting.to_dicts():
                residual = abs(Decimal(r["cost_identity_residual"]))
                if (
                    residual >= Decimal(r["cost_identity_tolerance"])
                    or r["forced_close_status"] != "NO_POSITION"
                ):
                    raise ValueError("cost identity or funded final liquidation failed")
                max_identity = max(max_identity, residual)
            for r in pl.read_parquet(folder / "terminal_attribution.parquet").to_dicts():
                point = {k: r[k] for k in PnLAttributionPoint.model_fields}
                PnLAttributionPoint.model_validate_json(json.dumps(point, default=str))
            actual = pl.read_parquet(folder / "forecast_diagnostics.parquet")
            if (
                "family" in actual.columns
                and actual.filter(
                    (pl.col("available_time") < fold.test_start)
                    | (pl.col("available_time") >= fold.test_end)
                ).height
            ):
                raise ValueError("forecast outside declared fold")
            legacy_folder = (
                ROOT / "artifacts/alpha_v4/walkforward"
                if symbol == "BTCUSDT"
                else SOURCE / symbol / fold.fold_id
            )
            predictions = pl.read_parquet(legacy_folder / "predictions.parquet")
            if symbol == "BTCUSDT":
                predictions = predictions.filter(pl.col("fold_id") == fold.fold_id)
            if "family" in predictions.columns:
                for (family,), frame in predictions.partition_by("family", as_dict=True).items():
                    values = [
                        Decimal(r["q90_return"]) - Decimal(r["q10_return"])
                        for r in frame.to_dicts()
                    ]
                    original_status.update(frame["calibration_status"].to_list())
                    widths.append(
                        {
                            "symbol": symbol,
                            "fold_id": fold.fold_id,
                            "family": family,
                            "rows": len(values),
                            "minimum_width": str(min(values)),
                            "maximum_width": str(max(values)),
                            "width_range": str(max(values) - min(values)),
                            "constant_within_1e_12": max(values) - min(values) <= Decimal("1e-12"),
                            "calibration_age_at_test_start_days": (
                                fold.test_start - calibration_end
                            ).total_seconds()
                            / 86400,
                            "calibration_age_at_test_end_boundary_days": (
                                fold.test_end - calibration_end
                            ).total_seconds()
                            / 86400,
                        }
                    )
            selected = np.asarray(fold.train_indices, dtype=np.int64)
            legacy_scaler = TrainingRobustScaler.model_validate_json(meta["scaler_json"])
            safe = fit_training_scaler(
                features,
                selected,
                validation_start=fold.validation_start,
                contract_version="mad-binary-safe-r2",
            )
            old = legacy_scaler.transform(features.values)[selected]
            new = safe.transform(features.values)[selected]
            old_standard = np.asarray(
                cast(Any, StandardScaler()).fit_transform(old), dtype=np.float64
            )
            new_standard = np.asarray(
                cast(Any, StandardScaler()).fit_transform(new), dtype=np.float64
            )
            difference = float(np.max(np.abs(old_standard - new_standard)))
            scaling.append(
                {
                    "symbol": symbol,
                    "fold_id": fold.fold_id,
                    "training_rows": len(selected),
                    "legacy_weekend_scale": legacy_scaler.scale[-1],
                    "safe_weekend_scale": safe.scale[-1],
                    "legacy_max_abs_model_input_before_standard_scaler": float(np.max(np.abs(old))),
                    "safe_max_abs_model_input_before_standard_scaler": float(np.max(np.abs(new))),
                    "standardized_training_max_abs_difference": difference,
                    "equivalent_at_1e_8": difference < 1e-8,
                    "real_return_model_refitted": False,
                    "prediction_equivalence": "frozen predictions unchanged; refitted real-tree equivalence not claimed",
                }
            )
            times = [
                b.available_time for b in bars if fold.test_start <= b.event_time < fold.test_end
            ]
            full_invalid = sum(not features.valid[indices[t]] for t in times)
            trend_invalid = sum(not cast(Any, features.trend_valid)[indices[t]] for t in times)
            coverage.append(
                {
                    "symbol": symbol,
                    "fold_id": fold.fold_id,
                    "completed_4h_bars": len(times),
                    "expected_4h_bars": int(
                        (fold.test_end - fold.test_start).total_seconds() / 14400
                    ),
                    "full_ml_invalid": full_invalid,
                    "primary_trend_invalid": trend_invalid,
                    "calibration_rows": meta["calibration_rows"],
                    "prediction_rows": actual.height,
                    "reason_counts_evidence": str(
                        (folder / "decision_trace.parquet").relative_to(ROOT)
                    ),
                }
            )
    table(output / "reproduction_checks.parquet", proofs)
    table(output / "prediction_width_and_age.parquet", widths)
    table(output / "scaling_diagnostics.parquet", scaling)
    table(output / "coverage.parquet", coverage)
    trace = rows_for("decision_trace", OUTPUT)
    if trace.filter(
        (pl.col("available_time") > pl.col("decision_time"))
        | (pl.col("forecast_available_time") > pl.col("decision_time"))
        | (pl.col("cash").cast(pl.Float64) < 0)
    ).height:
        raise ValueError("future input or negative cash in decision trace")
    if trace.filter(pl.col("raw_prediction").is_null() != pl.col("mean_bias").is_null()).height:
        raise ValueError("raw prediction and bias missingness differs")
    for r in trace.filter(pl.col("raw_prediction").is_not_null()).to_dicts():
        if abs(
            Decimal(r["raw_prediction"])
            + Decimal(r["mean_bias"])
            - Decimal(r["corrected_prediction"])
        ) > Decimal("1e-12"):
            raise ValueError("corrected point does not equal saved raw plus bias")
    cost_rows = trace.filter(
        pl.col("order_id").is_not_null() & pl.col("planned_increment_cost_usdt").is_not_null()
    )
    for r in cost_rows.to_dicts():
        if r["estimate_uses_future_fill"] or r["cost_estimate_available_time"] > r["decision_time"]:
            raise ValueError("noncausal incremental cost estimate")
        if Decimal(r["realized_execution_cost"]) - Decimal(
            r["planned_increment_cost_usdt"]
        ) != Decimal(r["realized_minus_planned_cost_usdt"]):
            raise ValueError("cost estimation residual differs from trace")
    table(
        output / "planned_vs_realized_cost.parquet",
        cost_rows.select(
            "symbol",
            "fold_id",
            "arm",
            "decision_time",
            "order_id",
            "signed_planned_quantity",
            "planned_order_notional",
            "planned_increment_cost_usdt",
            "actual_fill_notional",
            "realized_execution_cost",
            "realized_minus_planned_cost_usdt",
            "rejection_reason",
        ).to_dicts(),
    )
    costs = cost_rows.with_columns(
        pl.col("realized_minus_planned_cost_usdt").cast(pl.Float64).alias("error")
    )
    table(
        output / "cost_estimation_summary.parquet",
        costs.group_by("arm")
        .agg(
            pl.len(),
            pl.col("error").mean().alias("mean_error_usdt"),
            pl.col("error").abs().mean().alias("mean_absolute_error_usdt"),
            pl.col("error").abs().max().alias("maximum_absolute_error_usdt"),
        )
        .to_dicts(),
    )

    forecast = rows_for("forecast_diagnostics", OUTPUT).filter(
        pl.col("is_trend_candidate") & pl.col("realized_short_label").is_not_null()
    )
    cal_rows: list[dict[str, Any]] = []
    for r in forecast.to_dicts():
        days = (r["available_time"] - r["calibrated_through"]).total_seconds() / 86400
        probability = min(1 - 1e-12, max(1e-12, float(r["p_net_positive"])))
        positive = r["realized_short_label"] > known_cost[r["symbol"], r["available_time"]]
        cal_rows.append(
            {
                "family": r["family"],
                "age_band_days": age_band(days),
                "symbol": r["symbol"],
                "fold_id": r["fold_id"],
                "decision_time": r["available_time"],
                "trend_episode_id": r["trend_episode_id"],
                "brier": (probability - positive) ** 2,
                "log_loss": -float(
                    positive * np.log(probability) + (1 - positive) * np.log(1 - probability)
                ),
                "corrected_mean_residual": r["realized_short_label"]
                - float(r["expected_gross_return"]),
                "short_net_positive": positive,
            }
        )
    calibration = pl.DataFrame(cal_rows)
    table(
        output / "calibration_by_age.parquet",
        calibration.group_by("family", "age_band_days")
        .agg(
            pl.len(),
            pl.col("brier").mean(),
            pl.col("log_loss").mean(),
            pl.col("corrected_mean_residual").mean(),
            pl.col("trend_episode_id").n_unique(),
        )
        .sort("family", "age_band_days")
        .to_dicts(),
    )
    by_key = {(r["symbol"], r["fold_id"], r["arm"], r["time"]): r for r in trace.to_dicts()}
    gate_rows: list[dict[str, Any]] = []
    for label in pl.read_parquet(OUTPUT / "summary/candidate_trade_labels.parquet").to_dicts():
        a3 = by_key[label["symbol"], label["fold_id"], "A3", label["decision_time"]]
        a5 = by_key[label["symbol"], label["fold_id"], "A5", label["decision_time"]]
        a6 = by_key[label["symbol"], label["fold_id"], "A6", label["decision_time"]]
        gate_rows.append(
            {
                **label,
                "mean_positive": a3["signal_filter_pass"],
                "mean_above_cost_hurdle": a3["cost_filter_pass"],
                "probability_pass": a5["probability_filter_pass"],
                "quantile_pass": a6["uncertainty_filter_pass"],
                "distribution_penalty": a6["distribution_penalty"],
                "mean_estimation_uncertainty": None,
                "interpretation": "B3 fixed reference exit/quantity; nonadditive diagnostic, actual causal arm ledgers separate",
            }
        )
    table(output / "reference_candidates_by_component.parquet", gate_rows)
    rejected: list[dict[str, Any]] = []
    for gate in ("mean_positive", "mean_above_cost_hurdle", "probability_pass", "quantile_pass"):
        rejected_rows = [r for r in gate_rows if r[gate] is False]
        rejected.append(
            {
                "gate": gate,
                "rejected_reference_candidates": len(rejected_rows),
                "missed_reference_winner_pnl": str(
                    sum(
                        (
                            max(Decimal(r["net_pnl_reference_B3"]), Decimal("0"))
                            for r in rejected_rows
                        ),
                        Decimal("0"),
                    )
                ),
                "avoided_reference_loser_pnl": str(
                    sum(
                        (
                            min(Decimal(r["net_pnl_reference_B3"]), Decimal("0"))
                            for r in rejected_rows
                        ),
                        Decimal("0"),
                    )
                ),
                "exclusive_or_additive": False,
            }
        )
    write_json(output / "component_rejection_summary.json", rejected)
    by_order = {r["order_id"]: r for r in by_key.values() if r["order_id"]}
    entries: dict[tuple[str, str, str, datetime], dict[str, Any]] = {}
    max_participation = Decimal("0")
    for row in rows_for("fills", OUTPUT).to_dicts():
        fill = BacktestFill.model_validate_json(row["payload_json"])
        if str(fill.fee.asset_id) != "USDT" or fill.fee.amount < 0:
            raise ValueError("unexpected fee currency or negative cost")
        max_participation = max(max_participation, fill.quantity.amount / fill.available_liquidity)
        if row["scenario"] == "1" and fill.side.value == "BUY":
            entries[row["symbol"], row["fold_id"], row["level"], fill.available_time] = by_order[
                str(fill.backtest_order_id)
            ]
    trade_age: list[dict[str, Any]] = []
    for row in rows_for("trades", OUTPUT).filter(pl.col("scenario") == "1").to_dicts():
        trade = ClosedTrade.model_validate_json(row["payload_json"])
        entry = entries[row["symbol"], row["fold_id"], row["level"], trade.opened_at]
        trade_age.append(
            {
                "symbol": row["symbol"],
                "fold_id": row["fold_id"],
                "arm": row["level"],
                "entry_time": trade.opened_at,
                "entry_calibration_age_days": entry["calibration_age_days"],
                "age_band_days": age_band(entry["calibration_age_days"]),
                "net_pnl": float(trade.net_pnl),
                "holding_hours": float(trade.holding_seconds / 3600),
            }
        )
    table(
        output / "trade_economics_by_age.parquet",
        pl.DataFrame(trade_age)
        .group_by("arm", "age_band_days")
        .agg(pl.len(), pl.col("net_pnl").sum(), pl.col("holding_hours").sum())
        .to_dicts(),
    )
    early = pl.read_parquet(OUTPUT / "summary/early_exit_reentry.parquet")
    table(
        output / "exit_reentry_summary.parquet",
        early.group_by("arm", "reason")
        .agg(
            pl.len(),
            pl.col("next_entry_time").is_not_null().sum().alias("later_reentries"),
            pl.col("same_episode").sum(),
            pl.col("exit_execution_cost").cast(pl.Float64).sum(),
            pl.col("next_entry_cost").cast(pl.Float64).sum(),
        )
        .to_dicts(),
    )

    verify_files(PREVIOUS / "continuous")
    transitions = pl.read_parquet(PREVIOUS / "continuous/cash_transitions.parquet")
    for _, frame in transitions.sort("fold_id").partition_by("arm", "symbol", as_dict=True).items():
        money = Decimal("10000")
        for row in frame.to_dicts():
            if (
                Decimal(row["initial_actual_cash"]) != money
                or Decimal(row["external_flows"]) != 0
                or not row["flat_after_costed_exit"]
            ):
                raise ValueError("continuous cash chain contains a reset or uncosted position")
            money = Decimal(row["final_actual_cash"])
    continuous = (
        pl.read_parquet(PREVIOUS / "continuous/mtm_equity.parquet")
        .with_columns(pl.col("equity").cast(pl.Float64))
        .sort("fold_id")
        .unique(["level", "symbol", "time"], keep="last")
    )
    continuous_metrics: list[dict[str, Any]] = []
    for (arm,), frame in (
        continuous.group_by("level", "time")
        .agg(pl.col("equity").sum())
        .sort("time")
        .partition_by("level", as_dict=True)
        .items()
    ):
        money = frame["equity"].to_numpy()
        continuous_metrics.append(
            {
                "arm": arm,
                **path_metrics(money[1:] / money[:-1] - 1),
                "actual_initial_cash": float(money[0]),
                "actual_terminal_cash": float(money[-1]),
                "cross_sleeve_transfers": False,
            }
        )
    write_json(
        output / "continuous_cash_checks.json",
        {
            "transitions": transitions.height,
            "source": str((PREVIOUS / "continuous").relative_to(ROOT)),
            "status": "PASS",
            "metrics": continuous_metrics,
        },
    )
    shadow = pl.read_parquet(OUTPUT / "summary/same_fill_shadow.parquet")
    for _, frame in shadow.partition_by("symbol", "fold_id", "arm", as_dict=True).items():
        ordered = sorted(frame.to_dicts(), key=lambda r: Decimal(r["multiplier"]))
        if Decimal(ordered[1]["final_equity"]) > Decimal(ordered[0]["final_equity"]):
            raise ValueError("same-fill cost increase improved shadow equity")
    result = {
        "status": "PASS",
        "original_evidence": original,
        "checked_r2_artifact_files": checked_files,
        "legacy_reproduction_partitions": sum(r["reference"] == "ORIGINAL_FROZEN" for r in proofs),
        "stress_reuse_base_partitions": sum(
            r["reference"] == "PRIOR_AUDIT_STRESS_REUSE" for r in proofs
        ),
        "legacy_compared_equity_points": sum(
            r["equity_points"] for r in proofs if r["reference"] == "ORIGINAL_FROZEN"
        ),
        "legacy_compared_orders": sum(
            r["orders"] for r in proofs if r["reference"] == "ORIGINAL_FROZEN"
        ),
        "legacy_compared_fills": sum(
            r["fills"] for r in proofs if r["reference"] == "ORIGINAL_FROZEN"
        ),
        "decision_trace_rows": trace.height,
        "trace_rows_with_saved_raw_and_bias": trace.filter(
            pl.col("raw_prediction").is_not_null()
        ).height,
        "prior_null_calibration_fits": new_null_fits,
        "r2_new_return_model_fits": 0,
        "r2_new_calibration_fits": 0,
        "mature_training_label_memberships": mature_train,
        "calibration_row_memberships": mature_calibration,
        "maximum_accounting_identity_residual": str(max_identity),
        "planned_increment_cost_rows": cost_rows.height,
        "cost_estimation_error_is_not_accounting_error": True,
        "maximum_actual_participation": str(max_participation),
        "original_forecast_status_counts": dict(original_status),
        "width_groups": len(widths),
        "all_widths_constant_within_1e_12": all(r["constant_within_1e_12"] for r in widths),
        "scaler_diagnostic_folds": len(scaling),
        "maximum_standardized_training_difference": max(
            r["standardized_training_max_abs_difference"] for r in scaling
        ),
        "scaler_real_model_refits": 0,
        "same_fill_shadow_rows": shadow.height,
        "final_holdout_allocated": False,
        "final_holdout_access_count": 0,
        "maximum_replay_end_exclusive": END.isoformat(),
        "secrets_or_trading_accounts_accessed": False,
        "production_policy": "CASH",
        "production_ml_enabled": False,
        "live_trading": False,
        "order_submission_enabled": False,
        "verification_script_sha256": digest(Path(__file__)),
    }
    write_json(output / "validation.json", result)
    write_json(
        output / "completion.json",
        {
            "status": "PASS",
            "files": {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
