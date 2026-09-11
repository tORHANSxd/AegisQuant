"""Fail-closed Binance public REST and WebSocket endpoint contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from urllib.parse import urlsplit

from aegisquant.data.hashing import canonical_sha256

SYMBOL_PATTERN: Final = re.compile(r"^[A-Z0-9]{2,30}$")
INTERVAL_PATTERN: Final = re.compile(r"^(1s|[1-9][0-9]*[mhdwM])$")
FORBIDDEN_PARAMETER_NAMES: Final = frozenset(
    {"apikey", "api_key", "signature", "recvwindow", "listenkey", "secret", "cookie"}
)


class Product(StrEnum):
    SPOT = "SPOT"
    USD_M = "USD_M"


class RestEndpoint(StrEnum):
    SPOT_TIME = "spot_time"
    SPOT_EXCHANGE_INFO = "spot_exchange_info"
    SPOT_DEPTH = "spot_depth"
    SPOT_TRADES = "spot_trades"
    SPOT_AGG_TRADES = "spot_agg_trades"
    SPOT_KLINES = "spot_klines"
    SPOT_BOOK_TICKER = "spot_book_ticker"
    USDM_TIME = "usdm_time"
    USDM_EXCHANGE_INFO = "usdm_exchange_info"
    USDM_DEPTH = "usdm_depth"
    USDM_TRADES = "usdm_trades"
    USDM_AGG_TRADES = "usdm_agg_trades"
    USDM_KLINES = "usdm_klines"
    USDM_MARK_KLINES = "usdm_mark_klines"
    USDM_INDEX_KLINES = "usdm_index_klines"
    USDM_MARK_INDEX = "usdm_mark_index"
    USDM_FUNDING = "usdm_funding"
    USDM_OPEN_INTEREST = "usdm_open_interest"
    USDM_OPEN_INTEREST_HISTORY = "usdm_open_interest_history"
    USDM_BOOK_TICKER = "usdm_book_ticker"


class StreamKind(StrEnum):
    TRADE = "trade"
    AGG_TRADE = "agg_trade"
    KLINE = "kline"
    BOOK_TICKER = "book_ticker"
    DEPTH = "depth"
    MARK_PRICE = "mark_price"


@dataclass(frozen=True, slots=True)
class RestContract:
    endpoint: RestEndpoint
    product: Product
    base_url: str
    path: str
    allowed_parameters: frozenset[str]
    required_parameters: frozenset[str] = frozenset()
    maximum_limit: int | None = None

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.path}"


SPOT_BASE: Final = "https://data-api.binance.vision"
USDM_BASE: Final = "https://fapi.binance.com"
PUBLIC_ARCHIVE_BASE: Final = "https://data.binance.vision"
SPOT_WS_BASE: Final = "wss://data-stream.binance.vision"
USDM_PUBLIC_WS_BASE: Final = "wss://fstream.binance.com/public"
USDM_MARKET_WS_BASE: Final = "wss://fstream.binance.com/market"

_SYMBOL: Final = frozenset({"symbol"})
_TIME_PAGE: Final = frozenset({"symbol", "interval", "startTime", "endTime", "limit"})

REST_CONTRACTS: Final = MappingProxyType(
    {
        RestEndpoint.SPOT_TIME: RestContract(
            RestEndpoint.SPOT_TIME, Product.SPOT, SPOT_BASE, "/api/v3/time", frozenset()
        ),
        RestEndpoint.SPOT_EXCHANGE_INFO: RestContract(
            RestEndpoint.SPOT_EXCHANGE_INFO,
            Product.SPOT,
            SPOT_BASE,
            "/api/v3/exchangeInfo",
            frozenset({"symbol", "symbols", "permissions", "showPermissionSets", "symbolStatus"}),
        ),
        RestEndpoint.SPOT_DEPTH: RestContract(
            RestEndpoint.SPOT_DEPTH,
            Product.SPOT,
            SPOT_BASE,
            "/api/v3/depth",
            frozenset({"symbol", "limit"}),
            _SYMBOL,
            5000,
        ),
        RestEndpoint.SPOT_TRADES: RestContract(
            RestEndpoint.SPOT_TRADES,
            Product.SPOT,
            SPOT_BASE,
            "/api/v3/trades",
            frozenset({"symbol", "limit"}),
            _SYMBOL,
            1000,
        ),
        RestEndpoint.SPOT_AGG_TRADES: RestContract(
            RestEndpoint.SPOT_AGG_TRADES,
            Product.SPOT,
            SPOT_BASE,
            "/api/v3/aggTrades",
            frozenset({"symbol", "fromId", "startTime", "endTime", "limit"}),
            _SYMBOL,
            1000,
        ),
        RestEndpoint.SPOT_KLINES: RestContract(
            RestEndpoint.SPOT_KLINES,
            Product.SPOT,
            SPOT_BASE,
            "/api/v3/klines",
            _TIME_PAGE | frozenset({"timeZone"}),
            frozenset({"symbol", "interval"}),
            1000,
        ),
        RestEndpoint.SPOT_BOOK_TICKER: RestContract(
            RestEndpoint.SPOT_BOOK_TICKER,
            Product.SPOT,
            SPOT_BASE,
            "/api/v3/ticker/bookTicker",
            frozenset({"symbol", "symbols"}),
        ),
        RestEndpoint.USDM_TIME: RestContract(
            RestEndpoint.USDM_TIME, Product.USD_M, USDM_BASE, "/fapi/v1/time", frozenset()
        ),
        RestEndpoint.USDM_EXCHANGE_INFO: RestContract(
            RestEndpoint.USDM_EXCHANGE_INFO,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/exchangeInfo",
            frozenset(),
        ),
        RestEndpoint.USDM_DEPTH: RestContract(
            RestEndpoint.USDM_DEPTH,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/depth",
            frozenset({"symbol", "limit"}),
            _SYMBOL,
            1000,
        ),
        RestEndpoint.USDM_TRADES: RestContract(
            RestEndpoint.USDM_TRADES,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/trades",
            frozenset({"symbol", "limit"}),
            _SYMBOL,
            1000,
        ),
        RestEndpoint.USDM_AGG_TRADES: RestContract(
            RestEndpoint.USDM_AGG_TRADES,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/aggTrades",
            frozenset({"symbol", "fromId", "startTime", "endTime", "limit"}),
            _SYMBOL,
            1000,
        ),
        RestEndpoint.USDM_KLINES: RestContract(
            RestEndpoint.USDM_KLINES,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/klines",
            _TIME_PAGE,
            frozenset({"symbol", "interval"}),
            1500,
        ),
        RestEndpoint.USDM_MARK_KLINES: RestContract(
            RestEndpoint.USDM_MARK_KLINES,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/markPriceKlines",
            _TIME_PAGE,
            frozenset({"symbol", "interval"}),
            1500,
        ),
        RestEndpoint.USDM_INDEX_KLINES: RestContract(
            RestEndpoint.USDM_INDEX_KLINES,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/indexPriceKlines",
            frozenset({"pair", "interval", "startTime", "endTime", "limit"}),
            frozenset({"pair", "interval"}),
            1500,
        ),
        RestEndpoint.USDM_MARK_INDEX: RestContract(
            RestEndpoint.USDM_MARK_INDEX,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/premiumIndex",
            _SYMBOL,
        ),
        RestEndpoint.USDM_FUNDING: RestContract(
            RestEndpoint.USDM_FUNDING,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/fundingRate",
            frozenset({"symbol", "startTime", "endTime", "limit"}),
            frozenset(),
            1000,
        ),
        RestEndpoint.USDM_OPEN_INTEREST: RestContract(
            RestEndpoint.USDM_OPEN_INTEREST,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/openInterest",
            _SYMBOL,
            _SYMBOL,
        ),
        RestEndpoint.USDM_OPEN_INTEREST_HISTORY: RestContract(
            RestEndpoint.USDM_OPEN_INTEREST_HISTORY,
            Product.USD_M,
            USDM_BASE,
            "/futures/data/openInterestHist",
            frozenset({"symbol", "period", "startTime", "endTime", "limit"}),
            frozenset({"symbol", "period"}),
            500,
        ),
        RestEndpoint.USDM_BOOK_TICKER: RestContract(
            RestEndpoint.USDM_BOOK_TICKER,
            Product.USD_M,
            USDM_BASE,
            "/fapi/v1/ticker/bookTicker",
            _SYMBOL,
        ),
    }
)


def _normalize_parameters(parameters: dict[str, str | int] | None) -> dict[str, str | int]:
    normalized = dict(parameters or {})
    folded = {key.casefold() for key in normalized}
    forbidden = sorted(folded & FORBIDDEN_PARAMETER_NAMES)
    if forbidden:
        raise ValueError(f"AQ-BINANCE-PRIVATE-PARAMETER: {forbidden}")
    symbol = normalized.get("symbol")
    if symbol is not None and (
        not isinstance(symbol, str) or SYMBOL_PATTERN.fullmatch(symbol) is None
    ):
        raise ValueError("symbol must be an uppercase Binance symbol")
    return normalized


def build_rest_request(
    endpoint: RestEndpoint, parameters: dict[str, str | int] | None = None
) -> tuple[str, dict[str, str | int], str]:
    """Build an allow-listed unsigned public request and its deterministic identity hash."""
    contract = REST_CONTRACTS[endpoint]
    normalized = _normalize_parameters(parameters)
    unknown = sorted(set(normalized) - contract.allowed_parameters)
    missing = sorted(contract.required_parameters - set(normalized))
    if unknown or missing:
        raise ValueError(f"AQ-BINANCE-PARAMETERS: unknown={unknown}, missing={missing}")
    limit = normalized.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if contract.maximum_limit is not None and limit > contract.maximum_limit:
            raise ValueError(f"limit exceeds {endpoint.value} maximum")
    identity = canonical_sha256(
        {"method": "GET", "url": contract.url, "parameters": normalized, "auth": False}
    )
    return contract.url, normalized, identity


def build_stream_name(
    *, product: Product, kind: StreamKind, symbol: str, interval: str | None = None
) -> str:
    if SYMBOL_PATTERN.fullmatch(symbol) is None:
        raise ValueError("symbol must be an uppercase Binance symbol")
    lower_symbol = symbol.lower()
    if kind is StreamKind.KLINE:
        if interval is None or INTERVAL_PATTERN.fullmatch(interval) is None:
            raise ValueError("a supported Kline interval is required")
        suffix = f"@kline_{interval}"
    elif kind is StreamKind.DEPTH:
        suffix = "@depth@1000ms" if product is Product.SPOT else "@depth@500ms"
    elif kind is StreamKind.MARK_PRICE:
        if product is not Product.USD_M:
            raise ValueError("mark price stream exists only for USD-M")
        suffix = "@markPrice@1s"
    else:
        suffix = {
            StreamKind.TRADE: "@trade",
            StreamKind.AGG_TRADE: "@aggTrade",
            StreamKind.BOOK_TICKER: "@bookTicker",
        }[kind]
    if product is Product.USD_M and kind is StreamKind.TRADE:
        raise ValueError("USD-M public stream exposes aggTrade rather than raw trade")
    return f"{lower_symbol}{suffix}"


def build_ws_url(
    *, product: Product, kind: StreamKind, symbol: str, interval: str | None = None
) -> str:
    stream = build_stream_name(product=product, kind=kind, symbol=symbol, interval=interval)
    if product is Product.SPOT:
        base = SPOT_WS_BASE
    elif kind in {StreamKind.DEPTH, StreamKind.BOOK_TICKER}:
        base = USDM_PUBLIC_WS_BASE
    else:
        base = USDM_MARKET_WS_BASE
    url = f"{base}/ws/{stream}"
    assert_public_url(url, websocket=True)
    return url


def assert_public_url(url: str, *, websocket: bool = False) -> None:
    """Reject credentials, private routes, redirects to unknown hosts, and non-TLS URLs."""
    parsed = urlsplit(url)
    allowed_hosts = (
        {"data-stream.binance.vision", "fstream.binance.com"}
        if websocket
        else {"data-api.binance.vision", "fapi.binance.com", "data.binance.vision"}
    )
    expected_scheme = "wss" if websocket else "https"
    if (
        parsed.scheme != expected_scheme
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("AQ-BINANCE-PUBLIC-URL-DENIED")
    if parsed.port not in {None, 443, 9443}:
        raise ValueError("AQ-BINANCE-PUBLIC-URL-DENIED")
    folded_path = parsed.path.casefold()
    if any(token in folded_path for token in ("/private", "/order", "/account", "listenkey")):
        raise ValueError("AQ-BINANCE-PRIVATE-ROUTE")


def assert_public_archive_url(url: str) -> None:
    assert_public_url(url)
    parsed = urlsplit(url)
    if parsed.hostname != "data.binance.vision" or not parsed.path.startswith("/data/"):
        raise ValueError("AQ-BINANCE-PUBLIC-ARCHIVE-DENIED")
    if not parsed.path.endswith((".zip", ".CHECKSUM")):
        raise ValueError("AQ-BINANCE-PUBLIC-ARCHIVE-DENIED")
