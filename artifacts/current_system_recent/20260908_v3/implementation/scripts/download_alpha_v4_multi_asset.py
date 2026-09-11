"""Fetch only public spot history into a new, fixed-universe experiment directory."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import yaml

from aegisquant.data.providers.binance.rest import BinancePublicRestClient
from aegisquant.research.validation.public_market_backtest import (
    RealBacktestConfig,
    load_or_download_spot_klines,
    write_bronze_csv,
)
from scripts.run_alpha_v4_walkforward import digest, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    policy_path = root / "configs/research/alpha_v4_multi_asset.yaml"
    policy = cast(dict[str, Any], yaml.safe_load(policy_path.read_text(encoding="utf-8")))
    output = root / "artifacts/alpha_v4_multi_asset"
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "source_manifest.json"
    if args.check:
        manifest = cast(dict[str, Any], yaml.safe_load(manifest_path.read_text(encoding="utf-8")))
        if manifest["config_sha256"] != digest(policy_path):
            raise ValueError("fixed universe configuration changed")
        for row in manifest["datasets"]:
            if digest(root / row["path"]) != row["sha256"]:
                raise ValueError(f"source dataset hash mismatch: {row['symbol']}")
        print("fixed multi-asset public history hashes verified")
        return 0
    if manifest_path.exists():
        raise FileExistsError("source manifest already sealed; use --check")
    config = RealBacktestConfig(
        symbols=tuple(policy["symbols"]),
        start_at=datetime.fromisoformat(policy["first_train_start"]),
        end_at_exclusive=datetime.fromisoformat(policy["development_end"]),
    )
    write_json(
        output / "preregistration.json", {"config_sha256": digest(policy_path), "policy": policy}
    )
    rows: list[dict[str, Any]] = []
    bronze = root / "data/bronze/alpha_v4_multi_asset"
    bronze.mkdir(parents=True, exist_ok=True)
    with BinancePublicRestClient(timeout_seconds=20, maximum_attempts=4) as client:
        for symbol in config.symbols:
            if symbol in {"BTCUSDT", "ETHUSDT"}:
                path = root / "data/bronze/real_market_backtest" / f"{symbol}_1h.csv"
                rows.append(
                    {
                        "symbol": symbol,
                        "path": str(path.relative_to(root)),
                        "sha256": digest(path),
                        "source": "PRESERVED_EXISTING_PUBLIC_HISTORY",
                    }
                )
                continue
            print(f"download official spot {symbol} 2021-01..2025-10", flush=True)
            download = load_or_download_spot_klines(
                config=config,
                symbol=symbol,
                raw_root=root / "data/raw/alpha_v4_multi_asset",
                client=client,
            )
            path = bronze / f"{symbol}_1h.csv"
            file_hash = write_bronze_csv(download, path)
            rows.append(
                {
                    "symbol": symbol,
                    "path": str(path.relative_to(root)),
                    "sha256": file_hash,
                    "source": "BINANCE_OFFICIAL_PUBLIC_REST",
                    "download": download.source_manifest,
                }
            )
            print(f"saved {symbol} {len(download.rows)} hourly candles", flush=True)
    write_json(
        manifest_path,
        {
            "config_sha256": digest(policy_path),
            "datasets": rows,
            "authentication_used": False,
            "final_holdout_access_count": 0,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
