"""P00 Live Trading lock with no unlock path and no import side effects."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, NoReturn

ERROR_CODE: Final = "AQ-SECURITY-LIVE-LOCKED"
LIVE_TRADING: Final = False
ORDER_SUBMISSION_ENABLED: Final = False
LIVE_ADAPTERS: Final[tuple[str, ...]] = ()


class LiveTradingLockedError(RuntimeError):
    """Raised whenever configuration attempts to cross the P00 Live boundary."""

    code: Final = ERROR_CODE


def _reject(reason: str) -> NoReturn:
    raise LiveTradingLockedError(f"{ERROR_CODE}: {reason}")


def assert_live_locked(
    *,
    config_live: bool = False,
    environment_live: bool = False,
    order_submission_enabled: bool = False,
    registered_live_adapters: Iterable[str] = (),
) -> None:
    """Validate all lock inputs and fail closed on any Live capability request."""
    adapters = tuple(registered_live_adapters)
    if LIVE_TRADING or config_live or environment_live:
        _reject("Live Trading must remain disabled during P00")
    if ORDER_SUBMISSION_ENABLED or order_submission_enabled:
        _reject("order submission must remain disabled during P00")
    if LIVE_ADAPTERS or adapters:
        _reject("the Live adapter registry must remain empty during P00")
