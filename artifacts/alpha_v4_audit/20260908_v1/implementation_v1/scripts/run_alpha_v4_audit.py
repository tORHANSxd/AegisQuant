"""Preregister and replay a finite development audit from frozen forecasts, never refit trees."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl

from aegisquant.backtest.models import BacktestRunSpec, EngineKind
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import AssetId, RunId, StrategyId, StrategyVersionId
from aegisquant.domain.values import Money
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.models.baselines import BaselineDataset
from aegisquant.research.models.economic_filter import fit_economic_filter
from aegisquant.research.models.economic_gate import EconomicForecast
from aegisquant.research.strategies.cost_aware_trend import build_trend_features, trend_targets
from aegisquant.research.validation.calendar_walkforward import add_months, calendar_walkforward
from aegisquant.research.validation.cat_contract import audit_arms, compile_legacy_config
from aegisquant.research.validation.cat_replay import (
    USDT,
    CatMarket,
    executable_labels,
    load_completed_bars,
    replay_cat,
)
from scripts.export_alpha_v4_audit_bundle import check, digest, git
from scripts.run_alpha_v4_multi_asset import append_result
from scripts.run_alpha_v4_walkforward import table, write_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/alpha_v4_audit/20260908_v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
SOURCE = ROOT / "artifacts/alpha_v4_multi_asset"
END = datetime(2025, 10, 1, tzinfo=UTC)
SEED = 20260908


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def preregister():
    path = OUTPUT / "preregistration.json"
    if path.exists():
        raise FileExistsError("research questions already frozen")
    check(ROOT, OUTPUT / "before")
    effective = compile_legacy_config(ROOT, multi_asset=True)
    arms = {name: value.model_dump(mode="json") for name, value in audit_arms().items()}
    config = {
        "version": "alpha-v4-audit-20260908-v1",
        "registered_at": datetime.now(UTC).isoformat(),
        "git_sha": git(ROOT, "rev-parse", "HEAD"),
        "symbols": SYMBOLS,
        "test_start": "2022-04-01T00:00:00Z",
        "test_end_exclusive": END.isoformat(),
        "evidence_tier": "DEVELOPMENT_ATTRIBUTION_NOT_NEW_OOS",
        "arms": arms,
        "legacy_reproductions": ["B3", "B7"],
        "primary_no_ml": "A1",
        "primary_ml": "A3",
        "main_hypotheses": ["A1 > CASH", "A3 > A1", "A3 > NULL_A3"],
        "minimum_economic_increment_annual": 0.02,
        "risk_anchor_annual_volatility": 0.20,
        "alpha_confidence": 0.95,
        "blocks_bars": [6, 18, 42, 84],
        "bootstrap_repetitions": 10000,
        "quarter_cluster_bootstrap": True,
        "seed": SEED,
        "bridge_C0": "legacy B3 -> v2 causal reserve, no ML/no risk sizing; separates execution contract from A1 risk",
        "model_entry_rule": "frozen calibrated expected_gross_return > 0; no outcome-based redefinition",
        "prediction_contract": "legacy decision-offset-v1: entry i+1, exit i+6, five intervals/20h; no relabelling",
        "primary_trend": "same legacy B3 10/40 and complete-feature validity for A0/C0/A1-A7",
        "model_challengers": {
            "NULL_A3": "training mean plus EXACT same validation Platt/residual calibration, no tree fit",
            "EN_A3": "frozen Elastic Net forecasts, A3 controls; separate registered comparison",
        },
        "continuous": "A1 only; carry actual final cash into next quarter, paid liquidation, no cross-sleeve transfer",
        "covariance": "A1 covariance challenger; trailing 180 common 4h returns, 50% diagonal shrinkage, quarter-start capital weights, frozen quarterly cap, no leverage",
        "cost_stress": {
            "arms": ["A1", "A3"],
            "multipliers": [1.5, 2.0],
            "modes": ["SAME_FILL_SHADOW", "FROZEN_ORDERS_FUNDED", "REDECIDE_FUNDED"],
        },
        "selection_budget": {
            "new_return_model_fits": 0,
            "new_constant_calibration_slots": 70,
            "hyperparameter_searches": 0,
            "new_symbol_selection": 0,
            "historical_fixed_model_fits": 186,
            "historical_planned_slots": 210,
            "history_of_independent_hypotheses": "INCOMPLETE_DO_NOT_PASS_DSR_PBO",
        },
        "promotion": effective["declared"]["research"]["promotion"],
        "final_holdout": "NOT_ALLOCATED_NO_ACCESS; 12 previously unused months still required",
        "production_policy": "CASH",
        "production_ml_enabled": False,
        "live_trading": False,
        "order_submission_enabled": False,
    }
    config["sha256"] = canonical_sha256(config)
    write_json(path, config)
    write_json(OUTPUT / "effective_config.json", {"legacy": effective, "audit": config})
    print("preregistered finite audit", flush=True)


def inputs(symbol):
    policy = read_json(SOURCE / "run_manifest.json")["policy"]
    row = next(
        row
        for row in read_json(SOURCE / "source_manifest.json")["datasets"]
        if row["symbol"] == symbol
    )
    market = CatMarket(
        base_asset=AssetId(policy["execution_rules"][symbol]["base_asset"]),
        tick_size=Decimal(policy["execution_rules"][symbol]["tick_size"]),
        quantity_step=Decimal(policy["execution_rules"][symbol]["quantity_step"]),
    )
    source = ROOT / row["path"]
    if digest(source) != row["sha256"]:
        raise ValueError("public data identity changed")
    bars = tuple(b for b in load_completed_bars(source, market_spec=market) if b.event_time < END)
    features = build_trend_features(bars)
    values, ends = executable_labels(bars)
    folds = calendar_walkforward(
        available_times=features.available_times,
        label_end_times=ends,
        valid=tuple(map(bool, features.valid)),
        first_train_start=datetime(2021, 1, 1, tzinfo=UTC),
        development_end=END,
    )
    indices = {time: i for i, time in enumerate(features.available_times)}
    targets = trend_targets(features.values[:, 0], features.valid)
    trend = {
        time: bool(value) for time, value in zip(features.available_times, targets, strict=True)
    }
    return source, market, bars, features, values, ends, folds, indices, trend


def frozen(symbol, fold):
    if symbol == "BTCUSDT":
        folder = ROOT / "artifacts/alpha_v4/walkforward"
        forecasts = pl.read_parquet(folder / "predictions.parquet").filter(
            pl.col("fold_id") == fold.fold_id
        )
        original = pl.read_parquet(folder / "fold_stability.parquet").filter(
            pl.col("fold_id") == fold.fold_id
        )
        meta = (
            pl.read_parquet(folder / "fold_manifest.parquet")
            .filter(pl.col("fold_id") == fold.fold_id)
            .to_dicts()[0]
        )
    else:
        folder = SOURCE / symbol / fold.fold_id
        forecasts = pl.read_parquet(folder / "predictions.parquet")
        original = pl.read_parquet(folder / "fold_stability.parquet")
        meta = read_json(folder / "fold_manifest.json")
    outputs = {}
    if "family" in forecasts.columns:
        for family in ("XGBOOST", "ELASTIC_NET"):
            outputs[family] = {}
            for row in forecasts.filter(pl.col("family") == family).to_dicts():
                data = {name: row[name] for name in EconomicForecast.model_fields if name in row}
                value = EconomicForecast.model_validate_json(json.dumps(data, default=str))
                outputs[family][value.available_time] = value
    return outputs, original, meta


def constant_forecasts(bars, features, values, ends, fold):
    boundary = add_months(fold.validation_start, 1)
    calibration = tuple(
        i
        for i in fold.validation_indices
        if features.available_times[i] < boundary - timedelta(hours=48)
        and ends[i] is not None
        and ends[i] < boundary
    )
    if len(calibration) < 30:
        return {}, {"status": "INSUFFICIENT_CALIBRATION_NO_FIT", "rows": len(calibration)}

    def dataset(chosen, labels):
        # Constant model consumes no feature values; IDs/targets/calibration population are identical.
        return BaselineDataset(
            sample_ids=tuple(str(bars[i].event_id) for i in chosen),
            timestamps=tuple(features.available_times[i] for i in chosen),
            feature_names=("intercept",),
            features=((1.0,),) * len(chosen),
            targets=tuple(values[i] if labels else 0.0 for i in chosen),
        )

    known_costs = tuple(
        estimate_spot_transition_costs(
            available_time=bars[i].available_time,
            natr=Decimal(str(features.values[i, 9])),
            quote_volume=bars[i].close * bars[i].volume,
            order_notional=Decimal("10000"),
        ).round_trip
        for i in calibration
    )
    result = fit_economic_filter(
        family="CONSTANT",
        train=dataset(fold.train_indices, True),
        validation=dataset(calibration, True),
        test=dataset(fold.test_indices, False),
        train_label_end_times=tuple(ends[i] for i in fold.train_indices),
        validation_label_end_times=tuple(ends[i] for i in calibration),
        validation_round_trip_costs=known_costs,
        seed=20260903,
    )
    meta = result.model_dump(mode="json", exclude={"forecasts"})
    return {value.available_time: value for value in result.forecasts}, {
        "status": "CONSTANT_CALIBRATION_COMPLETED",
        **meta,
    }


def make_spec(symbol, fold, arm, source, config, cash=Decimal("10000")):
    return BacktestRunSpec(
        run_id=RunId(f"audit-{symbol}-{fold.fold_id}-{arm}"),
        engine_kind=EngineKind.EVENT,
        strategy_id=StrategyId("cat-audit"),
        strategy_version_id=StrategyVersionId("cat-audit-v2"),
        dataset_sha256=digest(source),
        config_sha256=config["sha256"],
        code_sha256=digest(Path(__file__)),
        seed=SEED,
        reporting_asset_id=USDT,
        initial_cash=Money(amount=cash, asset_id=USDT),
        start_time=fold.test_start,
        end_time=fold.test_end,
        created_at=datetime.fromisoformat(config["registered_at"]),
        accounting_policy_version="accounting-v1",
        cost_policy_version="cat-proxy-v2",
        rule_policy_version="cat-rule-proxy-v1",
        reproduction_command=f"python -m scripts.run_alpha_v4_audit --symbol {symbol}",
        metric_frequency_seconds=14400,
    )


def trial_collections():
    return {
        name: []
        for name in (
            "fold_stability",
            "mtm_equity",
            "orders",
            "fills",
            "trades",
            "terminal_attribution",
        )
    }


def save_result(collections, result, fold, arm, scenario="1", topology=None):
    append_result(
        collections,
        result,
        fold.fold_id,
        arm,
        scenario,
        topology
        if topology is not None
        else [(str(f.backtest_order_id), f.quantity.amount) for f in result.fills],
    )


def run_symbol(symbol):
    config = read_json(OUTPUT / "preregistration.json")
    if config["arms"] != {k: v.model_dump(mode="json") for k, v in audit_arms().items()}:
        raise ValueError("registered arm definitions changed")
    check(ROOT, OUTPUT / "before")
    source, market, bars, features, values, ends, folds, indices, trend = inputs(symbol)
    parent = OUTPUT / symbol
    parent.mkdir(exist_ok=True)
    episode = 0
    episodes = {}
    prior = False
    for time, long in trend.items():
        if long and not prior:
            episode += 1
        episodes[time] = f"{symbol}-trend-{episode}" if long else None
        prior = long
    for number, fold in enumerate(folds, 1):
        output = parent / fold.fold_id
        if (output / "completion.json").exists():
            continue
        if output.exists() and any(output.iterdir()):
            raise FileExistsError(
                "partial fold evidence exists; preserve it and use a versioned retry"
            )
        output.mkdir(exist_ok=True)
        print(
            f"{symbol} {number}/14 {fold.fold_id}: verify frozen B3/B7 then finite replays",
            flush=True,
        )
        forecasts, original, meta = frozen(symbol, fold)
        test_bars = tuple(b for b in bars if fold.test_start <= b.event_time < fold.test_end)
        allowed = set(fold.test_indices)
        fold_trend = {time: long and indices[time] in allowed for time, long in trend.items()}
        collection = trial_collections()
        traces, reproductions, shadows, all_forecasts = [], [], [], []
        results = {}
        common = dict(
            root=ROOT,
            bars=test_bars,
            features=features,
            feature_indices=indices,
            trend_by_time=fold_trend,
            market_spec=market,
        )
        for arm, level in (("A0", "B3"), ("LEGACY_B7", "B7")):
            spec = make_spec(symbol, fold, arm, source, config)
            result, trace = replay_cat(
                spec=spec, level=level, forecasts=forecasts.get("XGBOOST", {}), **common
            )
            expected = original.filter(
                (pl.col("level") == level) & (pl.col("scenario") == "cost_1")
            ).to_dicts()[0]
            difference = result.mark_to_market_final_equity - Decimal(
                str(expected["mtm_final_equity"])
            )
            if abs(difference) > Decimal("1e-8") or len(result.fills) != expected["fills"]:
                raise ValueError(f"legacy {level} reproduction failed: {difference}")
            reproductions.append(
                {
                    "arm": arm,
                    "equity_difference": str(difference),
                    "fills": len(result.fills),
                    "status": "PASS",
                }
            )
            results[arm] = result
            save_result(collection, result, fold, arm)
            traces.extend({"arm": arm, **row} for row in trace)

        null, null_meta = constant_forecasts(bars, features, values, ends, fold)
        write_json(output / "null_model.json", null_meta)
        arms = {**audit_arms(), "NULL_A3": audit_arms()["A3"], "EN_A3": audit_arms()["A3"]}
        for arm, policy in arms.items():
            family = (
                "CONSTANT" if arm == "NULL_A3" else "ELASTIC_NET" if arm == "EN_A3" else "XGBOOST"
            )
            predicted = null if family == "CONSTANT" else forecasts.get(family, {})
            spec = make_spec(symbol, fold, arm, source, config)
            result, trace = replay_cat(
                spec=spec, level=arm, forecasts=predicted, audit_policy=policy, **common
            )
            results[arm] = result
            save_result(collection, result, fold, arm)
            for row in trace:
                row.update(
                    {
                        "arm": arm,
                        "model_id": family if policy.switches.use_model_entry_filter else None,
                        "train_end": str(meta["maximum_train_label_end"]),
                        "trend_episode_id": episodes.get(row["time"]),
                        "trace_provenance": "REPLAYED_FROZEN_FORECAST_NEW_CONTRACT",
                    }
                )
                predicted_row = predicted.get(row["time"])
                if predicted_row is not None and predicted_row.raw_prediction is not None:
                    row.update(
                        {
                            "raw_prediction": str(predicted_row.raw_prediction),
                            "mean_bias": str(predicted_row.mean_bias),
                            "raw_prediction_missing_reason": None,
                        }
                    )
            traces.extend(trace)
            if arm in {"A1", "A3"}:
                topology = [(str(f.backtest_order_id), f.quantity.amount) for f in result.fills]
                for multiplier in ("1.5", "2"):
                    for mode in ("FROZEN_ORDERS_FUNDED", "REDECIDE_FUNDED"):
                        stress, _ = replay_cat(
                            spec=spec,
                            level=arm,
                            forecasts=predicted,
                            audit_policy=policy,
                            cost_multiplier=Decimal(multiplier),
                            fixed_orders=tuple(r.order for r in result.orders)
                            if mode == "FROZEN_ORDERS_FUNDED"
                            else None,
                            **common,
                        )
                        save_result(collection, stress, fold, arm, f"{mode}_{multiplier}", topology)
                    # Exact same quantities, references and accounting denomination. Fees apply to stressed execution.
                    cost = Decimal("0")
                    scale = Decimal(multiplier)
                    for fill in result.fills:
                        parts = fill.cost_breakdown
                        adverse = parts.spread + parts.slippage + parts.impact
                        direction = 1 if fill.side.value == "BUY" else -1
                        base_notional = parts.gross_notional
                        fee_rate = parts.fee / (fill.execution_price.amount * fill.quantity.amount)
                        cost += (
                            adverse * scale
                            + (base_notional + direction * adverse * scale) * fee_rate * scale
                        )
                    gross = result.pnl_attribution[-1].gross_trading_pnl
                    terminal = spec.initial_cash.amount + gross - cost
                    if terminal > result.mark_to_market_final_equity:
                        raise ValueError("nonnegative same-fill costs improved shadow wealth")
                    shadows.append(
                        {
                            "symbol": symbol,
                            "fold_id": fold.fold_id,
                            "arm": arm,
                            "multiplier": multiplier,
                            "mode": "SAME_FILL_SHADOW_NOT_FUNDED",
                            "final_equity": str(terminal),
                            "cost": str(cost),
                            "fixed": "fill time/side/quantity/reference price",
                            "changed": "nonnegative costs only",
                        }
                    )
        # Keep frozen forecast identity; the constant calibration is labelled as a new null diagnostic.
        for family, predicted in {**forecasts, "CONSTANT": null}.items():
            for time, predicted_row in predicted.items():
                i = indices[time]
                all_forecasts.append(
                    {
                        "family": family,
                        "symbol": symbol,
                        "fold_id": fold.fold_id,
                        **predicted_row.model_dump(mode="python"),
                        "is_trend_candidate": trend[time],
                        "trend_episode_id": episodes[time],
                        "label_entry_time": bars[i + 1].event_time if i + 1 < len(bars) else None,
                        "label_end_time": ends[i],
                        "realized_short_label": values[i]
                        if np.isfinite(values[i]) and ends[i] < fold.test_end
                        else None,
                        "outcome_not_strategy_input": True,
                    }
                )
        for name, rows in collection.items():
            table(output / f"{name}.parquet", rows)
        table(output / "decision_trace.parquet", traces)
        table(output / "forecast_diagnostics.parquet", all_forecasts)
        table(output / "same_fill_shadow.parquet", shadows)
        write_json(output / "reproduction.json", reproductions)
        write_json(
            output / "fold_contract.json",
            {
                **asdict(fold),
                "original_metadata": meta,
                "full_feature_invalid_bars": sum(
                    not features.valid[indices[b.available_time]] for b in test_bars
                ),
                "trend_invalid_bars": sum(
                    not features.trend_valid[indices[b.available_time]] for b in test_bars
                ),
            },
        )
        write_json(
            output / "completion.json",
            {
                "status": "PASS",
                "preregistration_sha256": config["sha256"],
                "files": {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
                "new_tree_or_linear_fits": 0,
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
    print(f"{symbol}: all 14 audit folds complete", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregister", action="store_true")
    parser.add_argument("--symbol", choices=SYMBOLS)
    args = parser.parse_args()
    if args.preregister:
        preregister()
    elif args.symbol:
        run_symbol(args.symbol)
    else:
        parser.error("choose --preregister or --symbol")


if __name__ == "__main__":
    main()
