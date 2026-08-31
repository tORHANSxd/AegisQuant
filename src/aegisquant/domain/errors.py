"""Stable error codes and machine-actionable recovery classifications."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ErrorDisposition(StrEnum):
    RETRY = "RETRY"
    NO_RETRY = "NO_RETRY"
    RECONCILE = "RECONCILE"
    MANUAL = "MANUAL"
    DEGRADE = "DEGRADE"
    HALT = "HALT"


ERROR_PREFIXES: Final = frozenset(
    {
        "AQ-DATA",
        "AQ-TIME",
        "AQ-MODEL",
        "AQ-STRATEGY",
        "AQ-RISK",
        "AQ-ORDER",
        "AQ-LEDGER",
        "AQ-RECON",
        "AQ-PROVIDER",
        "AQ-SECURITY",
        "AQ-WEB",
    }
)


class DomainError(RuntimeError):
    """Error with stable code independent of display text."""

    def __init__(self, code: str, disposition: ErrorDisposition, message: str) -> None:
        prefix = "-".join(code.split("-")[:2])
        if prefix not in ERROR_PREFIXES or code.count("-") < 2:
            raise ValueError(f"invalid AegisQuant error code: {code}")
        self.code = code
        self.disposition = disposition
        super().__init__(f"{code}: {message}")
