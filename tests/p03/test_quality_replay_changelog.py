"""Cross-stream consistency, immutable replay, and changelog watcher tests."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from aegisquant.data.providers.binance.changelog import (
    inspect_changelog,
    load_changelog_state,
    write_changelog_state,
)
from aegisquant.data.providers.binance.contracts import Product
from aegisquant.data.providers.binance.models import PriceBasis
from aegisquant.data.providers.binance.normalization import (
    normalize_book_ticker,
    normalize_depth_delta,
    normalize_kline,
    normalize_trade,
)
from aegisquant.data.providers.binance.orderbook import LocalOrderBook, OrderBookSnapshot
from aegisquant.data.providers.binance.quality import compare_book_ticker, compare_kline_trades
from aegisquant.data.providers.binance.replay import FixtureEnvelope, load_fixture, write_fixture
from tests.p03.helpers import OBSERVED, REQUEST_HASH, fixture


def test_kline_trade_and_book_ticker_consistency(project_root: Path) -> None:
    kline = normalize_kline(
        fixture(project_root, "spot/kline.json"),
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
            row,
            product=Product.SPOT,
            symbol="BTCUSDT",
            aggregate=False,
            observed_at=OBSERVED,
            request_hash=REQUEST_HASH,
            source="spot_trades",
        )
        for row in cast(list[object], fixture(project_root, "spot/trades.json"))
    )
    assert compare_kline_trades(kline, trades).passed is True

    snapshot = cast(dict[str, object], fixture(project_root, "spot/depth_snapshot.json"))
    book = LocalOrderBook(product=Product.SPOT, symbol="BTCUSDT")
    book.load_snapshot(
        OrderBookSnapshot(
            product=Product.SPOT,
            symbol="BTCUSDT",
            last_update_id=cast(int, snapshot["lastUpdateId"]),
            bids=((Decimal("100"), Decimal("1")),),
            asks=((Decimal("101"), Decimal("2")),),
        )
    )
    depth_payload = cast(list[object], fixture(project_root, "spot/depth_events.json"))[0]
    book.apply(
        normalize_depth_delta(
            depth_payload,
            product=Product.SPOT,
            symbol="BTCUSDT",
            observed_at=OBSERVED,
            request_hash=REQUEST_HASH,
            source="spot_depth",
        )
    )
    ticker = normalize_book_ticker(
        fixture(project_root, "spot/book_ticker.json"),
        product=Product.SPOT,
        symbol="BTCUSDT",
        observed_at=OBSERVED,
        request_hash=REQUEST_HASH,
        source="spot_book_ticker",
    )
    assert compare_book_ticker(book, ticker).passed is True


def test_fixture_round_trip_is_hash_checked_and_immutable(tmp_path: Path) -> None:
    observed = datetime(2026, 8, 31, 14, tzinfo=UTC)
    records = (
        FixtureEnvelope.create(
            sequence=0,
            product=Product.SPOT,
            channel="btcusdt@bookTicker",
            observed_at=observed,
            payload={"u": 1, "b": "100", "a": "101"},
        ),
        FixtureEnvelope.create(
            sequence=1,
            product=Product.USD_M,
            channel="btcusdt@markPrice@1s",
            observed_at=observed,
            payload={"e": "markPriceUpdate", "p": "100.5", "i": "100.4"},
        ),
    )
    path = tmp_path / "public.jsonl"
    first = write_fixture(path, records)
    second = write_fixture(path, records)
    assert first == second
    assert load_fixture(path) == records
    tampered = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    tampered["payload"]["b"] = "999"
    path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid fixture line"):
        load_fixture(path)


def test_committed_live_fixture_is_public_hash_checked_and_manifested(project_root: Path) -> None:
    path = project_root / "tests/fixtures/binance/recorded_public.jsonl"
    records = load_fixture(path)
    manifest = json.loads(
        (project_root / "tests/fixtures/binance/fixture_manifest.json").read_text(encoding="utf-8")
    )
    entry = next(row for row in manifest["files"] if row["path"].endswith("recorded_public.jsonl"))
    assert len(records) == 5
    assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest["contains_credentials"] is False
    assert {record.product for record in records} == {Product.SPOT, Product.USD_M}


def test_changelog_watcher_hashes_dates_and_changes(tmp_path: Path, project_root: Path) -> None:
    spot_content = (project_root / "tests/fixtures/binance/spot_changelog.md").read_bytes()
    first = inspect_changelog(
        source_name="binance_spot",
        source_url="https://github.com/binance/binance-spot-api-docs/blob/master/CHANGELOG.md",
        content=spot_content,
        observed_at=OBSERVED,
    )
    assert first.latest_entry_date == "2026-07-27"
    assert first.changed is False
    second = inspect_changelog(
        source_name="binance_spot",
        source_url=first.source_url,
        content=spot_content + b"\n## 2026-08-31\n",
        observed_at=OBSERVED,
        previous=first,
    )
    assert second.changed is True
    assert second.latest_entry_date == "2026-08-31"
    path = tmp_path / "state.json"
    write_changelog_state(path, second)
    assert load_changelog_state(path) == second
