"""Fail-closed bootstrap contracts."""

from aegisquant.bootstrap.live_lock import (
    ERROR_CODE,
    LIVE_ADAPTERS,
    LIVE_TRADING,
    ORDER_SUBMISSION_ENABLED,
    LiveTradingLockedError,
    assert_live_locked,
)

__all__ = [
    "ERROR_CODE",
    "LIVE_ADAPTERS",
    "LIVE_TRADING",
    "ORDER_SUBMISSION_ENABLED",
    "LiveTradingLockedError",
    "assert_live_locked",
]
