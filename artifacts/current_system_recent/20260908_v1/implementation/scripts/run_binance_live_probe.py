"""Run a bounded Binance public-only REST/WS smoke probe and write auditable evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from websockets.asyncio.client import connect

from aegisquant.data.providers.binance.contracts import (
    Product,
    RestEndpoint,
    StreamKind,
    assert_public_url,
    build_ws_url,
)
from aegisquant.data.providers.binance.replay import FixtureEnvelope, write_fixture
from aegisquant.data.providers.binance.rest import BinancePublicRestClient


async def receive_one(
    url: str,
) -> tuple[dict[str, object], dict[str, object] | list[object], datetime]:
    assert_public_url(url, websocket=True)
    started = datetime.now(UTC)
    async with connect(
        url,
        ping_interval=None,
        ping_timeout=None,
        open_timeout=10,
        close_timeout=5,
        max_size=2 * 1024 * 1024,
        compression=None,
        additional_headers={"User-Agent": "AegisQuant/3.1 public-market-data-probe"},
        proxy=None,
    ) as socket:
        raw = await asyncio.wait_for(socket.recv(decode=False), timeout=20)
    content = raw
    decoded: object = json.loads(content)
    keys: list[str] = []
    event_type: str | None = None
    symbol: str | None = None
    if isinstance(decoded, dict):
        row = cast(dict[object, object], decoded)
        keys = sorted(str(key) for key in row)[:64]
        raw_event = row.get("e")
        raw_symbol = row.get("s")
        event_type = raw_event if isinstance(raw_event, str) else None
        symbol = raw_symbol if isinstance(raw_symbol, str) else None
    if not isinstance(decoded, (dict, list)):
        raise ValueError("public fixture payload must be a JSON object or array")
    fixture_payload = cast(dict[str, object] | list[object], decoded)
    received_at = datetime.now(UTC)
    evidence: dict[str, object] = {
        "url": url,
        "connected_at_utc": started.isoformat().replace("+00:00", "Z"),
        "received_at_utc": received_at.isoformat().replace("+00:00", "Z"),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "json_keys": keys,
        "event_type": event_type,
        "symbol": symbol,
    }
    return evidence, fixture_payload, received_at


def rest_probe() -> list[dict[str, object]]:
    requests: tuple[tuple[RestEndpoint, dict[str, str | int] | None], ...] = (
        (RestEndpoint.SPOT_TIME, None),
        (RestEndpoint.SPOT_EXCHANGE_INFO, {"symbol": "BTCUSDT"}),
        (RestEndpoint.SPOT_DEPTH, {"symbol": "BTCUSDT", "limit": 100}),
        (RestEndpoint.USDM_TIME, None),
        (RestEndpoint.USDM_EXCHANGE_INFO, None),
        (RestEndpoint.USDM_DEPTH, {"symbol": "BTCUSDT", "limit": 100}),
        (RestEndpoint.USDM_MARK_INDEX, {"symbol": "BTCUSDT"}),
        (RestEndpoint.USDM_FUNDING, {"symbol": "BTCUSDT", "limit": 1}),
        (RestEndpoint.USDM_OPEN_INTEREST, {"symbol": "BTCUSDT"}),
    )
    evidence: list[dict[str, object]] = []
    with BinancePublicRestClient(timeout_seconds=15, maximum_attempts=3) as client:
        for endpoint, parameters in requests:
            response = client.get(endpoint, parameters)
            evidence.append(
                {
                    "endpoint": endpoint.value,
                    "request_url": response.request_url,
                    "request_hash": response.request_hash,
                    "status_code": response.status_code,
                    "received_at_utc": response.received_at.isoformat().replace("+00:00", "Z"),
                    "elapsed_ms": response.elapsed_ms,
                    "content_bytes": len(response.content),
                    "content_sha256": response.content_sha256,
                    "rate_limit_headers": response.rate_limit_headers,
                }
            )
    return evidence


async def run_probe(*, fixture_output: Path | None = None) -> dict[str, object]:
    started = datetime.now(UTC)
    rest = await asyncio.to_thread(rest_probe)
    urls = (
        build_ws_url(product=Product.SPOT, kind=StreamKind.BOOK_TICKER, symbol="BTCUSDT"),
        build_ws_url(product=Product.SPOT, kind=StreamKind.DEPTH, symbol="BTCUSDT"),
        build_ws_url(product=Product.USD_M, kind=StreamKind.DEPTH, symbol="BTCUSDT"),
        build_ws_url(product=Product.USD_M, kind=StreamKind.AGG_TRADE, symbol="BTCUSDT"),
        build_ws_url(product=Product.USD_M, kind=StreamKind.MARK_PRICE, symbol="BTCUSDT"),
    )
    received = await asyncio.gather(*(receive_one(url) for url in urls))
    websocket = [item[0] for item in received]
    fixture_summary: dict[str, object] | None = None
    if fixture_output is not None:
        ordered = sorted(
            zip(urls, received, strict=True),
            key=lambda pair: pair[1][2],
        )
        records = tuple(
            FixtureEnvelope.create(
                sequence=index,
                product=(Product.USD_M if "fstream.binance.com" in url else Product.SPOT),
                channel=url,
                observed_at=item[2],
                payload=item[1],
            )
            for index, (url, item) in enumerate(ordered)
        )
        fixture_manifest = write_fixture(fixture_output, records)
        fixture_summary = {
            "path": fixture_output.as_posix(),
            "sha256": fixture_manifest.sha256,
            "event_count": fixture_manifest.event_count,
            "contains_credentials": fixture_manifest.contains_credentials,
        }
    finished = datetime.now(UTC)
    return {
        "schema_version": "1.0.0",
        "phase": "P03",
        "status": "passed",
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "finished_at_utc": finished.isoformat().replace("+00:00", "Z"),
        "duration_seconds": (finished - started).total_seconds(),
        "network_scope": "Binance official public market data only",
        "authentication_used": False,
        "cookies_used": False,
        "account_access_performed": False,
        "order_capability_present": False,
        "live_trading_locked": True,
        "rest": rest,
        "websocket": websocket,
        "recorded_fixture": fixture_summary,
    }


def write_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/data/BINANCE_LIVE_SAMPLE.json"),
    )
    parser.add_argument("--fixture-output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        fixture_output = root / args.fixture_output if args.fixture_output is not None else None
        payload = asyncio.run(run_probe(fixture_output=fixture_output))
    except Exception as error:
        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "phase": "P03",
            "status": "failed",
            "failed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "error_type": type(error).__name__,
            "error": str(error),
            "authentication_used": False,
            "account_access_performed": False,
            "order_capability_present": False,
            "live_trading_locked": True,
        }
        write_atomic(root / args.output, payload)
        raise
    write_atomic(root / args.output, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
