"""R2 fixed-forecast audit. Versioned evidence only; no return-model fitting or search."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl

from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import BacktestResult, EquityPoint
from aegisquant.data.hashing import canonical_sha256
from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.research.models.economic_gate import (
    CalibrationStatus,
    EconomicForecast,
    PointForecastStatus,
)
from aegisquant.research.validation.calendar_walkforward import CalendarFold
from aegisquant.research.validation.cat_contract import (
    CatAuditPolicy,
    audit_arms,
    compile_legacy_config,
)
from aegisquant.research.validation.cat_replay import replay_cat
from scripts.export_alpha_v4_audit_bundle import check, digest, git
from scripts.run_alpha_v4_audit import OUTPUT as PREVIOUS
from scripts.run_alpha_v4_audit import (
    ROOT,
    SOURCE,
    SYMBOLS,
    frozen,
    inputs,
    make_spec,
    read_json,
    save_result,
    trial_collections,
)
from scripts.run_alpha_v4_walkforward import table, write_json

OUTPUT = ROOT / "artifacts/alpha_v4_audit/20260908_r2_v1"
TASKBOOK = ROOT / "AegisQuant_盈利验证修复任务书_R2_2026-09-08.md"
LEGACY = {"A0": "B3", "LEGACY_B5": "B5", "LEGACY_B6": "B6", "LEGACY_B7": "B7"}
IDENTIFIERS = {
    "fill_id",
    "venue_order_id",
    "backtest_order_id",
    "client_order_id",
    "order_intent_id",
}


def policies() -> dict[str, CatAuditPolicy]:
    return {
        k: CatAuditPolicy.model_validate({**v.model_dump(mode="python"), "version": "cat-audit-r2"})
        for k, v in audit_arms().items()
    }


def verify_files(folder: Path) -> int:
    recorded = read_json(folder / "completion.json")
    for name, expected in recorded["files"].items():
        if digest(folder / name) != expected:
            raise ValueError(f"frozen audit evidence changed: {folder / name}")
    return len(recorded["files"])


def preregister() -> None:
    if OUTPUT.exists():
        raise FileExistsError("R2 already registered; never replace its identity")
    if git(ROOT, "branch", "--show-current") != "main":
        raise ValueError("R2 requires existing main without branch mutation")
    check(ROOT, PREVIOUS / "before")
    evidence = {
        str((PREVIOUS / "before/audit_manifest.json").relative_to(ROOT)): digest(
            PREVIOUS / "before/audit_manifest.json"
        )
    }
    for symbol in SYMBOLS:
        for folder in sorted((PREVIOUS / symbol).iterdir()):
            verify_files(folder)
            evidence[(folder / "completion.json").relative_to(ROOT).as_posix()] = digest(
                folder / "completion.json"
            )
    for name in ("summary", "continuous"):
        verify_files(PREVIOUS / name)
        evidence[(PREVIOUS / name / "completion.json").relative_to(ROOT).as_posix()] = digest(
            PREVIOUS / name / "completion.json"
        )
    OUTPUT.mkdir()
    source_names = [
        *read_json(PREVIOUS / "implementation_v1/source_manifest.json")["files"],
        "scripts/run_alpha_v4_audit_r2.py",
    ]
    snapshot = OUTPUT / "implementation"
    source_hashes: dict[str, str] = {}
    for name in source_names:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        source_hashes[name] = digest(target)
    write_json(
        snapshot / "source_manifest.json",
        {"files": source_hashes, "snapshot_timing": "BEFORE_R2_REPLAY"},
    )
    original = read_json(PREVIOUS / "preregistration.json")
    config = {
        **original,
        "version": "alpha-v4-audit-r2-v1",
        "registered_at": datetime.now(UTC).isoformat(),
        "taskbook": TASKBOOK.name,
        "taskbook_sha256": digest(TASKBOOK),
        "git_sha": git(ROOT, "rev-parse", "HEAD"),
        "worktree_status": git(ROOT, "status", "--porcelain=v1", "--untracked-files=normal"),
        "source_sha256": source_hashes,
        "previous_evidence": evidence,
        "previous_results_already_seen": True,
        "arms": {k: v.model_dump(mode="json") for k, v in policies().items()},
        "gate": EconomicGatePolicy().model_dump(mode="json"),
        "legacy_reproductions": list(LEGACY.values()),
        "r2_changes": [
            "component calibration dependencies",
            "explicit decision value and predictive distribution penalty",
            "calibration age diagnostics without outcome-selected cutoff",
            "incremental risk-rebalance cost estimation",
        ],
        "decision_value_kind": {
            k: "MEDIAN_MINUS_PREDICTIVE_WIDTH"
            if v.switches.use_uncertainty_entry_gate
            else "MEAN_GROSS_RETURN"
            for k, v in policies().items()
        },
        "calibration_age_bins_days": [0, 30, 60, 90, 120, 180],
        "maximum_calibration_age_days": None,
        "frozen_prediction_component_mapping": "AVAILABLE fitted point and residual components inferred from original fit recipe and fold metadata; original probability status retained; missing raw/bias not reconstructed",
        "preprocessing": "real forecasts remain frozen MAD-v1; optional binary-safe-r2 verified separately, no real model refit",
        "selection_budget": {
            "new_return_model_fits": 0,
            "new_constant_fits": 0,
            "new_calibration_fits": 0,
            "previous_constant_calibrations_reused": True,
            "parameter_searches": 0,
            "new_symbols": 0,
            "historical_return_model_fits": 186,
            "independent_attempt_history": "INCOMPLETE",
        },
        "stress_evidence": "reuse prior three-mode stresses only after A1/A3 funded ledger equality; otherwise fail and register required rerun",
        "continuous_evidence": "reuse prior A1 continuous/covariance money only after corresponding A1 base equality",
        "hypothesis_scope": "R2 additional controlled development attempt; prior failures retained, no new OOS claim",
    }
    config.pop("sha256", None)
    config["sha256"] = canonical_sha256(config)
    write_json(OUTPUT / "preregistration.json", config)
    write_json(
        OUTPUT / "effective_config.json",
        {"legacy": compile_legacy_config(ROOT, multi_asset=True), "r2": config},
    )
    print("R2 registered: fixed forecasts, zero new fits, unchanged primary hypotheses", flush=True)


def strip_identity(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: strip_identity(v)
            for k, v in cast(dict[str, Any], value).items()
            if k not in IDENTIFIERS
        }
    if isinstance(value, list):
        return [strip_identity(v) for v in cast(list[Any], value)]
    return value


def select(frame: pl.DataFrame, fold: str, level: str, scenario: str) -> pl.DataFrame:
    if "level" not in frame.columns:
        return frame
    chosen = frame.filter(pl.col("level") == level)
    if "fold_id" in chosen.columns:
        chosen = chosen.filter(pl.col("fold_id") == fold)
    return chosen.filter(pl.col("scenario") == scenario) if "scenario" in chosen.columns else chosen


def verify_ledger(
    result: BacktestResult, folder: Path, fold: CalendarFold, level: str, scenario: str
) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    for name, actual in (("orders", result.orders), ("fills", result.fills)):
        frame = select(pl.read_parquet(folder / f"{name}.parquet"), fold.fold_id, level, scenario)
        prior = (
            [strip_identity(json.loads(p)) for p in frame["payload_json"].to_list()]
            if "payload_json" in frame.columns
            else []
        )
        current = [strip_identity(r.model_dump(mode="json")) for r in actual]
        if prior != current:
            raise ValueError(f"{folder.name} {level}: exact {name} economic payload differs")
        counts[name] = len(current)
    equity = select(pl.read_parquet(folder / "mtm_equity.parquet"), fold.fold_id, level, scenario)
    points = tuple(
        EquityPoint.model_validate({k: r[k] for k in EquityPoint.model_fields})
        for r in equity.to_dicts()
    )
    prior_curve = resample_equity(points, 14400)
    current_curve = resample_equity(result.equity_curve, 14400)
    if prior_curve != current_curve:
        raise ValueError(f"{folder.name} {level}: full fixed-clock cash/equity differs")
    counts.update(
        {
            "equity_points": len(current_curve),
            "status": "PASS",
            "cash_equity_and_fill_values": "EXACT_DECIMAL",
            "ignored_fields": "run-specific order/fill identifiers only",
        }
    )
    return counts


def components(
    value: EconomicForecast, meta: dict[str, Any], evidence_hash: str
) -> EconomicForecast:
    data = value.model_dump(mode="python")
    data.update(
        {
            "point_forecast_status": PointForecastStatus.AVAILABLE,
            "trained_through": meta["maximum_train_label_end"],
            "residual_calibration_status": CalibrationStatus.VALIDATION_CALIBRATED
            if meta["calibration_rows"] >= 30
            else CalibrationStatus.UNAVAILABLE,
            "probability_calibration_status": value.calibration_status,
            "residual_calibrated_through": meta["maximum_calibration_label_end"],
            "probability_calibrated_through": value.calibrated_through,
            "component_evidence_sha256": evidence_hash,
        }
    )
    return EconomicForecast.model_validate(data)


def augment_trace(
    rows: list[dict[str, Any]],
    *,
    arm: str,
    family: str,
    forecasts: dict[datetime, EconomicForecast],
    meta: dict[str, Any],
    episodes: dict[datetime, str | None],
) -> None:
    for row in rows:
        value = forecasts.get(row["time"])
        legacy_quantile = arm in {"LEGACY_B6", "LEGACY_B7"}
        model_used = arm not in {"A0", "A1", "C0"}
        through = value.residual_calibrated_through if value else None
        row.update(
            {
                "arm": arm,
                "model_id": family if model_used else None,
                "train_end": str(meta["maximum_train_label_end"]),
                "trend_episode_id": episodes[row["time"]],
                "trace_provenance": "R2_REPLAY_OF_FROZEN_FORECAST_NOT_ORIGINAL_RAW_DECISION",
                "point_forecast_status": value.point_forecast_status.value
                if value
                else "MODEL_MISSING",
                "probability_calibration_status": str(value.probability_calibration_status)
                if value
                else "MODEL_MISSING",
                "residual_calibration_status": str(value.residual_calibration_status)
                if value
                else "MODEL_MISSING",
                "calibration_age_days": (row["time"] - through).total_seconds() / 86400
                if through
                else None,
                "calibration_end": through,
                "forecast_available_time": value.available_time if value else None,
                "raw_prediction": str(value.raw_prediction)
                if value and value.raw_prediction is not None
                else None,
                "mean_bias": str(value.mean_bias)
                if value and value.mean_bias is not None
                else None,
                "raw_prediction_missing_reason": None
                if value and value.raw_prediction is not None
                else "ORIGINAL_RAW_PREDICTION_AND_BIAS_NOT_PERSISTED",
                "corrected_prediction": str(value.expected_gross_return) if value else None,
                "p_net_positive": str(value.p_net_positive) if value else None,
                "q10": str(value.q10_return) if value else None,
                "q50": str(value.q50_return) if value else None,
                "q90": str(value.q90_return) if value else None,
                "quantile_width": str(value.q90_return - value.q10_return) if value else None,
                "mean_estimation_uncertainty": None,
                "mean_estimation_uncertainty_status": "NOT_ESTIMATED",
            }
        )
        if arm in LEGACY:
            row["decision_value_kind"] = (
                "NO_MODEL_VALUE"
                if not model_used
                else "MEDIAN_MINUS_PREDICTIVE_WIDTH"
                if legacy_quantile
                else "MEAN_GROSS_RETURN"
            )
            row["distribution_penalty"] = (
                str(Decimal("0.25") * (value.q90_return - value.q10_return))
                if value and legacy_quantile
                else "0"
            )
            row["calibration_dependency_policy"] = "LEGACY_JOINT_STATUS"
        else:
            row["calibration_dependency_policy"] = "R2_ENABLED_COMPONENTS_ONLY"


def run_symbol(symbol: str) -> None:
    config = read_json(OUTPUT / "preregistration.json")
    if config["arms"] != {k: v.model_dump(mode="json") for k, v in policies().items()}:
        raise ValueError("R2 policy differs from registration")
    for name, expected in config["source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"implementation changed after registration: {name}")
    check(ROOT, PREVIOUS / "before")
    source, market, bars, features, _, _, folds, indices, trend = inputs(symbol)
    episodes: dict[datetime, str | None] = {}
    number = 0
    last = False
    for time, long in trend.items():
        if long and not last:
            number += 1
        episodes[time] = f"{symbol}-trend-{number}" if long else None
        last = long
    parent = OUTPUT / symbol
    parent.mkdir(exist_ok=True)
    for index, fold in enumerate(folds, 1):
        folder = parent / fold.fold_id
        if (folder / "completion.json").exists():
            verify_files(folder)
            continue
        if folder.exists() and any(folder.iterdir()):
            raise FileExistsError("partial R2 evidence must be preserved")
        folder.mkdir(exist_ok=True)
        print(
            f"R2 {symbol} {index}/14 {fold.fold_id}: four legacy ledger proofs then fixed arms",
            flush=True,
        )
        forecast, _, meta = frozen(symbol, fold)
        previous = PREVIOUS / symbol / fold.fold_id
        verify_files(previous)
        diagnostic = pl.read_parquet(previous / "forecast_diagnostics.parquet")
        evidence_hash = digest(previous / "forecast_diagnostics.parquet")
        for family, values in forecast.items():
            forecast[family] = {t: components(v, meta, evidence_hash) for t, v in values.items()}
        null: dict[datetime, EconomicForecast] = {}
        if "family" in diagnostic.columns:
            for row in diagnostic.filter(pl.col("family") == "CONSTANT").to_dicts():
                data = {k: row[k] for k in EconomicForecast.model_fields if k in row}
                value = EconomicForecast.model_validate_json(json.dumps(data, default=str))
                null[value.available_time] = components(value, meta, evidence_hash)
        forecast["CONSTANT"] = null
        allowed = set(fold.test_indices)
        common: dict[str, Any] = dict(
            root=ROOT,
            bars=tuple(b for b in bars if fold.test_start <= b.event_time < fold.test_end),
            features=features,
            feature_indices=indices,
            trend_by_time={t: v and indices[t] in allowed for t, v in trend.items()},
            market_spec=market,
            gate_policy=EconomicGatePolicy.model_validate(config["gate"]),
        )
        collection = trial_collections()
        traces: list[dict[str, Any]] = []
        proofs: list[dict[str, Any]] = []
        for arm, level in LEGACY.items():
            value, trace = replay_cat(
                spec=make_spec(symbol, fold, arm, source, config),
                level=level,
                forecasts=forecast.get("XGBOOST", {}),
                **common,
            )
            original = (
                ROOT / "artifacts/alpha_v4/walkforward"
                if symbol == "BTCUSDT"
                else SOURCE / symbol / fold.fold_id
            )
            proofs.append(
                {
                    "arm": arm,
                    "reference": "ORIGINAL_FROZEN",
                    **verify_ledger(value, original, fold, level, "cost_1"),
                }
            )
            save_result(collection, value, fold, arm)
            augment_trace(
                trace,
                arm=arm,
                family="XGBOOST",
                forecasts=forecast.get("XGBOOST", {}),
                meta=meta,
                episodes=episodes,
            )
            traces.extend(trace)
        for arm, policy in {
            **policies(),
            "NULL_A3": policies()["A3"],
            "EN_A3": policies()["A3"],
        }.items():
            family = (
                "CONSTANT" if arm == "NULL_A3" else "ELASTIC_NET" if arm == "EN_A3" else "XGBOOST"
            )
            predicted = forecast.get(family, {})
            value, trace = replay_cat(
                spec=make_spec(symbol, fold, arm, source, config),
                level=arm,
                forecasts=predicted,
                audit_policy=policy,
                **common,
            )
            if arm in {"A1", "A3"}:
                proofs.append(
                    {
                        "arm": arm,
                        "reference": "PRIOR_AUDIT_STRESS_REUSE",
                        **verify_ledger(value, previous, fold, arm, "1"),
                    }
                )
            save_result(collection, value, fold, arm)
            augment_trace(
                trace, arm=arm, family=family, forecasts=predicted, meta=meta, episodes=episodes
            )
            traces.extend(trace)
        # Stress/continuous controls are unchanged; reuse only the fully identical funded base plans.
        for name, rows in collection.items():
            old = pl.read_parquet(previous / f"{name}.parquet")
            if "scenario" in old.columns:
                rows.extend(
                    old.filter(
                        (pl.col("scenario") != "1") & pl.col("level").is_in(["A1", "A3"])
                    ).to_dicts()
                )
            table(folder / f"{name}.parquet", rows)
        table(folder / "decision_trace.parquet", traces)
        shutil.copyfile(previous / "same_fill_shadow.parquet", folder / "same_fill_shadow.parquet")
        shutil.copyfile(
            previous / "forecast_diagnostics.parquet", folder / "forecast_diagnostics.parquet"
        )
        write_json(folder / "reproduction.json", proofs)
        write_json(
            folder / "fold_contract.json",
            {
                **asdict(fold),
                "original_metadata": meta,
                "new_model_fits": 0,
                "prior_fold_completion_sha256": digest(previous / "completion.json"),
                "component_mapping_source_sha256": evidence_hash,
            },
        )
        write_json(
            folder / "completion.json",
            {
                "status": "PASS",
                "new_return_model_fits": 0,
                "new_calibration_fits": 0,
                "preregistration_sha256": config["sha256"],
                "files": {p.name: digest(p) for p in sorted(folder.iterdir()) if p.is_file()},
                "reused_stresses": "only after A1/A3 complete funded ledger equality",
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
    print(f"R2 {symbol}: all 14 folds complete", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregister", action="store_true")
    parser.add_argument("--symbol", choices=SYMBOLS)
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    if args.preregister:
        preregister()
    elif args.symbol:
        run_symbol(args.symbol)
    elif args.summarize:
        from scripts.summarize_alpha_v4_audit import summarize

        summarize(OUTPUT)
    else:
        parser.error("choose --preregister, --symbol or --summarize")


if __name__ == "__main__":
    main()
