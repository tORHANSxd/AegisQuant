from __future__ import annotations

import pytest

from aegisquant.data.market import Venue
from aegisquant.data.providers.public import (
    PublicOrderBook,
    PublicSequenceTracker,
    SequenceDisposition,
    parse_orderbook_update,
)


@pytest.mark.parametrize("venue", [Venue.OKX, Venue.BYBIT, Venue.DERIBIT])
def test_delta_before_snapshot_requires_recovery(venue: Venue) -> None:
    result = PublicSequenceTracker(venue).apply(action="update", sequence=10, previous_sequence=9)
    assert result.disposition is SequenceDisposition.GAP
    assert result.recovery_required is True


def test_okx_prev_seq_id_and_deribit_prev_change_id_are_enforced() -> None:
    for venue in (Venue.OKX, Venue.DERIBIT):
        tracker = PublicSequenceTracker(venue)
        assert (
            tracker.apply(action="snapshot", sequence=100).disposition
            is SequenceDisposition.SNAPSHOT
        )
        assert (
            tracker.apply(action="update", sequence=101, previous_sequence=100).disposition
            is SequenceDisposition.APPLIED
        )
        assert (
            tracker.apply(action="update", sequence=103, previous_sequence=102).disposition
            is SequenceDisposition.GAP
        )


def test_bybit_snapshot_delta_and_u_one_restart() -> None:
    tracker = PublicSequenceTracker(Venue.BYBIT)
    tracker.apply(action="snapshot", sequence=500)
    assert tracker.apply(action="delta", sequence=501).disposition is SequenceDisposition.APPLIED
    assert tracker.apply(action="delta", sequence=503).disposition is SequenceDisposition.GAP
    assert tracker.apply(action="delta", sequence=1).disposition is SequenceDisposition.SNAPSHOT
    assert tracker.watermark == 1


def test_duplicate_does_not_advance_watermark() -> None:
    tracker = PublicSequenceTracker(Venue.OKX)
    tracker.apply(action="snapshot", sequence=5)
    result = tracker.apply(action="update", sequence=5, previous_sequence=4)
    assert result.disposition is SequenceDisposition.DUPLICATE
    assert result.watermark == 5


@pytest.mark.parametrize(
    ("venue", "symbol", "snapshot", "delta"),
    [
        (
            Venue.OKX,
            "BTC-USDT-SWAP",
            {
                "action": "snapshot",
                "data": [
                    {"seqId": 100, "prevSeqId": -1, "bids": [["100", "2"]], "asks": [["101", "3"]]}
                ],
            },
            {
                "action": "update",
                "data": [
                    {
                        "seqId": 101,
                        "prevSeqId": 100,
                        "bids": [["100", "0"], ["99", "4"]],
                        "asks": [["101", "2"]],
                    }
                ],
            },
        ),
        (
            Venue.BYBIT,
            "BTCUSDT",
            {
                "type": "snapshot",
                "data": {"u": 500, "seq": 1000, "b": [["100", "2"]], "a": [["101", "3"]]},
            },
            {
                "type": "delta",
                "data": {
                    "u": 501,
                    "seq": 1001,
                    "b": [["100", "0"], ["99", "4"]],
                    "a": [["101", "2"]],
                },
            },
        ),
        (
            Venue.DERIBIT,
            "BTC-PERPETUAL",
            {
                "params": {
                    "data": {
                        "type": "snapshot",
                        "change_id": 700,
                        "bids": [[100, 2]],
                        "asks": [[101, 3]],
                    }
                }
            },
            {
                "params": {
                    "data": {
                        "type": "change",
                        "change_id": 701,
                        "prev_change_id": 700,
                        "bids": [["delete", 100, 0], ["new", 99, 4]],
                        "asks": [["change", 101, 2]],
                    }
                }
            },
        ),
    ],
)
def test_venue_orderbooks_apply_snapshot_and_delta_without_cross_contamination(
    venue: Venue,
    symbol: str,
    snapshot: dict[str, object],
    delta: dict[str, object],
) -> None:
    book = PublicOrderBook(venue, symbol)
    first = book.apply(parse_orderbook_update(venue, snapshot, symbol=symbol))
    second = book.apply(parse_orderbook_update(venue, delta, symbol=symbol))
    assert first.disposition is SequenceDisposition.SNAPSHOT
    assert second.disposition is SequenceDisposition.APPLIED
    assert book.best_bid_ask()[0][0] == 99
    assert book.best_bid_ask()[1] == (101, 2)


def test_crossed_delta_rolls_back_levels_and_requires_recovery() -> None:
    book = PublicOrderBook(Venue.OKX, "BTC-USDT-SWAP")
    snapshot = parse_orderbook_update(
        Venue.OKX,
        {
            "action": "snapshot",
            "data": [
                {"seqId": 10, "prevSeqId": -1, "bids": [["100", "1"]], "asks": [["101", "1"]]}
            ],
        },
        symbol="BTC-USDT-SWAP",
    )
    book.apply(snapshot)
    crossed = parse_orderbook_update(
        Venue.OKX,
        {
            "action": "update",
            "data": [{"seqId": 11, "prevSeqId": 10, "bids": [["102", "1"]], "asks": []}],
        },
        symbol="BTC-USDT-SWAP",
    )
    result = book.apply(crossed)
    assert result.disposition is SequenceDisposition.GAP
    assert result.recovery_required is True
    assert book.best_bid_ask() == ((100, 1), (101, 1))
