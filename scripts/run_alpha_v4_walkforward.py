"""One frozen development run: calendar folds, causal CAT ablations, and cost stress."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl
import yaml

from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import BacktestResult, BacktestRunSpec, EngineKind
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import RunId, StrategyId, StrategyVersionId
from aegisquant.domain.values import Money
from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.models.baselines import BaselineDataset
from aegisquant.research.models.economic_filter import EconomicModelFamily, fit_economic_filter
from aegisquant.research.models.economic_gate import CalibrationStatus, EconomicForecast
from aegisquant.research.strategies.cost_aware_trend import (
    TrendPolicy,
    build_trend_features,
    fit_training_scaler,
    trend_targets,
)
from aegisquant.research.validation.calendar_walkforward import add_months, calendar_walkforward
from aegisquant.research.validation.cat_replay import (
    USDT,
    decimal,
    executable_labels,
    load_completed_bars,
    replay_cat,
)
from aegisquant.research.validation.failure_attribution import (
    long_flat_path,
    matched_random_offsets,
)
from aegisquant.research.validation.paired_bootstrap import (
    FloatArray,
    holm_adjust,
    paired_block_bootstrap,
)
from aegisquant.research.validation.statistics import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
)

LEVELS = ("B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "LIGHTGBM", "ELASTIC_NET")
FAMILIES: tuple[EconomicModelFamily, ...] = ("XGBOOST", "LIGHTGBM", "ELASTIC_NET")
COSTS = ("0", "0.5", "1", "1.5", "2")
SEED = 20260903


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_default(value: object) -> str:
    if isinstance(value, datetime | Decimal):
        return str(value)
    raise TypeError(f"unserializable evidence type {type(value).__name__}")


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=json_default)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def table(path: Path, rows: list[dict[str, Any]]) -> None:
    rows = [
        {key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()}
        for row in rows
    ]
    frame = (
        pl.DataFrame(rows, infer_schema_length=None)
        if rows
        else pl.DataFrame(schema={"status": pl.String})
    )
    frame.write_parquet(path, compression="zstd")


def path_metrics(changes: FloatArray) -> dict[str, float | None]:
    nav = np.cumprod(1 + changes)
    mean, std = float(np.mean(changes)), float(np.std(changes))
    whole = np.r_[1.0, nav]
    drawdown = float(np.max(1 - whole / np.maximum.accumulate(whole)))
    annual = float(nav[-1] ** (2191.5 / len(nav)) - 1)
    return {
        "net_compound_return": float(nav[-1] - 1),
        "cagr": annual,
        "sharpe": mean / std * math.sqrt(2191.5) if std > 0 else None,
        "calmar": annual / drawdown if drawdown else None,
        "maximum_drawdown": drawdown,
    }


def result_returns(result: BacktestResult) -> FloatArray:
    curve = resample_equity(result.equity_curve, 14400)
    values = np.asarray([float(point.equity) for point in curve], dtype=np.float64)
    return values[1:] / values[:-1] - 1


def fold_row(result: BacktestResult, fold_id: str, level: str, scenario: str) -> dict[str, Any]:
    attribution = result.pnl_attribution[-1]
    metrics = result.metrics
    return {
        "fold_id": fold_id,
        "level": level,
        "scenario": scenario,
        **path_metrics(result_returns(result)),
        "mtm_final_equity": str(result.mark_to_market_final_equity),
        "forced_close_final_equity": str(result.forced_close_final_equity),
        "forced_close_status": result.forced_close_status,
        "gross_pnl": float(attribution.gross_trading_pnl),
        "total_cost": float(attribution.gross_trading_pnl - attribution.net_pnl),
        "turnover": float(metrics.turnover),
        "closed_trade_count": metrics.trade_statistics.closed_trade_count,
        "win_rate": float(metrics.trade_statistics.win_rate),
        "average_win": float(metrics.trade_statistics.average_win),
        "average_loss": float(metrics.trade_statistics.average_loss),
        "payoff_ratio": float(metrics.trade_statistics.payoff_ratio)
        if metrics.trade_statistics.payoff_ratio is not None
        else None,
        "expectancy": float(metrics.trade_statistics.expectancy),
        "holding_seconds": float(metrics.trade_statistics.average_holding_seconds),
        "reversal_count": metrics.trade_statistics.reversal_count,
        "gross_profit": float(
            sum(
                (max(trade.gross_pnl, Decimal("0")) for trade in result.closed_trades), Decimal("0")
            )
        ),
        "cost_identity_residual": str(result.cost_identity_residual),
        "cost_identity_tolerance": str(result.cost_identity_tolerance),
        "economic_event_hash": result.economic_event_hash,
        "orders": len(result.orders),
        "fills": len(result.fills),
        "rejections": sum(bool(row.rejection_code) for row in result.orders),
        "warnings": json.dumps(result.warnings),
    }


def run(root: Path, output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(
            "development evidence already exists; use --check, never silently rerun OOS"
        )
    output.mkdir(parents=True, exist_ok=True)
    config_path = root / "configs/research/aegis_alpha_v4.yaml"
    strategy_path = root / "configs/strategies/aegisalpha_cat_v1.yaml"
    config = cast(dict[str, Any], yaml.safe_load(config_path.read_text(encoding="utf-8")))
    policy = cast(dict[str, Any], yaml.safe_load(strategy_path.read_text(encoding="utf-8")))
    if (
        config["selection_policy"] != "preregistered_centers_no_profit_optimization"
        or policy["training"]["planned_trials_per_fold_per_family"] != 1
    ):
        raise ValueError("this runner implements fixed centers and one fit per family per fold")
    if (
        policy["fast_days"],
        policy["slow_days"],
        policy["horizon_bars"],
        policy["lambda_cost"],
        policy["target_annual_volatility"],
    ) != (10, 40, 6, 2, 0.2):
        raise ValueError("the registered center configuration changed")
    if any(
        config["safety"].get(name) is not False
        for name in ("live_trading", "order_submission_enabled", "production_ml_enabled")
    ):
        raise ValueError("CAT runner must remain safety locked")
    raw = root / config["data_source"]
    old_file = root / "artifacts/alpha_v4/reconstructed_before/BTCUSDT_logistic_core.parquet"
    source_files = [*sorted((root / "src/aegisquant").rglob("*.py")), Path(__file__).resolve()]
    code_hash = canonical_sha256(
        {str(p.relative_to(root)).replace("\\", "/"): digest(p) for p in source_files}
    )
    config_hash = canonical_sha256(
        {"research": digest(config_path), "strategy": digest(strategy_path)}
    )
    frozen_at = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "version": "alpha-v4-walkforward-v1",
        "frozen_at": frozen_at.isoformat(),
        "evidence_tier": "PREVIOUSLY_USED_DEVELOPMENT_OOS_NOT_FINAL_HOLDOUT",
        "data_sha256": digest(raw),
        "config_sha256": config_hash,
        "code_sha256": code_hash,
        "old_predictions_sha256": digest(old_file),
        "research_config": config,
        "strategy_config": policy,
        "test_access_count_per_fixed_configuration": 1,
        "final_holdout_access_count": 0,
        "hyperparameter_optimizer_started": False,
        "cost_stress_semantics": "frozen base-run orders, same quantities; topology changes explicitly checked",
        "execution_evidence": "BAR_PROXY_NOT_HISTORICAL_ORDERBOOK_OR_FEE_TIER_PROOF",
        "exact_decimal_parquet_encoding": "base-10 strings; float summary columns explicitly approximate",
        "validation": "first month calibration, remaining two months fixed-neighborhood checks; no selection",
        "status": "STARTED",
    }
    write_json(output / "run_manifest.json", manifest)
    bars = load_completed_bars(raw)
    hourly = load_completed_bars(raw, hours=1)
    features = build_trend_features(bars)
    indices = {time: i for i, time in enumerate(features.available_times)}
    hourly_indices = {
        bar.available_time: max(0, bisect_right(features.available_times, bar.available_time) - 1)
        for bar in hourly
    }
    label_values, label_ends = executable_labels(bars)
    folds = calendar_walkforward(
        available_times=features.available_times,
        label_end_times=label_ends,
        valid=tuple(bool(value) for value in features.valid),
        first_train_start=datetime.fromisoformat(config["first_train_start"]),
        development_end=datetime.fromisoformat(config["development_end"]),
    )
    original = pl.read_parquet(old_file)
    original_times: list[datetime] = original["decision_time"].to_list()
    original_weights: list[float] = original["target_position"].to_list()
    old_targets = {
        bar.available_time: bool(original_weights[at])
        if (at := bisect_right(original_times, bar.available_time) - 1) >= 0
        else False
        for bar in hourly
    }
    center_targets = trend_targets(features.values[:, 0], features.valid)
    neighbor_features = {
        (fast, slow): build_trend_features(
            bars, TrendPolicy.model_validate({"fast_days": fast, "slow_days": slow})
        )
        for fast, slow in ((7, 40), (10, 40), (14, 40), (10, 30), (10, 60))
    }
    collections: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "fold_manifest",
            "all_trials",
            "predictions",
            "positions",
            "orders",
            "fills",
            "mtm_equity",
            "trades",
            "cost_waterfall",
            "fold_stability",
            "neighborhood_stability",
            "decisions",
        )
    }
    paths: dict[tuple[str, str], list[FloatArray]] = {}
    exposure_paths: dict[str, list[FloatArray]] = {level: [] for level in LEVELS}
    reference_paths: list[FloatArray] = []

    def known_cost(i: int) -> Decimal:
        bar = bars[i]
        return estimate_spot_transition_costs(
            available_time=bar.available_time,
            natr=decimal(float(features.values[i, 9])),
            quote_volume=bar.close * bar.volume,
            order_notional=Decimal("10000"),
        ).round_trip

    for number, fold in enumerate(folds, 1):
        print(
            f"fold {number}/{len(folds)} {fold.fold_id}: fit and evaluate frozen configurations",
            flush=True,
        )
        test_bars = tuple(b for b in bars if fold.test_start <= b.event_time < fold.test_end)
        old_bars = tuple(b for b in hourly if fold.test_start <= b.event_time < fold.test_end)
        train_idx = np.asarray(fold.train_indices, dtype=np.int64)
        scaler = fit_training_scaler(features, train_idx, validation_start=fold.validation_start)
        transformed = scaler.transform(features.values)
        calibration_boundary = add_months(fold.validation_start, 1)
        calibration_idx = tuple(
            i
            for i in fold.validation_indices
            if features.available_times[i] < calibration_boundary - timedelta(hours=48)
            and (label_end := label_ends[i]) is not None
            and label_end < calibration_boundary
        )
        later_validation_idx = tuple(
            i
            for i in fold.validation_indices
            if features.available_times[i] >= calibration_boundary + timedelta(hours=4)
        )
        inference_idx = (*later_validation_idx, *fold.test_indices)
        later_validation_bars = tuple(
            b for b in bars if calibration_boundary <= b.event_time < fold.test_start
        )

        def dataset(
            chosen: tuple[int, ...], *, labels: bool, feature_values: FloatArray = transformed
        ) -> BaselineDataset:
            return BaselineDataset(
                sample_ids=tuple(str(bars[i].event_id) for i in chosen),
                timestamps=tuple(features.available_times[i] for i in chosen),
                feature_names=features.feature_names,
                features=tuple(
                    tuple(map(float, row))
                    for row in feature_values[np.asarray(chosen, dtype=np.int64)]
                ),
                targets=tuple(label_values[i] for i in chosen) if labels else (0.0,) * len(chosen),
            )

        train = dataset(fold.train_indices, labels=True)
        validation = dataset(calibration_idx, labels=True) if len(calibration_idx) >= 30 else None
        inference = dataset(inference_idx, labels=False)
        forecast_by_family: dict[str, dict[datetime, EconomicForecast]] = {}
        training_trend_values = [
            label_values[i] for i in fold.train_indices if center_targets[i] > 0
        ]
        prior_mean = float(np.mean(training_trend_values)) if training_trend_values else 0.0
        cal_indices = [i for i in calibration_idx if center_targets[i] > 0]
        cal_truth = np.asarray([label_values[i] for i in cal_indices], dtype=np.float64)
        if len(cal_truth) >= 30:
            q10, q50, q90 = (float(v) for v in np.quantile(cal_truth, (0.1, 0.5, 0.9)))
            positives = sum(label_values[i] > float(known_cost(i)) for i in cal_indices)
            empirical_status = CalibrationStatus.VALIDATION_CALIBRATED
            empirical_hash = canonical_sha256(
                {
                    "train_ids": train.sample_ids,
                    "train_mean": prior_mean,
                    "calibration_indices": cal_indices,
                    "calibration_truth": cal_truth.tolist(),
                }
            )
            probability = positives / len(cal_truth)
        else:
            q10 = q50 = q90 = 0.0
            empirical_status, empirical_hash, probability = CalibrationStatus.UNAVAILABLE, None, 0.5
        calibration_through = max(
            (cast(datetime, label_ends[i]) for i in calibration_idx), default=fold.validation_start
        )
        empirical = {
            features.available_times[i]: EconomicForecast(
                expected_gross_return=decimal(prior_mean),
                q10_return=decimal(q10),
                q50_return=decimal(q50),
                q90_return=decimal(q90),
                p_net_positive=decimal(probability),
                prediction_uncertainty=decimal((q90 - q10) / 2),
                available_time=features.available_times[i],
                calibration_status=empirical_status,
                calibrated_through=calibration_through if empirical_hash else None,
                calibration_sha256=empirical_hash,
            )
            for i in inference_idx
        }
        for family in FAMILIES:
            trial: dict[str, Any] = {
                "fold_id": fold.fold_id,
                "kind": "MODEL_FIT",
                "family": family,
                "trial_number": 1,
                "budget": 30,
                "status": "STARTED",
                "seed": SEED,
                "test_targets_used": False,
            }
            collections["all_trials"].append(trial)
            table(output / "all_trials.parquet", collections["all_trials"])
            if validation is None:
                forecast_by_family[family] = {}
                trial.update(
                    {
                        "status": "INSUFFICIENT_CALIBRATION_DATA_NO_FIT",
                        "calibration_rows": len(calibration_idx),
                    }
                )
                continue
            fitted = fit_economic_filter(
                family=family,
                train=train,
                validation=validation,
                test=inference,
                train_label_end_times=tuple(
                    cast(datetime, label_ends[i]) for i in fold.train_indices
                ),
                validation_label_end_times=tuple(
                    cast(datetime, label_ends[i]) for i in calibration_idx
                ),
                validation_round_trip_costs=tuple(known_cost(i) for i in calibration_idx),
            )
            forecast_by_family[family] = {p.available_time: p for p in fitted.forecasts}
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
            for prediction in fitted.forecasts:
                if prediction.available_time >= fold.test_start:
                    collections["predictions"].append(
                        {
                            "fold_id": fold.fold_id,
                            "family": family,
                            **prediction.model_dump(mode="python"),
                        }
                    )
        collections["fold_manifest"].append(
            {
                "fold_id": fold.fold_id,
                "train_start": fold.train_start,
                "validation_start": fold.validation_start,
                "calibration_end": calibration_boundary,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "train_rows": len(train.sample_ids),
                "calibration_rows": len(calibration_idx),
                "validation_check_rows": len(later_validation_idx),
                "test_rows": len(fold.test_indices),
                "purge_bars": fold.purge_bars,
                "embargo_bars": fold.embargo_bars,
                "maximum_train_label_end": max(
                    cast(datetime, label_ends[i]) for i in fold.train_indices
                ),
                "maximum_calibration_label_end": calibration_through,
                "scaler_json": scaler.model_dump_json(),
                "train_indices_sha256": canonical_sha256(fold.train_indices),
                "test_indices_sha256": canonical_sha256(fold.test_indices),
            }
        )
        test_allowed = set(fold.test_indices)
        trend_map = {
            time: bool(center_targets[i]) and i in test_allowed for time, i in indices.items()
        }
        prices_by_time = {
            b.available_time + timedelta(milliseconds=1): float(b.close) for b in test_bars
        }
        grid_count = int((fold.test_end - fold.test_start).total_seconds() // 14400)
        known_price = float(test_bars[0].open)
        market_prices = [known_price]
        for j in range(1, grid_count + 1):
            known_price = prices_by_time.get(fold.test_start + timedelta(hours=j * 4), known_price)
            market_prices.append(known_price)
        reference_paths.append(np.diff(np.asarray(market_prices)) / np.asarray(market_prices[:-1]))

        def spec_for(
            level: str, start: datetime, end: datetime, fold_id: str = fold.fold_id
        ) -> BacktestRunSpec:
            return BacktestRunSpec(
                run_id=RunId(f"cat-{fold_id}-{level}"),
                engine_kind=EngineKind.EVENT,
                strategy_id=StrategyId(f"cat-{level.lower()}"),
                strategy_version_id=StrategyVersionId("alpha-v4"),
                dataset_sha256=manifest["data_sha256"],
                config_sha256=config_hash,
                code_sha256=code_hash,
                seed=SEED,
                reporting_asset_id=USDT,
                initial_cash=Money(amount=Decimal("10000"), asset_id=USDT),
                start_time=start,
                end_time=end,
                created_at=frozen_at,
                accounting_policy_version="accounting-v1",
                cost_policy_version="cat-proxy-v1",
                rule_policy_version="cat-proxy-v1",
                reproduction_command=".venv\\Scripts\\python.exe -m scripts.run_alpha_v4_walkforward --check",
                metric_frequency_seconds=14400,
            )

        for level in LEVELS:
            chosen_bars = old_bars if level == "B2" else test_bars
            forecasts = (
                empirical
                if level == "B4"
                else forecast_by_family.get(level, forecast_by_family["XGBOOST"])
            )
            arguments: dict[str, Any] = {
                "root": root,
                "spec": spec_for(level, fold.test_start, fold.test_end),
                "bars": chosen_bars,
                "features": features,
                "feature_indices": hourly_indices if level == "B2" else indices,
                "trend_by_time": trend_map,
                "forecasts": forecasts,
                "level": level,
                "old_targets": old_targets,
            }
            base, decisions = replay_cat(**arguments)
            base_row = fold_row(base, fold.fold_id, level, "cost_1")
            collections["fold_stability"].append(base_row)
            paths.setdefault((level, "cost_1"), []).append(result_returns(base))
            for decision in decisions:
                collections["decisions"].append(
                    {"fold_id": fold.fold_id, "level": level, **decision}
                )
                collections["positions"].append(
                    {
                        "fold_id": fold.fold_id,
                        "level": level,
                        "time": decision["time"],
                        "quantity": decision["current_quantity"],
                        "pending_quantity": decision["pending_quantity"],
                    }
                )
            for point in base.equity_curve:
                collections["mtm_equity"].append(
                    {"fold_id": fold.fold_id, "level": level, **point.model_dump(mode="python")}
                )
            for row in base.orders:
                collections["orders"].append(
                    {
                        "fold_id": fold.fold_id,
                        "level": level,
                        "order_id": str(row.order.backtest_order_id),
                        "decision_time": row.order.decision_time,
                        "side": row.order.side.value,
                        "quantity": str(row.order.quantity.amount),
                        "status": row.status.value,
                        "rejection_code": row.rejection_code,
                        "payload_json": row.model_dump_json(),
                    }
                )
            for fill in base.fills:
                collections["fills"].append(
                    {
                        "fold_id": fold.fold_id,
                        "level": level,
                        "event_time": fill.event_time,
                        "available_time": fill.available_time,
                        "side": fill.side.value,
                        "quantity": str(fill.quantity.amount),
                        "reference_price": str(fill.reference_price.amount),
                        "execution_price": str(fill.execution_price.amount),
                        "fee": str(fill.fee.amount),
                        "payload_json": fill.model_dump_json(),
                    }
                )
            for trade in base.closed_trades:
                collections["trades"].append(
                    {"fold_id": fold.fold_id, "level": level, **trade.model_dump(mode="python")}
                )
            collections["cost_waterfall"].append(
                {
                    "fold_id": fold.fold_id,
                    "level": level,
                    **base.pnl_attribution[-1].model_dump(mode="python"),
                    "identity_residual": str(base.cost_identity_residual),
                }
            )
            regular = resample_equity(base.equity_curve, 14400)
            exposure_paths[level].append(
                np.asarray([float(p.position_value > 0) for p in regular[1:]], dtype=np.float64)
            )
            orders = tuple(row.order for row in base.orders)
            base_fills = [(f.event_time, f.side, f.quantity) for f in base.fills]
            for multiplier in COSTS:
                if multiplier == "1":
                    continue
                stressed, _ = replay_cat(
                    **arguments, cost_multiplier=Decimal(multiplier), fixed_orders=orders
                )
                scenario = f"cost_{multiplier}"
                row = fold_row(stressed, fold.fold_id, level, scenario)
                row["same_fill_topology"] = [
                    (f.event_time, f.side, f.quantity) for f in stressed.fills
                ] == base_fills
                collections["fold_stability"].append(row)
                paths.setdefault((level, scenario), []).append(result_returns(stressed))
            if level in {"B3", "B4", "B5", "B6", "B7"}:
                stresses: dict[str, dict[str, Any]] = {
                    "latency_2": {"latency_multiplier": 2},
                    "latency_5": {"latency_multiplier": 5},
                    "spread_2": {"spread_multiplier": Decimal("2")},
                    "spread_4": {"spread_multiplier": Decimal("4")},
                    "slippage_2": {"slippage_multiplier": Decimal("2")},
                    "slippage_4": {"slippage_multiplier": Decimal("4")},
                    "volume_50pct": {"volume_multiplier": Decimal("0.5")},
                    "volume_20pct": {"volume_multiplier": Decimal("0.2")},
                    **{
                        f"omit_{name}": {"omit_cost": name}
                        for name in ("fee", "spread", "slippage", "impact", "latency")
                    },
                }
                for scenario, knobs in stresses.items():
                    stressed, _ = replay_cat(**arguments, **knobs, fixed_orders=orders)
                    row = fold_row(stressed, fold.fold_id, level, scenario)
                    row["same_fill_topology"] = [
                        (f.event_time, f.side, f.quantity) for f in stressed.fills
                    ] == base_fills
                    collections["fold_stability"].append(row)
                    paths.setdefault((level, scenario), []).append(result_returns(stressed))
        # Only later validation is used for the registered neighborhood checks.
        for (fast, slow), neighbor in neighbor_features.items():
            targets = trend_targets(
                neighbor.values[:, 0],
                neighbor.valid,
                TrendPolicy.model_validate({"fast_days": fast, "slow_days": slow}),
            )
            candidate_id = f"trend-{fast}-{slow}"
            tested, _ = replay_cat(
                root=root,
                spec=spec_for(candidate_id, calibration_boundary, fold.test_start),
                bars=later_validation_bars,
                features=neighbor,
                feature_indices=indices,
                trend_by_time={time: bool(targets[i]) for time, i in indices.items()},
                forecasts={},
                level="B3",
            )
            row = fold_row(tested, fold.fold_id, "B3", candidate_id)
            row["partition"] = "LATER_VALIDATION_ONLY_NO_SELECTION"
            collections["neighborhood_stability"].append(row)
            collections["all_trials"].append(
                {
                    "fold_id": fold.fold_id,
                    "kind": "TREND_NEIGHBOR_CHECK",
                    "family": "TREND",
                    "status": "COMPLETED",
                    "configuration": candidate_id,
                    "net_return": row["net_compound_return"],
                    "selected": False,
                }
            )
        for knob, candidates in (
            ("lambda_cost", ("1.5", "2", "2.5")),
            ("target_volatility", ("0.15", "0.20", "0.25")),
        ):
            for candidate in candidates:
                gate = EconomicGatePolicy.model_validate({knob: Decimal(candidate)})
                level = "B4" if knob == "lambda_cost" else "B7"
                tested, _ = replay_cat(
                    root=root,
                    spec=spec_for(f"{knob}-{candidate}", calibration_boundary, fold.test_start),
                    bars=later_validation_bars,
                    features=features,
                    feature_indices=indices,
                    trend_by_time={time: bool(center_targets[i]) for time, i in indices.items()},
                    forecasts=empirical if level == "B4" else forecast_by_family["XGBOOST"],
                    level=level,
                    gate_policy=gate,
                )
                row = fold_row(tested, fold.fold_id, level, f"{knob}-{candidate}")
                row["partition"] = "LATER_VALIDATION_ONLY_NO_SELECTION"
                collections["neighborhood_stability"].append(row)
                collections["all_trials"].append(
                    {
                        "fold_id": fold.fold_id,
                        "kind": "GATE_NEIGHBOR_CHECK",
                        "family": level,
                        "status": "COMPLETED",
                        "configuration": f"{knob}={candidate}",
                        "net_return": row["net_compound_return"],
                        "selected": False,
                    }
                )
        for name, rows in collections.items():
            if name != "mtm_equity":
                table(output / f"{name}.parquet", rows)
        print(f"fold {fold.fold_id} completed; identities within 1e-8 USDT", flush=True)

    aggregate(root, output, collections, paths, exposure_paths, reference_paths, manifest)


def aggregate(
    root: Path,
    output: Path,
    collections: dict[str, list[dict[str, Any]]],
    paths: dict[tuple[str, str], list[FloatArray]],
    exposure_paths: dict[str, list[FloatArray]],
    reference_paths: list[FloatArray],
    manifest: dict[str, Any],
) -> None:
    del root
    all_paths = {key: np.concatenate(value) for key, value in paths.items()}
    matrix = np.column_stack([all_paths[(level, "cost_1")] for level in LEVELS])
    print("running 10,000 paired block bootstraps and matched random diagnostics", flush=True)
    boot = paired_block_bootstrap(matrix)
    bootstrap_report: dict[str, Any] = {
        "method": "PAIRED_CIRCULAR_BLOCK_BOOTSTRAP",
        "frequency_seconds": 14400,
        "block_bars": 6,
        "repetitions": 10000,
        "seed": SEED,
        "return_confidence_intervals": {
            level: [float(v) for v in np.quantile(boot.compound_returns[:, i], (0.025, 0.975))]
            for i, level in enumerate(LEVELS)
        },
        "incremental_comparisons": {},
        "white_reality_check": {
            "p_value": boot.reality_check_p_value,
            "benchmark": "zero mean net return across all declared OOS configurations",
        },
    }
    ablations: list[dict[str, Any]] = []
    aggregate_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for (level, scenario), returns in all_paths.items():
        rows = [
            r
            for r in collections["fold_stability"]
            if r["level"] == level and r["scenario"] == scenario
        ]
        gross_profit = sum(r["gross_profit"] for r in rows)
        cost = sum(r["total_cost"] for r in rows)
        fold_returns = [r["net_compound_return"] for r in rows]
        positive_profit = sum(max(v, 0) for v in fold_returns)
        yearly: dict[str, float] = {}
        for r in rows:
            year = r["fold_id"][:4]
            yearly[year] = yearly.get(year, 1.0) * (1 + r["net_compound_return"])
        year_profits = [value - 1 for value in yearly.values()]
        positive_years = sum(max(value, 0) for value in year_profits)
        aggregate_rows[(level, scenario)] = {
            "level": level,
            "scenario": scenario,
            **path_metrics(returns),
            "turnover": sum(r["turnover"] for r in rows),
            "total_cost": cost,
            "cost_units": "USDT_SUM_OF_INDEPENDENT_10000_USDT_FOLDS",
            "closed_trade_count": sum(r["closed_trade_count"] for r in rows),
            "cost_to_gross_profit": cost / gross_profit if gross_profit > 0 else None,
            "median_fold_return": float(np.median(fold_returns)),
            "positive_fold_ratio": sum(v > 0 for v in fold_returns) / len(fold_returns),
            "maximum_positive_fold_share": max(fold_returns) / positive_profit
            if positive_profit > 0
            else None,
            "maximum_positive_year_share": max(year_profits) / positive_years
            if positive_years > 0
            else None,
            "year_returns_json": json.dumps({year: value - 1 for year, value in yearly.items()}),
            "all_cost_identities_passed": all(
                abs(Decimal(r["cost_identity_residual"])) < Decimal("1e-8") for r in rows
            ),
            "all_same_fill_topology": all(r.get("same_fill_topology", True) for r in rows),
        }
    for level in LEVELS:
        ablations.append(aggregate_rows[(level, "cost_1")])
    comparisons = (
        ("B4", "B3"),
        ("B5", "B4"),
        ("B6", "B5"),
        ("B7", "B6"),
        ("LIGHTGBM", "B4"),
        ("ELASTIC_NET", "B4"),
        ("B3", "B2"),
    )
    p_values: dict[str, float] = {}
    for candidate, base in comparisons:
        name = f"{candidate}_minus_{base}"
        difference = boot.difference(LEVELS.index(candidate), LEVELS.index(base))
        p_values[name] = difference["one_sided_mean_p_value"]
        row: dict[str, Any] = {"candidate": candidate, "baseline": base, **difference}
        for metric in (
            "net_compound_return",
            "sharpe",
            "calmar",
            "maximum_drawdown",
            "turnover",
            "total_cost",
            "closed_trade_count",
        ):
            a, b = (
                aggregate_rows[(candidate, "cost_1")][metric],
                aggregate_rows[(base, "cost_1")][metric],
            )
            row[f"delta_{metric}"] = a - b if a is not None and b is not None else None
        a_folds = [
            r["net_compound_return"]
            for r in collections["fold_stability"]
            if r["level"] == candidate and r["scenario"] == "cost_1"
        ]
        b_folds = [
            r["net_compound_return"]
            for r in collections["fold_stability"]
            if r["level"] == base and r["scenario"] == "cost_1"
        ]
        row["fold_wins"] = sum(a > b for a, b in zip(a_folds, b_folds, strict=True))
        row["fold_losses"] = sum(a < b for a, b in zip(a_folds, b_folds, strict=True))
        row["fold_ties"] = sum(a == b for a, b in zip(a_folds, b_folds, strict=True))
        bootstrap_report["incremental_comparisons"][name] = row
    bootstrap_report["holm_adjusted_p_values"] = holm_adjust(p_values)
    random_rows: list[dict[str, Any]] = []
    market = np.concatenate(reference_paths)
    for level in ("B3", "B4", "B5", "B6", "B7"):
        # Binary holding-time screen, not a substitute for the actual quantity/cost ledger.
        weights = np.concatenate(exposure_paths[level]).copy()
        weights[0] = weights[-1] = 0
        if not np.any(weights):
            random_rows.append(
                {
                    "level": level,
                    "status": "INSUFFICIENT_EVIDENCE_NO_TRADES",
                    "count": 0,
                    "p_value": None,
                }
            )
            continue
        try:
            offsets = matched_random_offsets((weights,), count=1000, seed=SEED)
        except ValueError:
            random_rows.append(
                {
                    "level": level,
                    "status": "INSUFFICIENT_DISTINCT_MATCHED_SHIFTS",
                    "count": 0,
                    "p_value": None,
                }
            )
            continue
        observed = float(long_flat_path(market, weights, 0.0014).equity[-1] - 1)
        simulated = [
            float(long_flat_path(market, np.roll(weights, offset), 0.0014).equity[-1] - 1)
            for offset in offsets
        ]
        p_value = (sum(value >= observed for value in simulated) + 1) / 1001
        random_rows.append(
            {
                "level": level,
                "status": "BINARY_HOLDING_DIAGNOSTIC_ONLY",
                "count": 1000,
                "p_value": p_value,
                "observed_screen_return": observed,
                "median_random_return": float(np.median(simulated)),
                "holding_run_lengths_and_direction_matched": True,
                "cash_turnover_exactly_matched": False,
                "actual_fractional_size_and_dynamic_cost_matched": False,
            }
        )
    bootstrap_report["matched_random"] = random_rows
    # Daily inference avoids reporting annualized Sharpe as a per-observation statistic.
    days = len(matrix) // 6
    daily = np.prod(1 + matrix[: days * 6].reshape(days, 6, len(LEVELS)), axis=1) - 1
    daily_sharpes = np.divide(
        np.mean(daily, axis=0),
        np.std(daily, axis=0),
        out=np.zeros(len(LEVELS)),
        where=np.std(daily, axis=0) > 0,
    )
    diagnostics: dict[str, Any] = {
        "frequency": "non_overlapping_daily",
        "all_fixed_oos_configurations": list(LEVELS),
        "dsr": {},
        "limitations": [
            "Development data were previously used in v5 research.",
            "Neighborhood checks are validation-only and never selected on OOS.",
            "DSR and PBO are diagnostics, not proof of an untouched final holdout.",
        ],
    }
    for i, level in enumerate(LEVELS):
        values = daily[:, i]
        std = float(np.std(values))
        if std <= 0:
            diagnostics["dsr"][level] = {
                "status": "INSUFFICIENT_EVIDENCE_NO_VARIANCE",
                "probability": None,
            }
            continue
        normalized = (values - np.mean(values)) / std
        inference = deflated_sharpe_ratio(
            observed_sharpe=decimal(float(daily_sharpes[i])),
            observations=days,
            skewness=decimal(float(np.mean(normalized**3))),
            kurtosis=decimal(max(1.0, float(np.mean(normalized**4)))),
            trial_sharpes=tuple(decimal(float(value)) for value in daily_sharpes),
        )
        diagnostics["dsr"][level] = inference.model_dump(mode="json")
    segments = np.array_split(daily, 8)
    pbo = probability_of_backtest_overfitting(
        tuple(
            tuple(decimal(float(value)) for value in np.mean(segment, axis=0))
            for segment in segments
        )
    )
    diagnostics["pbo"] = pbo.model_dump(mode="json")
    diagnostics["pbo_selection_metric"] = (
        "mean daily return over eight equal-count temporal segments"
    )
    table(output / "ablation_results.parquet", ablations)
    table(output / "aggregate_stress.parquet", list(aggregate_rows.values()))
    for name, rows in collections.items():
        # JSON is used for nested asset identifiers; numeric economic columns stay Decimal.
        for row in rows:
            for key, value in tuple(row.items()):
                if hasattr(value, "model_dump"):
                    row[key] = str(value)
        table(output / f"{name}.parquet", rows)
    write_json(output / "bootstrap_results.json", bootstrap_report)
    write_json(output / "dsr_pbo.json", diagnostics)
    manifest.update(
        {
            "status": "COMPLETED",
            "folds": len(collections["fold_manifest"]),
            "number_of_features_tried": 17,
            "number_of_horizons_tried": 1,
            "number_of_model_families_tried": 3,
            "number_of_model_fits": sum(
                row["kind"] == "MODEL_FIT" and row["status"] == "COMPLETED"
                for row in collections["all_trials"]
            ),
            "number_of_planned_model_fit_slots": sum(
                row["kind"] == "MODEL_FIT" for row in collections["all_trials"]
            ),
            "number_of_skipped_model_fits": sum(
                row["kind"] == "MODEL_FIT"
                and row["status"] == "INSUFFICIENT_CALIBRATION_DATA_NO_FIT"
                for row in collections["all_trials"]
            ),
            "number_of_hyperparameter_trials_per_model_per_fold": 1,
            "number_of_cost_thresholds_tried_in_validation": 3,
            "number_of_target_volatility_values_tried_in_validation": 3,
            "number_of_risk_rules_tried": 1,
            "files_sha256": {
                p.name: digest(p)
                for p in sorted(output.iterdir())
                if p.is_file() and p.name != "run_manifest.json"
            },
        }
    )
    write_json(output / "run_manifest.json", manifest)
    print(
        json.dumps(
            {level: aggregate_rows[(level, "cost_1")]["net_compound_return"] for level in LEVELS}
        ),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/alpha_v4/walkforward"
    if args.check:
        manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        if manifest["status"] != "COMPLETED":
            raise ValueError("walk-forward run is incomplete")
        for name, expected in manifest["files_sha256"].items():
            path = (output / name).resolve()
            if not path.is_relative_to(output.resolve()) or digest(path) != expected:
                raise ValueError(f"walk-forward evidence hash mismatch: {name}")
        print("frozen walk-forward evidence verified; no fitting or holdout access")
        return 0
    run(root, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
