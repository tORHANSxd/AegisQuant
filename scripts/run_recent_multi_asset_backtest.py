"""Frozen R4 policies on newly downloaded, completed public spot candles."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml

from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import BacktestResult, BacktestRunSpec, EngineKind
from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.providers.binance.rest import BinancePublicRestClient
from aegisquant.domain.identifiers import AssetId, RunId, StrategyId, StrategyVersionId
from aegisquant.domain.values import Money
from aegisquant.portfolio.economic_gate import EconomicGatePolicy
from aegisquant.research.strategies.buffered_target import BufferPolicy
from aegisquant.research.strategies.cost_aware_trend import (
    BoolArray,
    FloatArray,
    R4TrendPolicy,
    build_trend_features,
    trend_targets,
)
from aegisquant.research.validation.cat_replay import CatMarket, load_completed_bars, replay_cat
from aegisquant.research.validation.public_market_backtest import (
    RealBacktestConfig,
    load_or_download_spot_klines,
    write_bronze_csv,
)
from scripts.run_alpha_r4 import read_result, save_run
from scripts.run_alpha_v4_audit import ROOT, SYMBOLS, read_json
from scripts.run_alpha_v4_audit_r2 import policies
from scripts.run_alpha_v4_walkforward import digest, table, write_json
from scripts.summarize_alpha_r4 import shadow_cost

ARMS = ("CASH", "F2", "F3", "F4", "F5", "BUY_HOLD")
MULTIPLIERS = ("1", "0", "0.5", "1.5", "2")
ZERO = Decimal("0")


def completed_cutoff(server_ms: int) -> datetime:
    """Use only candles closed before the frozen exchange clock."""
    width = 14_400_000
    return datetime.fromtimestamp((server_ms // width * width) / 1000, UTC)


def validate_result(result: BacktestResult, end: datetime) -> dict[str, Any]:
    if abs(result.cost_identity_residual) >= Decimal("1e-8"):
        raise ValueError("cost identity failed")
    if result.positions[-1].quantity != 0:
        raise ValueError("terminal position remains; cannot report liquidated cash")
    for point in result.equity_curve:
        if point.cash < 0 or point.position_value < 0:
            raise ValueError("spot long/flat cash constraint failed")
        if abs(point.equity - point.cash - point.position_value) > Decimal("1e-8"):
            raise ValueError("MTM identity failed")
    orders = {str(row.order.backtest_order_id): row.order for row in result.orders}
    for fill in result.fills:
        if not orders[str(fill.backtest_order_id)].decision_time < fill.event_time < end:
            raise ValueError("fill uses a contemporaneous or unavailable price")
    return {
        "cost_identity_residual": str(result.cost_identity_residual),
        "nonnegative_cash_and_long_only": True,
        "paid_terminal_exit": True,
        "strict_next_event_fills": True,
    }


def prepare(output: Path, start: datetime) -> None:
    if output.exists():
        raise FileExistsError("use a new evidence directory; previous runs are immutable")
    with httpx.Client(timeout=30, trust_env=False) as client:
        response = client.get("https://data-api.binance.vision/api/v3/time")
        response.raise_for_status()
        server = response.json()
    end = completed_cutoff(int(server["serverTime"]))
    if start.tzinfo is None or start.utcoffset() != timedelta(0):
        raise ValueError("start must be explicitly UTC")
    if start.timestamp() % 14400 or end <= start:
        raise ValueError("start must precede the latest complete UTC four-hour boundary")
    output.mkdir(parents=True)
    prior = read_json(ROOT / "artifacts/alpha_r4/20260908_v1/effective_config.json")
    rules = yaml.safe_load((ROOT / "configs/research/alpha_v4_multi_asset.yaml").read_text("utf-8"))
    source_files = [
        *ROOT.glob("src/**/*.py"),
        *ROOT.glob("configs/**/*.yaml"),
        *ROOT.glob("scripts/*.py"),
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
    ]
    source_hashes = {}
    for source in source_files:
        relative = source.relative_to(ROOT).as_posix()
        target = output / "implementation" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        source_hashes[relative] = digest(target)
    from scripts.export_alpha_v4_audit_bundle import git

    config: dict[str, Any] = {
        "version": "recent-r4-fixed-20260908-v1",
        "authorization": "user requested recent months through today multi-crypto historical test",
        "registered_at": datetime.now(UTC).isoformat(),
        "exchange_time": server,
        "test_start": start.isoformat(),
        "test_end_exclusive": end.isoformat(),
        "warmup_start": (start - timedelta(days=365)).isoformat(),
        "warmup_is_not_scored": True,
        "source_head": git(ROOT, "rev-parse", "HEAD"),
        "source_branch": git(ROOT, "branch", "--show-current"),
        "workspace_status_at_registration": git(ROOT, "status", "--porcelain=v1"),
        "source_sha256": source_hashes,
        "symbols": SYMBOLS,
        "arms": ARMS,
        "primary_candidate": "F3",
        "excluded_historical_arms": "F0/F1 quarterly-reset diagnostics already audited; A3/A7 have no recent frozen forecasts",
        "cost_multipliers": MULTIPLIERS,
        "frozen_order_multipliers": ["1.5", "2"],
        "cash_per_symbol": "10000",
        "cross_asset_transfers": False,
        "gate": prior["gate"],
        "audit_policy": policies()["A1"].model_dump(mode="json"),
        "buffer_policy": {
            "relative_half_width": str(BufferPolicy().relative_half_width),
            "review_interval_seconds": BufferPolicy().review_interval.total_seconds(),
        },
        "execution_rules": rules["execution_rules"],
        "buy_hold_definition": "existing B1: 99% target at first eligible next open, no ordinary resizing, paid final exit",
        "terminal_exit": "decision at penultimate completed bar close, execute at last completed bar open; no later price",
        "evidence_tier": "RECENT_FIXED_POLICY_RETROSPECTIVE_NOT_FINAL_HOLDOUT",
        "new_return_model_fits": 0,
        "new_calibration_fits": 0,
        "new_scaler_fits": 0,
        "parameter_searches": 0,
        "final_holdout_access_count": 0,
        "production_policy": "CASH",
        "live_trading": False,
        "order_submission_enabled": False,
        "bootstrap": {
            "seed": 20260908,
            "repetitions": 10000,
            "comparisons": ["F3-F2", "F4-F3", "F3-F5", "F4-F5", "F3-CASH"],
            "frequency": "complete UTC daily intervals only; last partial UTC day excluded from inference",
            "block_rule": "existing R4 maximum automatic estimate across returns and squared returns",
        },
    }
    if config["source_branch"] != "main":
        raise ValueError("preserve checkout; only existing main is allowed")
    config["sha256"] = canonical_sha256(config)
    write_json(output / "effective_config.json", config)
    request = RealBacktestConfig(
        symbols=SYMBOLS,
        start_at=start - timedelta(days=365),
        end_at_exclusive=end,
    )
    datasets: list[dict[str, Any]] = []
    with BinancePublicRestClient(timeout_seconds=30, maximum_attempts=4) as client:
        for symbol in SYMBOLS:
            print(
                f"download {symbol} {request.start_at.isoformat()} to {end.isoformat()}", flush=True
            )
            download = load_or_download_spot_klines(
                config=request, symbol=symbol, raw_root=output / "raw", client=client
            )
            target = output / "data" / f"{symbol}_1h.csv"
            target.parent.mkdir(exist_ok=True)
            sha = write_bronze_csv(download, target)
            datasets.append(
                {
                    "symbol": symbol,
                    "file": target.relative_to(output).as_posix(),
                    "sha256": sha,
                    "download": download.source_manifest,
                }
            )
            write_json(
                output / "source_manifest.json",
                {"datasets": datasets, "authentication_used": False, "status": "DOWNLOADING"},
            )
            print(f"saved {symbol}: {len(download.rows)} hourly candles", flush=True)
    write_json(
        output / "source_manifest.json",
        {"datasets": datasets, "authentication_used": False, "status": "COMPLETE"},
    )


def run(output: Path) -> None:
    config = read_json(output / "effective_config.json")
    for name, sha in config["source_sha256"].items():
        if digest(ROOT / name) != sha:
            raise ValueError(f"registered implementation changed: {name}")
    if (output / "experiment_registry.json").exists():
        raise FileExistsError("preserve completed experiment registry")
    start = datetime.fromisoformat(config["test_start"])
    end = datetime.fromisoformat(config["test_end_exclusive"])
    registry: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    quality: list[dict[str, Any]] = []
    shadow: list[dict[str, Any]] = []
    for dataset in read_json(output / "source_manifest.json")["datasets"]:
        symbol = dataset["symbol"]
        source = output / dataset["file"]
        if digest(source) != dataset["sha256"]:
            raise ValueError("downloaded data hash changed")
        rule = config["execution_rules"][symbol]
        market = CatMarket(
            AssetId(rule["base_asset"]), Decimal(rule["tick_size"]), Decimal(rule["quantity_step"])
        )
        bars = load_completed_bars(source, market_spec=market)
        features = build_trend_features(bars)
        indices = {t: i for i, t in enumerate(features.available_times)}
        targets = trend_targets(features.values[:, 0], features.valid)
        trend = {t: bool(v) for t, v in zip(features.available_times, targets, strict=True)}
        local = tuple(b for b in bars if start <= b.event_time < end)
        expected = int((end - start).total_seconds() / 14400)
        if len(local) != expected or any(
            b.event_time != start + timedelta(hours=4 * i) for i, b in enumerate(local)
        ):
            raise ValueError(f"{symbol}: incomplete evaluation clock; no forward filling")
        if any(b.available_time >= end for b in local):
            raise ValueError("unfinished evaluation candle")
        signals: list[FloatArray] = []
        readiness: list[BoolArray] = []
        for fast, slow in ((10, 40), (20, 80), (40, 160)):
            policy = R4TrendPolicy.model_validate({"fast_days": fast, "slow_days": slow})
            other = build_trend_features(bars, policy)
            signals.append(trend_targets(other.values[:, 0], other.valid, policy))
            readiness.append(other.valid)
        fractions = {
            t: Decimal(sum(int(s[i]) for s in signals)) / 3
            if all(bool(v[i]) for v in readiness)
            else ZERO
            for i, t in enumerate(features.available_times)
        }
        table(
            output / "data" / f"{symbol}_readiness.parquet",
            [
                {
                    "time": b.available_time,
                    "ready_10_40": bool(readiness[0][indices[b.available_time]]),
                    "ready_20_80": bool(readiness[1][indices[b.available_time]]),
                    "ready_40_160": bool(readiness[2][indices[b.available_time]]),
                    "signal_fraction": str(fractions[b.available_time]),
                }
                for b in local
            ],
        )
        quality.append(
            {
                "symbol": symbol,
                "completed_4h_bars": len(local),
                "expected_4h_bars": expected,
                "warmup_4h_bars": len(bars) - len(local),
                "first_open": local[0].event_time,
                "last_close": local[-1].available_time,
                "full_ensemble_ready_bars": sum(
                    all(bool(v[indices[b.available_time]]) for v in readiness) for b in local
                ),
            }
        )
        for arm in ARMS:
            cases = (
                [("REDECIDE_FUNDED", m) for m in MULTIPLIERS]
                if arm != "CASH"
                else [("REDECIDE_FUNDED", "1")]
            )
            if arm != "CASH":
                cases += [("FROZEN_ORDERS_FUNDED", m) for m in ("1.5", "2")]
            base: BacktestResult | None = None
            for mode, multiplier in cases:
                print(f"replay {symbol} {arm} {mode} cost={multiplier}", flush=True)
                spec = BacktestRunSpec(
                    run_id=RunId(f"recent-{symbol}-{arm}"),
                    engine_kind=EngineKind.EVENT,
                    strategy_id=StrategyId("recent-r4-fixed"),
                    strategy_version_id=StrategyVersionId("recent-r4-fixed-v1"),
                    dataset_sha256=dataset["sha256"],
                    config_sha256=config["sha256"],
                    code_sha256=canonical_sha256(config["source_sha256"]),
                    seed=20260908,
                    reporting_asset_id=AssetId("USDT"),
                    initial_cash=Money(amount=Decimal("10000"), asset_id=AssetId("USDT")),
                    start_time=start,
                    end_time=end,
                    created_at=datetime.fromisoformat(config["registered_at"]),
                    accounting_policy_version="accounting-v1",
                    cost_policy_version="cat-proxy-v2",
                    rule_policy_version="cat-rule-proxy-v1",
                    metric_frequency_seconds=14400,
                    reproduction_command="python -m scripts.run_recent_multi_asset_backtest run --output <registered-output>",
                )
                actual_trend = (
                    {t: v > 0 for t, v in fractions.items()}
                    if arm == "F4"
                    else dict.fromkeys(trend, True)
                    if arm == "F5"
                    else trend
                )
                result, trace = replay_cat(
                    root=ROOT,
                    spec=spec,
                    bars=local,
                    features=features,
                    feature_indices=indices,
                    trend_by_time=actual_trend,
                    forecasts={},
                    level="B0" if arm == "CASH" else "B1" if arm == "BUY_HOLD" else "A1",
                    audit_policy=None if arm in {"CASH", "BUY_HOLD"} else policies()["A1"],
                    gate_policy=EconomicGatePolicy.model_validate_json(json.dumps(config["gate"])),
                    market_spec=market,
                    cost_multiplier=Decimal(multiplier),
                    fixed_orders=tuple(r.order for r in base.orders)
                    if mode == "FROZEN_ORDERS_FUNDED" and base is not None
                    else None,
                    buffer_policy=BufferPolicy() if arm in {"F3", "F4", "F5"} else None,
                    signal_fractions=fractions if arm == "F4" else None,
                    terminal_exit_reason="EVALUATION_END_NEXT_OPEN_EXIT",
                )
                folder = output / "runs" / arm / symbol / f"{mode}_{multiplier}"
                save_run(folder, result, trace)
                checks = validate_result(result, end)
                if arm == "CASH" and (result.orders or result.equity_curve[-1].equity != 10000):
                    raise ValueError("production CASH must remain cash with zero orders")
                costs = sum((f.cost_breakdown.total for f in result.fills), ZERO)
                final = result.equity_curve[-1].equity
                terminal = [f for f in result.fills if f.event_time == local[-1].event_time]
                row = {
                    "arm": arm,
                    "symbol": symbol,
                    "mode": mode,
                    "cost_multiplier": multiplier,
                    "final_cash": str(final),
                    "terminal_mtm_at_exit_reference": str(
                        final + sum((f.cost_breakdown.total for f in terminal), ZERO)
                    ),
                    "exit_reference_time": local[-1].event_time,
                    "total_cost": str(costs),
                    "orders": len(result.orders),
                    "fills": len(result.fills),
                    "closed_trades": len(result.closed_trades),
                    "winning_trades": sum(t.net_pnl > 0 for t in result.closed_trades),
                    "rejections": sum(bool(o.rejection_code) for o in result.orders),
                    "checks": checks,
                    "output": folder.relative_to(output).as_posix(),
                }
                registry.append(row)
                write_json(output / "progress.json", {"completed_runs": registry})
                for p in resample_equity(result.equity_curve, 14400):
                    equity_rows.append(
                        {
                            "arm": arm,
                            "symbol": symbol,
                            "mode": mode,
                            "cost_multiplier": multiplier,
                            "time": p.time,
                            "equity": float(p.equity),
                            "cash": float(p.cash),
                            "position_value": float(p.position_value),
                        }
                    )
                if mode == "REDECIDE_FUNDED" and multiplier == "1":
                    base = result
                    for factor in ("0", "0.5", "1", "1.5", "2"):
                        stressed = sum(
                            (shadow_cost(f, Decimal(factor)) for f in result.fills), ZERO
                        )
                        shadow.append(
                            {
                                "symbol": symbol,
                                "arm": arm,
                                "mode": "SAME_FILL_SHADOW",
                                "cost_multiplier": factor,
                                "final_equity": str(final + costs - stressed),
                                "total_cost": str(stressed),
                                "tradable": False,
                            }
                        )
            # Confirm the persisted base can reconstruct the authoritative result.
            restored = read_result(output / "runs" / arm / symbol / "REDECIDE_FUNDED_1")
            if base is not None and restored.economic_event_hash != base.economic_event_hash:
                raise ValueError("saved ledger failed round-trip")
    if len(registry) != len(SYMBOLS) * (1 + 5 * 7):
        raise ValueError("finite matrix incomplete")
    table(output / "mtm_equity.parquet", equity_rows)
    table(output / "same_fill_shadow.parquet", shadow)
    write_json(output / "data_quality.json", {"symbols": quality, "no_forward_fill": True})
    write_json(output / "experiment_registry.json", {"status": "REPLAYED", "runs": registry})
    print(f"complete: {len(registry)} funded engine replays", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="2026-03-08T00:00:00+00:00")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.action == "prepare":
        prepare(output, datetime.fromisoformat(args.start))
    else:
        run(output)


if __name__ == "__main__":
    main()
