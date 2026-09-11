"""Fixed-parameter multi-asset extension; never select configurations on these tests."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl
import yaml

from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import (
    BacktestFill,
    BacktestOrder,
    BacktestOrderResult,
    BacktestResult,
    BacktestRunSpec,
    BarEvent,
    EngineKind,
    EquityPoint,
)
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import AssetId, RunId, StrategyId, StrategyVersionId
from aegisquant.domain.values import Money
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.models.baselines import BaselineDataset
from aegisquant.research.models.economic_filter import fit_economic_filter
from aegisquant.research.models.economic_gate import CalibrationStatus, EconomicForecast
from aegisquant.research.strategies.cost_aware_trend import (
    TrendFeatures,
    build_trend_features,
    fit_training_scaler,
    trend_targets,
)
from aegisquant.research.validation.calendar_walkforward import (
    CalendarFold,
    add_months,
    calendar_walkforward,
)
from aegisquant.research.validation.cat_contract import compile_legacy_config
from aegisquant.research.validation.cat_replay import (
    USDT,
    CatMarket,
    decimal,
    executable_labels,
    load_completed_bars,
    replay_cat,
)
from scripts.run_alpha_v4_walkforward import (
    FAMILIES,
    SEED,
    digest,
    fold_row,
    json_default,
    table,
    write_json,
)


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def point_from_row(row: dict[str, Any]) -> EquityPoint:
    """Restore exact Decimals and the identifier from the declared Parquet encoding."""
    asset = row["reporting_asset_id"]
    return EquityPoint(
        time=row["time"],
        cash=Decimal(row["cash"]),
        position_value=Decimal(row["position_value"]),
        realized_pnl=Decimal(row["realized_pnl"]),
        unrealized_pnl=Decimal(row["unrealized_pnl"]),
        equity=Decimal(row["equity"]),
        reporting_asset_id=AssetId(
            cast(str, asset["value"]) if isinstance(asset, dict) else str(asset)
        ),
    )


def inputs(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    compile_legacy_config(root, multi_asset=True)
    config_path = root / "configs/research/alpha_v4_multi_asset.yaml"
    policy = cast(dict[str, Any], yaml.safe_load(config_path.read_text(encoding="utf-8")))
    if any(
        policy.get(key) is not False
        for key in ("live_trading", "order_submission_enabled", "production_ml_enabled")
    ):
        raise ValueError("multi-asset research must remain safety locked")
    if policy["trials_per_fold_per_family"] != 1 or policy["test_selection"] != "none":
        raise ValueError("only the preregistered single-fit, no-selection experiment is supported")
    source = read_json(root / "artifacts/alpha_v4_multi_asset/source_manifest.json")
    if source["config_sha256"] != digest(config_path):
        raise ValueError("pre-download universe declaration changed")
    files = [
        *sorted((root / "src/aegisquant").rglob("*.py")),
        root / "scripts/run_alpha_v4_walkforward.py",
        Path(__file__).resolve(),
        config_path,
        root / policy["strategy_config"],
        root / policy["research_config"],
        root / "artifacts/alpha_v4_multi_asset/source_manifest.json",
        *[root / row["path"] for row in source["datasets"]],
        *[
            root / f"artifacts/alpha_v4/walkforward/{name}.parquet"
            for name in (
                "fold_manifest",
                "fold_stability",
                "mtm_equity",
                "orders",
                "fills",
                "trades",
            )
        ],
    ]
    hashes = {path.relative_to(root).as_posix(): digest(path) for path in files}
    for row in source["datasets"]:
        if hashes[Path(row["path"]).as_posix()] != row["sha256"]:
            raise ValueError(f"market history changed: {row['symbol']}")
    return policy, source, hashes


def fit_fold(
    *,
    bars: tuple[BarEvent, ...],
    features: TrendFeatures,
    fold: CalendarFold,
    output: Path,
) -> tuple[dict[str, dict[datetime, EconomicForecast]], dict[str, Any]]:
    """Use the original fixed fit/calibration recipe with inert test targets."""
    labels, ends = executable_labels(bars)
    scaler = fit_training_scaler(
        features,
        np.asarray(fold.train_indices, dtype=np.int64),
        validation_start=fold.validation_start,
    )
    transformed = scaler.transform(features.values)
    boundary = add_months(fold.validation_start, 1)
    calibration = tuple(
        i
        for i in fold.validation_indices
        if features.available_times[i] < boundary - timedelta(hours=48)
        and ends[i] is not None
        and cast(datetime, ends[i]) < boundary
    )

    def dataset(chosen: tuple[int, ...], *, with_targets: bool) -> BaselineDataset:
        return BaselineDataset(
            sample_ids=tuple(str(bars[i].event_id) for i in chosen),
            timestamps=tuple(features.available_times[i] for i in chosen),
            feature_names=features.feature_names,
            features=tuple(tuple(map(float, transformed[i])) for i in chosen),
            targets=tuple(labels[i] for i in chosen) if with_targets else (0.0,) * len(chosen),
        )

    def known_cost(i: int) -> Decimal:
        return estimate_spot_transition_costs(
            available_time=bars[i].available_time,
            natr=decimal(float(features.values[i, 9])),
            quote_volume=bars[i].close * bars[i].volume,
            order_notional=Decimal("10000"),
        ).round_trip

    train = dataset(fold.train_indices, with_targets=True)
    validation = dataset(calibration, with_targets=True) if len(calibration) >= 30 else None
    inference = dataset(fold.test_indices, with_targets=False)
    targets = trend_targets(features.values[:, 0], features.valid)
    training_trend = [labels[i] for i in fold.train_indices if targets[i] > 0]
    mean = float(np.mean(training_trend)) if training_trend else 0.0
    cal_indices = [i for i in calibration if targets[i] > 0]
    truth = np.asarray([labels[i] for i in cal_indices], dtype=np.float64)
    through = max((cast(datetime, ends[i]) for i in calibration), default=fold.validation_start)
    if len(truth) >= 30:
        q10, q50, q90 = (float(v) for v in np.quantile(truth, (0.1, 0.5, 0.9)))
        probability = sum(labels[i] > float(known_cost(i)) for i in cal_indices) / len(truth)
        empirical_status = CalibrationStatus.VALIDATION_CALIBRATED
        empirical_hash = canonical_sha256(
            {
                "train_ids": train.sample_ids,
                "train_mean": mean,
                "calibration_indices": cal_indices,
                "calibration_truth": truth.tolist(),
            }
        )
    else:
        q10 = q50 = q90 = 0.0
        probability = 0.5
        empirical_status, empirical_hash = CalibrationStatus.UNAVAILABLE, None
    forecasts: dict[str, dict[datetime, EconomicForecast]] = {
        "B4": {
            time: EconomicForecast(
                expected_gross_return=decimal(mean),
                q10_return=decimal(q10),
                q50_return=decimal(q50),
                q90_return=decimal(q90),
                p_net_positive=decimal(probability),
                prediction_uncertainty=decimal((q90 - q10) / 2),
                available_time=time,
                calibration_status=empirical_status,
                calibrated_through=through if empirical_hash else None,
                calibration_sha256=empirical_hash,
            )
            for time in inference.timestamps
        }
    }
    trials: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        trial: dict[str, Any] = {
            "fold_id": fold.fold_id,
            "family": family,
            "trial_number": 1,
            "seed": SEED,
            "status": "STARTED",
            "test_targets_used": False,
            "calibration_rows": len(calibration),
        }
        trials.append(trial)
        table(output / "all_trials.parquet", trials)
        if validation is None:
            forecasts[family] = {}
            trial["status"] = "INSUFFICIENT_CALIBRATION_DATA_NO_FIT"
        else:
            fitted = fit_economic_filter(
                family=family,
                train=train,
                validation=validation,
                test=inference,
                train_label_end_times=tuple(cast(datetime, ends[i]) for i in fold.train_indices),
                validation_label_end_times=tuple(cast(datetime, ends[i]) for i in calibration),
                validation_round_trip_costs=tuple(known_cost(i) for i in calibration),
            )
            forecasts[family] = {p.available_time: p for p in fitted.forecasts}
            trial.update(
                {
                    "status": "COMPLETED",
                    "model_spec_sha256": fitted.model_spec_sha256,
                    "training_sha256": fitted.training_samples_sha256,
                    "calibration_sha256": fitted.calibration_sha256,
                    "calibration_status": fitted.calibration_status.value,
                    "predictions_sha256": canonical_sha256(
                        [p.model_dump(mode="json") for p in fitted.forecasts]
                    ),
                }
            )
            prediction_rows.extend(
                {"family": family, **p.model_dump(mode="python")} for p in fitted.forecasts
            )
        table(output / "all_trials.parquet", trials)
    table(output / "predictions.parquet", prediction_rows)
    return forecasts, {
        "train_rows": len(train.sample_ids),
        "calibration_rows": len(calibration),
        "test_rows": len(fold.test_indices),
        "calibration_end": boundary,
        "maximum_train_label_end": max(cast(datetime, ends[i]) for i in fold.train_indices),
        "maximum_calibration_label_end": through,
        "scaler_json": scaler.model_dump_json(),
        "train_indices_sha256": canonical_sha256(fold.train_indices),
        "test_indices_sha256": canonical_sha256(fold.test_indices),
        "actual_model_fits": sum(row["status"] == "COMPLETED" for row in trials),
    }


def append_result(
    collections: dict[str, list[dict[str, Any]]],
    result: BacktestResult,
    fold_id: str,
    level: str,
    scenario: str,
    base_topology: list[tuple[str, Decimal]],
) -> None:
    key = {"fold_id": fold_id, "level": level, "scenario": scenario}
    row = fold_row(result, fold_id, level, scenario)
    row["same_fill_topology"] = [
        (str(f.backtest_order_id), f.quantity.amount) for f in result.fills
    ] == base_topology
    if abs(result.cost_identity_residual) > result.cost_identity_tolerance:
        raise ValueError("multi-asset cost accounting identity failed")
    if result.forced_close_status != "NO_POSITION":
        raise ValueError("fold-end positions must have a costed exit before aggregation")
    collections["fold_stability"].append(row)
    collections["mtm_equity"].extend(
        {**key, **point.model_dump(mode="python")}
        for point in resample_equity(result.equity_curve, 14400)
    )
    for name, records in (
        ("orders", result.orders),
        ("fills", result.fills),
        ("trades", result.closed_trades),
    ):
        collections[name].extend(
            {**key, "payload_json": record.model_dump_json()} for record in records
        )
    collections["terminal_attribution"].append(
        {**key, **result.pnl_attribution[-1].model_dump(mode="python")}
    )


def run_symbol(root: Path, symbol: str) -> None:
    policy, source, hashes = inputs(root)
    parent = root / "artifacts/alpha_v4_multi_asset"
    manifest = read_json(parent / "run_manifest.json")
    if manifest["input_sha256"] != hashes:
        raise ValueError("experiment source/configuration changed after freezing")
    if symbol not in policy["symbols"]:
        raise ValueError("symbol is outside the preregistered universe")
    output = parent / symbol
    if output.exists():
        raise FileExistsError("asset experiment already started; no silent OOS rerun")
    output.mkdir()
    write_json(output / "effective_config.json", compile_legacy_config(root, multi_asset=True))
    rule = policy["execution_rules"][symbol]
    market = CatMarket(
        base_asset=AssetId(rule["base_asset"]),
        tick_size=Decimal(rule["tick_size"]),
        quantity_step=Decimal(rule["quantity_step"]),
    )
    source_row = next(row for row in source["datasets"] if row["symbol"] == symbol)
    end = datetime.fromisoformat(policy["development_end"])
    start = datetime.fromisoformat(policy["first_train_start"])
    bars = tuple(
        b
        for b in load_completed_bars(root / source_row["path"], market_spec=market)
        if start <= b.event_time < end
    )
    features = build_trend_features(bars)
    indices = {time: i for i, time in enumerate(features.available_times)}
    _, label_ends = executable_labels(bars)
    folds = calendar_walkforward(
        available_times=features.available_times,
        label_end_times=label_ends,
        valid=tuple(bool(v) for v in features.valid),
        first_train_start=start,
        development_end=end,
    )
    old = root / "artifacts/alpha_v4/walkforward"
    old_folds = pl.read_parquet(old / "fold_manifest.parquet").to_dicts()
    if [(f.fold_id, f.test_start, f.test_end) for f in folds] != [
        (f["fold_id"], f["test_start"], f["test_end"]) for f in old_folds
    ]:
        raise ValueError("asset does not share the preregistered calendar folds")
    btc = (
        {
            name: pl.read_parquet(old / f"{name}.parquet")
            for name in ("fold_stability", "mtm_equity", "orders", "fills", "trades")
        }
        if symbol == "BTCUSDT"
        else {}
    )
    targets = trend_targets(features.values[:, 0], features.valid)
    asset_manifest: dict[str, Any] = {
        "symbol": symbol,
        "status": "STARTED",
        "completed_folds": 0,
        "actual_model_fits": 0,
        "planned_fit_slots": 0 if btc else len(folds) * len(FAMILIES),
        "base_evidence": "REUSED_FROZEN_BTC" if btc else "NEW_FIXED_PARAMETER_DEVELOPMENT_OOS",
        "run_manifest_sha256": digest(parent / "run_manifest.json"),
    }
    write_json(output / "asset_manifest.json", asset_manifest)
    for number, fold in enumerate(folds, 1):
        print(f"{symbol} fold {number}/{len(folds)} {fold.fold_id}", flush=True)
        folder = output / fold.fold_id
        folder.mkdir()
        if btc:
            forecasts: dict[str, dict[datetime, EconomicForecast]] = {}
            training = {"actual_model_fits": 0, "source": "REUSED_FROZEN_BTC_NO_REFIT"}
        else:
            forecasts, training = fit_fold(bars=bars, features=features, fold=fold, output=folder)
        fold_manifest = {
            "symbol": symbol,
            "fold_id": fold.fold_id,
            "train_start": fold.train_start,
            "validation_start": fold.validation_start,
            "test_start": fold.test_start,
            "test_end": fold.test_end,
            "purge_bars": fold.purge_bars,
            "embargo_bars": fold.embargo_bars,
            **training,
        }
        write_json(folder / "fold_manifest.json", fold_manifest)
        allowed = set(fold.test_indices)
        trend = {time: bool(targets[i]) and i in allowed for time, i in indices.items()}
        test_bars = tuple(b for b in bars if fold.test_start <= b.event_time < fold.test_end)
        collections: dict[str, list[dict[str, Any]]] = {
            name: []
            for name in (
                "mtm_equity",
                "fold_stability",
                "orders",
                "fills",
                "trades",
                "decisions",
                "terminal_attribution",
            )
        }
        for level in policy["levels"]:
            spec = BacktestRunSpec(
                run_id=RunId(f"cat-multi-{symbol}-{fold.fold_id}-{level}"),
                engine_kind=EngineKind.EVENT,
                strategy_id=StrategyId(f"cat-{level.lower()}"),
                strategy_version_id=StrategyVersionId("alpha-v4-multi-asset"),
                dataset_sha256=source_row["sha256"],
                config_sha256=manifest["config_sha256"],
                code_sha256=manifest["code_sha256"],
                seed=SEED,
                reporting_asset_id=USDT,
                initial_cash=Money(amount=Decimal("10000"), asset_id=USDT),
                start_time=fold.test_start,
                end_time=fold.test_end,
                created_at=datetime.fromisoformat(manifest["frozen_at"]),
                accounting_policy_version="accounting-v1",
                cost_policy_version="cat-proxy-v1",
                rule_policy_version="cat-proxy-v1",
                metric_frequency_seconds=14400,
                reproduction_command=".venv\\Scripts\\python.exe -m scripts.run_alpha_v4_multi_asset --check",
            )
            arguments: dict[str, Any] = {
                "root": root,
                "spec": spec,
                "bars": test_bars,
                "features": features,
                "feature_indices": indices,
                "trend_by_time": trend,
                "level": level,
                "forecasts": forecasts.get(level, forecasts.get("XGBOOST", {})),
                "market_spec": market,
            }
            match = (pl.col("fold_id") == fold.fold_id) & (pl.col("level") == level)
            if btc:
                original_points = tuple(
                    point_from_row(row) for row in btc["mtm_equity"].filter(match).to_dicts()
                )
                collections["mtm_equity"].extend(
                    {
                        "fold_id": fold.fold_id,
                        "level": level,
                        "scenario": "cost_1",
                        **p.model_dump(mode="python"),
                    }
                    for p in resample_equity(original_points, 14400)
                )
                collections["fold_stability"].extend(
                    btc["fold_stability"]
                    .filter(match & (pl.col("scenario") == "cost_1"))
                    .to_dicts()
                )
                fixed: tuple[BacktestOrder, ...] = tuple(
                    BacktestOrderResult.model_validate_json(row["payload_json"]).order
                    for row in btc["orders"].filter(match).to_dicts()
                )
                original_fills = [
                    BacktestFill.model_validate_json(row["payload_json"])
                    for row in btc["fills"].filter(match).to_dicts()
                ]
                base_topology = [
                    (str(f.backtest_order_id), f.quantity.amount) for f in original_fills
                ]
                for name in ("orders", "fills", "trades"):
                    collections[name].extend(
                        {
                            "fold_id": fold.fold_id,
                            "level": level,
                            "scenario": "cost_1",
                            "payload_json": row["payload_json"]
                            if "payload_json" in row
                            else json.dumps(row, default=json_default),
                        }
                        for row in btc[name].filter(match).to_dicts()
                    )
            else:
                base, decisions = replay_cat(**arguments)
                fixed = tuple(record.order for record in base.orders)
                base_topology = [(str(f.backtest_order_id), f.quantity.amount) for f in base.fills]
                append_result(collections, base, fold.fold_id, level, "cost_1", base_topology)
                collections["decisions"].extend({"level": level, **row} for row in decisions)
            for cost in policy["cost_multipliers"]:
                if cost == "1":
                    continue
                result, _ = replay_cat(
                    **arguments, fixed_orders=fixed, cost_multiplier=Decimal(cost)
                )
                append_result(
                    collections, result, fold.fold_id, level, f"cost_{cost}", base_topology
                )
                if btc:
                    expected = btc["fold_stability"].filter(
                        match & (pl.col("scenario") == f"cost_{cost}")
                    )
                    if (
                        expected.height != 1
                        or result.mark_to_market_final_equity is None
                        or abs(
                            result.mark_to_market_final_equity
                            - Decimal(expected["mtm_final_equity"][0])
                        )
                        > Decimal("1e-8")
                    ):
                        raise ValueError(
                            "frozen BTC order cost replay changed the previous economic result"
                        )
            print(f"  {level}: base and fixed-order costs complete", flush=True)
        for name, rows in collections.items():
            table(folder / f"{name}.parquet", rows)
        write_json(
            folder / "completion.json",
            {
                "status": "COMPLETED",
                "files": {p.name: digest(p) for p in sorted(folder.iterdir())},
            },
        )
        asset_manifest["completed_folds"] = number
        asset_manifest["actual_model_fits"] += training["actual_model_fits"]
        write_json(output / "asset_manifest.json", asset_manifest)
    asset_manifest["status"] = "COMPLETED"
    write_json(output / "asset_manifest.json", asset_manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--symbol")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    parent = root / "artifacts/alpha_v4_multi_asset"
    if args.symbol:
        run_symbol(root, args.symbol)
        return 0
    policy, _, hashes = inputs(root)
    manifest_path = parent / "run_manifest.json"
    if args.initialize:
        if manifest_path.exists():
            raise FileExistsError("experiment already frozen")
        write_json(
            manifest_path,
            {
                "version": policy["version"],
                "frozen_at": datetime.now(UTC).isoformat(),
                "policy": policy,
                "input_sha256": hashes,
                "config_sha256": canonical_sha256(
                    {k: v for k, v in hashes.items() if k.startswith("configs/")}
                ),
                "code_sha256": canonical_sha256(
                    {k: v for k, v in hashes.items() if k.endswith(".py")}
                ),
                "final_holdout_access_count": 0,
                "hyperparameter_optimizer_started": False,
                "cost_stress_semantics": "funded frozen base orders; refusals and changed fills retained",
                "execution_evidence": "BAR_AND_DECLARED_PRECISION_PROXY_NOT_HISTORICAL_EXCHANGE_RULE_PROOF",
            },
        )
        print("fixed multi-asset experiment frozen before any new model fit")
        return 0
    if read_json(manifest_path)["input_sha256"] != hashes:
        raise ValueError("frozen experiment inputs changed")
    for symbol in policy["symbols"]:
        folder = parent / symbol
        if read_json(folder / "asset_manifest.json")["status"] != "COMPLETED":
            raise ValueError(f"incomplete asset run: {symbol}")
        for path in sorted(folder.glob("*/completion.json")):
            for name, expected_hash in read_json(path)["files"].items():
                if digest(path.parent / name) != expected_hash:
                    raise ValueError(f"asset evidence hash changed: {path.parent / name}")
    print("five fixed-parameter asset experiments and all sealed fold artifacts verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
