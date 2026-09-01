"""Bounded P05 ledger throughput smoke benchmark."""

from __future__ import annotations

import time
from pathlib import Path

from aegisquant.domain.execution import OrderSide
from tests.p05.helpers import engine, fill, linear_instrument


def test_two_thousand_fill_replay_completes_within_ten_seconds(project_root: Path) -> None:
    spec = linear_instrument()
    ledger = engine(project_root)
    started = time.perf_counter()
    for sequence in range(1, 2001):
        ledger.process_fill(
            fill(
                spec,
                sequence=sequence,
                side=OrderSide.BUY if sequence % 2 else OrderSide.SELL,
                quantity="1",
                price=str(100 + sequence % 7),
            ),
            spec,
        )
    elapsed = time.perf_counter() - started
    assert len(ledger.records) == 2000
    assert elapsed < 10
