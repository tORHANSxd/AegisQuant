"""P00 fail-closed Live Trading boundary tests."""

import json
import tomllib
from pathlib import Path

import pytest

from aegisquant.bootstrap.live_lock import (
    ERROR_CODE,
    LIVE_ADAPTERS,
    LIVE_TRADING,
    ORDER_SUBMISSION_ENABLED,
    LiveTradingLockedError,
    assert_live_locked,
)


def test_code_lock_is_immutable_and_accepts_only_locked_state() -> None:
    assert LIVE_TRADING is False
    assert ORDER_SUBMISSION_ENABLED is False
    assert LIVE_ADAPTERS == ()
    assert_live_locked()


@pytest.mark.parametrize(
    "arguments",
    [
        {"config_live": True},
        {"environment_live": True},
        {"order_submission_enabled": True},
        {"registered_live_adapters": ["private_exchange"]},
    ],
)
def test_every_live_request_fails_closed(arguments: dict[str, object]) -> None:
    with pytest.raises(LiveTradingLockedError, match=ERROR_CODE):
        assert_live_locked(**arguments)  # type: ignore[arg-type]


def test_machine_configuration_is_locked() -> None:
    root = Path(__file__).resolve().parents[2]
    runtime = tomllib.loads((root / "configs/base/runtime.toml").read_text(encoding="utf-8"))
    registry = json.loads(
        (root / "configs/exchanges/adapter_registry.json").read_text(encoding="utf-8")
    )

    assert runtime["live_trading"] is False
    assert runtime["order_submission_enabled"] is False
    assert runtime["secret_loading_enabled"] is False
    assert registry["live_trading_locked"] is True
    assert registry["order_submission_enabled"] is False
    assert registry["live_adapters"] == []
