# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Pinned NautilusTrader replay probe; never an authoritative accounting source."""

from __future__ import annotations

import hashlib
import json
import warnings
from importlib.metadata import version
from typing import Any

from aegisquant.domain.base import DomainModel


class NautilusContractEvidence(DomainModel):
    package_version: str
    expected_version: str
    deterministic: bool
    first_digest: str
    second_digest: str
    stable_state: dict[str, int | str | None]
    authentication_used: bool = False
    account_access_performed: bool = False
    order_capability_used: bool = False


def _replay() -> tuple[str, dict[str, int | str | None]]:
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Money, Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

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
    engine = BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
    try:
        engine.add_venue(
            venue=Venue("BINANCE"),
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money.from_str("1 BTC"), Money.from_str("100000 USDT")],
        )
        engine.add_instrument(instrument)
        engine.add_data(ticks)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Timestamp.utcnow is deprecated.*",
                category=DeprecationWarning,
            )
            engine.run()
        result: Any = engine.get_result()
        last_quote: Any = engine.cache.quote_tick(instrument.id)
        stable_state: dict[str, int | str | None] = {
            "input_quote_count": len(ticks),
            "iterations": int(result.iterations),
            "backtest_start": int(result.backtest_start),
            "backtest_end": int(result.backtest_end),
            "total_events": int(result.total_events),
            "total_orders": int(result.total_orders),
            "total_positions": int(result.total_positions),
            "last_quote": str(last_quote),
        }
        encoded = json.dumps(stable_state, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest(), stable_state
    finally:
        engine.dispose()


def verify_nautilus_contract(expected_version: str = "1.231.0") -> NautilusContractEvidence:
    installed = version("nautilus-trader")
    if installed != expected_version:
        raise ValueError("AQ-BACKTEST-NAUTILUS-VERSION-CONFLICT")
    first_digest, first_state = _replay()
    second_digest, second_state = _replay()
    return NautilusContractEvidence(
        package_version=installed,
        expected_version=expected_version,
        deterministic=first_digest == second_digest and first_state == second_state,
        first_digest=first_digest,
        second_digest=second_digest,
        stable_state=first_state,
    )
