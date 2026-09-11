"""Cross-stream Binance market-data consistency checks."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from aegisquant.data.providers.binance.models import BookTickerRecord, KlineRecord, TradeRecord
from aegisquant.data.providers.binance.orderbook import LocalOrderBook
from aegisquant.domain.base import DomainModel


class ConsistencySeverity(StrEnum):
    WARNING = "WARNING"
    ERROR = "ERROR"


class ConsistencyIssue(DomainModel):
    code: str
    severity: ConsistencySeverity
    message: str


class ConsistencyReport(DomainModel):
    passed: bool
    issues: tuple[ConsistencyIssue, ...]

    @model_validator(mode="after")
    def validate_passed(self) -> ConsistencyReport:
        has_error = any(issue.severity is ConsistencySeverity.ERROR for issue in self.issues)
        if self.passed == has_error:
            raise ValueError("consistency passed flag disagrees with ERROR issues")
        return self


def compare_book_ticker(book: LocalOrderBook, ticker: BookTickerRecord) -> ConsistencyReport:
    issues: list[ConsistencyIssue] = []
    if ticker.product is not book.product or ticker.symbol != book.symbol:
        issues.append(
            ConsistencyIssue(
                code="AQ-DATA-BOOK-TICKER-INSTRUMENT-MISMATCH",
                severity=ConsistencySeverity.ERROR,
                message="book and ticker do not describe the same instrument",
            )
        )
    else:
        bid, ask = book.best_bid_ask()
        if bid != (ticker.best_bid_price, ticker.best_bid_quantity):
            issues.append(
                ConsistencyIssue(
                    code="AQ-DATA-BOOK-BID-MISMATCH",
                    severity=ConsistencySeverity.ERROR,
                    message="book best bid differs from bookTicker",
                )
            )
        if ask != (ticker.best_ask_price, ticker.best_ask_quantity):
            issues.append(
                ConsistencyIssue(
                    code="AQ-DATA-BOOK-ASK-MISMATCH",
                    severity=ConsistencySeverity.ERROR,
                    message="book best ask differs from bookTicker",
                )
            )
    return ConsistencyReport(passed=not issues, issues=tuple(issues))


def compare_kline_trades(
    kline: KlineRecord,
    trades: Sequence[TradeRecord],
    *,
    quantity_tolerance: Decimal = Decimal("0.00000001"),
    quote_tolerance: Decimal = Decimal("0.01"),
) -> ConsistencyReport:
    if quantity_tolerance < 0 or quote_tolerance < 0:
        raise ValueError("consistency tolerances cannot be negative")
    included = tuple(
        trade
        for trade in trades
        if trade.product is kline.product
        and trade.symbol == kline.symbol
        and kline.open_time <= trade.event_time <= kline.close_time
    )
    issues: list[ConsistencyIssue] = []
    if not included:
        issues.append(
            ConsistencyIssue(
                code="AQ-DATA-KLINE-TRADES-MISSING",
                severity=ConsistencySeverity.WARNING,
                message="no complete trade set was supplied for this Kline",
            )
        )
        return ConsistencyReport(passed=True, issues=tuple(issues))
    prices = [trade.price for trade in included]
    base_volume = sum((trade.quantity for trade in included), Decimal("0"))
    quote_volume = sum((trade.quote_quantity for trade in included), Decimal("0"))
    comparisons = (
        (abs(base_volume - kline.base_volume) <= quantity_tolerance, "BASE_VOLUME"),
        (abs(quote_volume - kline.quote_volume) <= quote_tolerance, "QUOTE_VOLUME"),
        (max(prices) == kline.high, "HIGH"),
        (min(prices) == kline.low, "LOW"),
    )
    for matched, field in comparisons:
        if not matched:
            issues.append(
                ConsistencyIssue(
                    code=f"AQ-DATA-KLINE-TRADE-{field}-MISMATCH",
                    severity=ConsistencySeverity.ERROR,
                    message=f"trade-derived {field.lower()} differs from Kline",
                )
            )
    return ConsistencyReport(
        passed=not any(issue.severity is ConsistencySeverity.ERROR for issue in issues),
        issues=tuple(issues),
    )
