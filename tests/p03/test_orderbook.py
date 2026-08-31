"""Spot and USD-M sequence, duplicate, late, gap, and crossed-book behavior."""

from decimal import Decimal
from pathlib import Path
from typing import cast

from aegisquant.data.providers.binance.contracts import Product
from aegisquant.data.providers.binance.normalization import normalize_depth_delta
from aegisquant.data.providers.binance.orderbook import (
    ApplyDisposition,
    LocalOrderBook,
    OrderBookSnapshot,
)
from tests.p03.helpers import OBSERVED, REQUEST_HASH, fixture


def _snapshot(payload: object, *, product: Product) -> OrderBookSnapshot:
    row = cast(dict[str, object], payload)
    bids = cast(list[list[str]], row["bids"])
    asks = cast(list[list[str]], row["asks"])
    return OrderBookSnapshot(
        product=product,
        symbol="BTCUSDT",
        last_update_id=cast(int, row["lastUpdateId"]),
        bids=tuple((Decimal(price), Decimal(quantity)) for price, quantity in bids),
        asks=tuple((Decimal(price), Decimal(quantity)) for price, quantity in asks),
    )


def _events(project_root: Path, product: Product) -> tuple[object, ...]:
    folder = "spot" if product is Product.SPOT else "usdm"
    return tuple(cast(list[object], fixture(project_root, f"{folder}/depth_events.json")))


def test_spot_buffer_snapshot_duplicate_late_and_gap(project_root: Path) -> None:
    book = LocalOrderBook(product=Product.SPOT, symbol="BTCUSDT")
    events = tuple(
        normalize_depth_delta(
            payload,
            product=Product.SPOT,
            symbol="BTCUSDT",
            observed_at=OBSERVED,
            request_hash=REQUEST_HASH,
            source="spot_depth",
        )
        for payload in _events(project_root, Product.SPOT)
    )
    assert book.buffer_or_apply(events[0]).disposition is ApplyDisposition.BUFFERED
    replayed = book.load_snapshot(
        _snapshot(fixture(project_root, "spot/depth_snapshot.json"), product=Product.SPOT)
    )
    assert replayed[0].disposition is ApplyDisposition.APPLIED
    assert book.best_bid_ask() == (
        (Decimal("100.00"), Decimal("1.50000000")),
        (Decimal("102.00"), Decimal("2.00000000")),
    )
    assert book.apply(events[1]).disposition is ApplyDisposition.DUPLICATE
    assert book.apply(events[2]).disposition is ApplyDisposition.LATE
    gap = book.apply(events[3])
    assert gap.disposition is ApplyDisposition.GAP
    assert gap.recovery_required is True
    assert book.apply(events[1]).disposition is ApplyDisposition.RECOVERY_REQUIRED


def test_usdm_requires_previous_final_update_id_after_first_event(project_root: Path) -> None:
    book = LocalOrderBook(product=Product.USD_M, symbol="BTCUSDT")
    book.load_snapshot(
        _snapshot(fixture(project_root, "usdm/depth_snapshot.json"), product=Product.USD_M)
    )
    events = tuple(
        normalize_depth_delta(
            payload,
            product=Product.USD_M,
            symbol="BTCUSDT",
            observed_at=OBSERVED,
            request_hash=REQUEST_HASH,
            source="usdm_depth",
        )
        for payload in _events(project_root, Product.USD_M)
    )
    assert book.apply(events[0]).disposition is ApplyDisposition.APPLIED
    assert book.apply(events[1]).disposition is ApplyDisposition.APPLIED
    gap = book.apply(events[2])
    assert gap.disposition is ApplyDisposition.GAP
    assert gap.reason_code.endswith("PREVIOUS-SEQUENCE-GAP")


def test_forced_resnapshot_drops_stale_watermark(project_root: Path) -> None:
    book = LocalOrderBook(product=Product.SPOT, symbol="BTCUSDT")
    book.load_snapshot(
        _snapshot(fixture(project_root, "spot/depth_snapshot.json"), product=Product.SPOT)
    )
    book.force_resnapshot()
    assert book.last_update_id is None
    assert book.bids == {}
    assert book.asks == {}
