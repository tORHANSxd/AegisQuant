"""Generate deterministic offline P03 Binance contract, replay, and compatibility evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

import yaml

from aegisquant.data.providers.binance.changelog import inspect_changelog
from aegisquant.data.providers.binance.contracts import Product
from aegisquant.data.providers.binance.models import PriceBasis
from aegisquant.data.providers.binance.nautilus_compat import inspect_installed_nautilus
from aegisquant.data.providers.binance.normalization import (
    normalize_book_ticker,
    normalize_depth_delta,
    normalize_kline,
    normalize_trade,
)
from aegisquant.data.providers.binance.orderbook import LocalOrderBook, OrderBookSnapshot
from aegisquant.data.providers.binance.quality import compare_book_ticker, compare_kline_trades

ROOT: Final = Path(__file__).resolve().parents[1]
FIXTURE_ROOT: Final = ROOT / "tests/fixtures/binance"
OBSERVED: Final = datetime(2026, 8, 31, 14, 30, tzinfo=UTC)
REQUEST_HASH: Final = "1" * 64


def _json_fixture(relative: str) -> object:
    return cast(
        object,
        json.loads((FIXTURE_ROOT / relative).read_text(encoding="utf-8")),
    )


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _snapshot(relative: str, product: Product) -> OrderBookSnapshot:
    raw = cast(dict[str, object], _json_fixture(relative))
    bids = cast(list[list[str]], raw["bids"])
    asks = cast(list[list[str]], raw["asks"])
    return OrderBookSnapshot(
        product=product,
        symbol="BTCUSDT",
        last_update_id=cast(int, raw["lastUpdateId"]),
        bids=tuple((Decimal(price), Decimal(quantity)) for price, quantity in bids),
        asks=tuple((Decimal(price), Decimal(quantity)) for price, quantity in asks),
    )


def fixture_manifest() -> dict[str, object]:
    entries: list[dict[str, object]] = []
    response_cookie_header = b"set-" + b"cookie" + b":"
    forbidden = (b"api_secret", b"x-mbx-apikey", b"authorization:", response_cookie_header)
    for path in sorted(FIXTURE_ROOT.rglob("*")):
        if not path.is_file() or path.name == "fixture_manifest.json":
            continue
        content = path.read_bytes()
        folded = content.lower()
        if any(token in folded for token in forbidden):
            raise ValueError(f"fixture may contain credential material: {path}")
        entries.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    return {
        "schema_version": "1.0.0",
        "generated_at_utc": "2026-08-31T14:30:00Z",
        "source": "Binance official public market-data documentation examples and bounded public frames",
        "contains_credentials": False,
        "file_count": len(entries),
        "total_bytes": sum(cast(int, entry["size_bytes"]) for entry in entries),
        "files": entries,
    }


def orderbook_evidence() -> tuple[str, dict[str, object]]:
    sections: list[str] = []
    machine: dict[str, object] = {}
    for product, folder in ((Product.SPOT, "spot"), (Product.USD_M, "usdm")):
        book = LocalOrderBook(product=product, symbol="BTCUSDT")
        book.load_snapshot(_snapshot(f"{folder}/depth_snapshot.json", product))
        results: list[dict[str, object]] = []
        for raw in cast(list[object], _json_fixture(f"{folder}/depth_events.json")):
            event = normalize_depth_delta(
                raw,
                product=product,
                symbol="BTCUSDT",
                observed_at=OBSERVED,
                request_hash=REQUEST_HASH,
                source=f"{folder}_depth",
            )
            result = book.apply(event)
            results.append(result.model_dump(mode="json"))
        machine[product.value] = results
        sections.append(
            f"| {product.value} | "
            + " → ".join(cast(str, row["disposition"]) for row in results)
            + f" | {results[-1]['recovery_required']} |"
        )
    markdown = (
        """# Binance 订单簿恢复证据

固定 fixture 验证快照加增量、重复、迟到及 sequence gap。数量为绝对数量，零数量删除价位。

| 产品 | 处理序列 | 最终要求重建 |
|---|---|---|
"""
        + "\n".join(sections)
        + "\n"
    )
    return markdown, machine


def consistency_evidence() -> tuple[str, dict[str, object]]:
    kline = normalize_kline(
        _json_fixture("spot/kline.json"),
        product=Product.SPOT,
        symbol="BTCUSDT",
        interval="1m",
        price_basis=PriceBasis.TRADE,
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="spot_klines",
    )
    trades = tuple(
        normalize_trade(
            raw,
            product=Product.SPOT,
            symbol="BTCUSDT",
            aggregate=False,
            observed_at=OBSERVED,
            request_hash=REQUEST_HASH,
            source="spot_trades",
        )
        for raw in cast(list[object], _json_fixture("spot/trades.json"))
    )
    kline_report = compare_kline_trades(kline, trades)
    book = LocalOrderBook(product=Product.SPOT, symbol="BTCUSDT")
    book.load_snapshot(_snapshot("spot/depth_snapshot.json", Product.SPOT))
    first_depth = cast(list[object], _json_fixture("spot/depth_events.json"))[0]
    book.apply(
        normalize_depth_delta(
            first_depth,
            product=Product.SPOT,
            symbol="BTCUSDT",
            observed_at=OBSERVED,
            request_hash=REQUEST_HASH,
            source="spot_depth",
        )
    )
    ticker = normalize_book_ticker(
        _json_fixture("spot/book_ticker.json"),
        product=Product.SPOT,
        symbol="BTCUSDT",
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="spot_book_ticker",
    )
    ticker_report = compare_book_ticker(book, ticker)
    machine: dict[str, object] = {
        "kline_vs_trades": kline_report.model_dump(mode="json"),
        "book_vs_ticker": ticker_report.model_dump(mode="json"),
        "passed": kline_report.passed and ticker_report.passed,
    }
    markdown = f"""# Binance 一致性检查

- Kline vs trades：`{"PASS" if kline_report.passed else "FAIL"}`
- Local book vs bookTicker：`{"PASS" if ticker_report.passed else "FAIL"}`
- 时间字段：event/available/ingest/processed/revision 均由严格模型约束。
- 不完整 Kline：保留 `close_time`，并标记 `INCOMPLETE_KLINE`，不静默当作收盘数据。
"""
    return markdown, machine


def expected_outputs() -> dict[Path, bytes]:
    contract = cast(
        dict[str, object],
        yaml.safe_load((ROOT / "data/contracts/binance_public_contracts.yaml").read_text()),
    )
    rest_endpoints = cast(list[object], contract["rest_endpoints"])
    streams = cast(list[object], contract["websocket_streams"])
    contract_markdown = f"""# Binance 公开市场数据契约

- 复核时间：`{contract["reviewed_at_utc"]}`
- 认证：`{contract["authentication"]}`
- REST 契约数：{len(rest_endpoints)}
- WS stream 契约数：{len(streams)}
- Spot REST：`https://data-api.binance.vision`
- Spot WS：`wss://data-stream.binance.vision`
- USDⓈ-M 深度/BookTicker：`wss://fstream.binance.com/public`
- USDⓈ-M 成交/Kline/Mark：`wss://fstream.binance.com/market`
- 禁止：账户、订单、用户数据流、签名请求与 `/private`。

机器可读清单：`data/contracts/binance_public_contracts.yaml`。
"""
    orderbook_markdown, orderbook_json = orderbook_evidence()
    consistency_markdown, consistency_json = consistency_evidence()
    spot_changelog = inspect_changelog(
        source_name="binance_spot",
        source_url=cast(dict[str, str], contract["source_documents"])["spot_changelog"],
        content=(FIXTURE_ROOT / "spot_changelog.md").read_bytes(),
        observed_at=OBSERVED,
    )
    usdm_changelog = inspect_changelog(
        source_name="binance_usdm",
        source_url="https://developers.binance.com/docs/derivatives/change-log",
        content=(FIXTURE_ROOT / "usdm_changelog.md").read_bytes(),
        observed_at=OBSERVED,
    )
    changelog = {
        "schema_version": "1.0.0",
        "network_used": False,
        "snapshots": [
            spot_changelog.model_dump(mode="json"),
            usdm_changelog.model_dump(mode="json"),
        ],
    }
    semantics = inspect_installed_nautilus()
    semantics_json = semantics.model_dump(mode="json")
    semantics_markdown = f"""# Binance / NautilusTrader 语义对照

- 已安装版本：`{semantics.installed_version}`
- Spot instrument：`{semantics.spot_instrument_example}`
- USDⓈ-M instrument：`{semantics.usdm_instrument_example}`
- USDⓈ-M market route：`{semantics.usdm_market_ws_base}`
- USDⓈ-M public book route：`{semantics.usdm_public_ws_base}`
- 与 P03 路由契约一致：`{semantics.routes_match_p03_contract}`
- 凭据访问：`{semantics.credentials_accessed}`

Nautilus 的纯 URL helper 和命名语义用于兼容性核验；AegisQuant 原始归档、PIT、质量与
Silver 数据湖仍由本项目适配器负责。
"""
    return {
        ROOT / "tests/fixtures/binance/fixture_manifest.json": _json_bytes(fixture_manifest()),
        ROOT / "reports/data/BINANCE_PUBLIC_CONTRACTS.md": contract_markdown.encode(),
        ROOT / "reports/data/BINANCE_ORDERBOOK_RECOVERY.md": orderbook_markdown.encode(),
        ROOT / "reports/data/BINANCE_ORDERBOOK_RECOVERY.json": _json_bytes(orderbook_json),
        ROOT / "reports/data/BINANCE_CONSISTENCY_CHECKS.md": consistency_markdown.encode(),
        ROOT / "reports/data/BINANCE_CONSISTENCY_CHECKS.json": _json_bytes(consistency_json),
        ROOT / "reports/data/BINANCE_CHANGELOG_WATCH.json": _json_bytes(changelog),
        ROOT / "reports/compatibility/BINANCE_NAUTILUS_SEMANTICS.json": _json_bytes(semantics_json),
        ROOT / "reports/compatibility/BINANCE_NAUTILUS_SEMANTICS.md": semantics_markdown.encode(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = expected_outputs()
    if args.check:
        stale = [
            path
            for path, content in outputs.items()
            if not path.is_file() or path.read_bytes() != content
        ]
        if stale:
            raise SystemExit(
                f"P03 Binance evidence is stale: {[path.as_posix() for path in stale]}"
            )
        print(f"verified {len(outputs)} P03 Binance evidence artifacts")
        return 0
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"wrote {len(outputs)} P03 Binance evidence artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
