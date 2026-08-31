"""NautilusTrader deterministic minimal replay contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider


def replay_digest() -> tuple[str, dict[str, Any]]:
    """Replay three fixed quote ticks and hash only stable economic state."""
    instrument = TestInstrumentProvider.btcusdt_binance()
    ticks = [
        QuoteTick(
            instrument_id=instrument.id,
            bid_price=Price.from_str(bid),
            ask_price=Price.from_str(ask),
            bid_size=Quantity.from_str("1.000000"),
            ask_size=Quantity.from_str("2.000000"),
            ts_event=timestamp,
            ts_init=timestamp,
        )
        for bid, ask, timestamp in (
            ("50000.00", "50001.00", 1_700_000_000_000_000_000),
            ("50001.00", "50002.00", 1_700_000_001_000_000_000),
            ("50003.00", "50004.00", 1_700_000_002_000_000_000),
        )
    ]
    engine = BacktestEngine(
        config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")),
    )
    try:
        engine.add_venue(
            venue=Venue("BINANCE"),
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money.from_str("1 BTC"), Money.from_str("100000 USDT")],
        )
        engine.add_instrument(instrument)
        engine.add_data(ticks)
        engine.run()
        result = engine.get_result()
        last_quote = engine.cache.quote_tick(instrument.id)
        stable_state = {
            "iterations": result.iterations,
            "backtest_start": result.backtest_start,
            "backtest_end": result.backtest_end,
            "total_events": result.total_events,
            "total_orders": result.total_orders,
            "total_positions": result.total_positions,
            "last_quote": str(last_quote),
        }
        encoded = json.dumps(stable_state, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest(), stable_state
    finally:
        engine.dispose()


@pytest.mark.nautilus
def test_fixed_replay_is_identical_across_fresh_engines() -> None:
    first_digest, first_state = replay_digest()
    second_digest, second_state = replay_digest()

    assert first_state == second_state
    assert first_digest == second_digest
    assert first_state["iterations"] == 3
    assert first_state["backtest_start"] == 1_700_000_000_000_000_000
    assert first_state["backtest_end"] == 1_700_000_002_000_000_000
    assert first_state["total_orders"] == 0
