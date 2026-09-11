"""Download official public market data and run the frozen development-OOS backtest."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from aegisquant.data.providers.binance.rest import BinancePublicRestClient
from aegisquant.research.validation.public_market_backtest import (
    DownloadedKlines,
    RealBacktestConfig,
    SymbolRun,
    build_backtest_report,
    load_or_download_spot_klines,
    prepare_samples,
    run_symbol_walk_forward,
    verify_evidence,
    write_evidence,
)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include UTC offset")
    normalized = parsed.astimezone(UTC)
    if normalized.utcoffset() != UTC.utcoffset(normalized):
        raise argparse.ArgumentTypeError("timestamp must resolve to UTC")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=("BTCUSDT", "ETHUSDT"))
    parser.add_argument("--start", type=_utc, default=_utc("2021-01-01T00:00:00Z"))
    parser.add_argument("--end-exclusive", type=_utc, default=_utc("2026-01-01T00:00:00Z"))
    parser.add_argument("--bootstrap-repetitions", type=int, default=1_000)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    report_directory = root / "reports/v5/REAL_DATA_BACKTEST"
    manifest_path = report_directory / "RUN_MANIFEST.json"
    if args.check:
        verify_evidence(root, manifest_path)
        print(f"verified real-data backtest evidence: {manifest_path}")
        return 0

    config = RealBacktestConfig(
        symbols=tuple(cast("list[str]", args.symbols)),
        start_at=cast("datetime", args.start),
        end_at_exclusive=cast("datetime", args.end_exclusive),
        bootstrap_repetitions=cast("int", args.bootstrap_repetitions),
    )
    raw_root = root / "data/raw"
    downloads: list[DownloadedKlines] = []
    with BinancePublicRestClient(timeout_seconds=20.0, maximum_attempts=4) as client:
        for symbol in config.symbols:
            print(f"loading official Binance Spot {symbol} {config.start_at:%Y-%m-%d}..")
            downloads.append(
                load_or_download_spot_klines(
                    config=config,
                    symbol=symbol,
                    raw_root=raw_root,
                    client=client,
                )
            )
    prepared = [prepare_samples(item) for item in downloads]
    runs: list[SymbolRun] = []
    for samples in prepared:
        print(f"running rolling OOS validation for {samples.symbol}..")
        runs.append(run_symbol_walk_forward(samples, config))
    report = build_backtest_report(
        config=config,
        downloads=downloads,
        runs=runs,
        generated_at=datetime.now(UTC),
    )
    write_evidence(
        root=root,
        config=config,
        downloads=downloads,
        runs=runs,
        report=report,
        report_directory=report_directory,
        bronze_directory=root / "data/bronze/real_market_backtest",
        gold_directory=root / "data/gold/real_market_backtest",
    )
    aggregate = cast("dict[str, object]", report["aggregate_selected_policy"])
    classification = cast("dict[str, object]", aggregate["classification"])
    performance = cast("dict[str, object]", aggregate["performance"])
    gates = cast("dict[str, object]", report["gate_assessment"])
    print(
        json.dumps(
            {
                "direction_accuracy": classification["direction_accuracy"],
                "net_compound_return": performance["net_compound_return"],
                "annualized_sharpe": performance["annualized_sharpe"],
                "global_promotion": gates["global_promotion"],
                "report": report_directory.as_posix(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
