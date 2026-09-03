# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Reproducible public-market walk-forward validation with fail-closed evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Final, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, safe_path_segment
from aegisquant.data.providers.binance.contracts import RestEndpoint
from aegisquant.data.providers.binance.models import RawResponseEnvelope
from aegisquant.research.models import (
    BaselineDataset,
    BaselineModelKind,
    BaselineModelSpec,
    fit_predict_baseline,
)
from aegisquant.research.validation.splits import (
    SampleSpan,
    TemporalSplitPolicy,
    WalkForwardMode,
    walk_forward_splits,
)
from aegisquant.research.validation.statistics import (
    benjamini_hochberg,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

INTERVAL: Final = "1h"
INTERVAL_MILLISECONDS: Final = 3_600_000
PERIODS_PER_YEAR: Final = 24 * 365
FEATURE_NAMES: Final = (
    "log_return_1h",
    "momentum_6h",
    "momentum_24h",
    "momentum_168h",
    "realized_volatility_24h",
    "realized_volatility_168h",
    "log_quote_volume_z_168h",
    "range_fraction",
    "close_to_open_return",
    "taker_buy_quote_ratio",
    "trade_count_z_168h",
)
CALIBRATION_THRESHOLDS: Final = (0.50, 0.52, 0.54, 0.56, 0.58, 1.0)


class PublicJsonClient(Protocol):
    """Minimum public REST surface used by the downloader."""

    def get_json(
        self, endpoint: RestEndpoint, parameters: dict[str, str | int] | None = None
    ) -> tuple[RawResponseEnvelope, object]: ...


@dataclass(frozen=True, slots=True)
class RealBacktestConfig:
    """Precommitted development-OOS experiment configuration."""

    symbols: tuple[str, ...]
    start_at: datetime
    end_at_exclusive: datetime
    train_hours: int = 8_760
    validation_hours: int = 720
    calibration_hours: int = 720
    test_hours: int = 2_160
    purge_hours: int = 2
    embargo_hours: int = 24
    assumed_fee_bps_per_turnover: float = 10.0
    assumed_execution_bps_per_turnover: float = 3.0
    bootstrap_repetitions: int = 1_000
    bootstrap_block_hours: int = 24
    seed: int = 20260903

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be non-empty and unique")
        for symbol in self.symbols:
            safe_path_segment(symbol, field_name="symbol")
            if symbol != symbol.upper():
                raise ValueError("Binance symbols must be uppercase")
        for name, value in (
            ("start_at", self.start_at),
            ("end_at_exclusive", self.end_at_exclusive),
        ):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise ValueError(f"{name} must be UTC aware")
            if any((value.minute, value.second, value.microsecond)):
                raise ValueError(f"{name} must be aligned to an hour")
        if self.start_at >= self.end_at_exclusive:
            raise ValueError("backtest time range is empty")
        if self.train_hours < 4 or any(
            value < 1
            for value in (
                self.validation_hours,
                self.calibration_hours,
                self.test_hours,
                self.bootstrap_block_hours,
            )
        ):
            raise ValueError("positive backtest window and bootstrap sizes are required")
        if self.bootstrap_repetitions < 20:
            raise ValueError("at least twenty bootstrap repetitions are required")
        if self.purge_hours < 2 or self.embargo_hours < 1:
            raise ValueError("two-label-bar purge and a positive embargo are mandatory")
        cost_values = (
            self.assumed_fee_bps_per_turnover,
            self.assumed_execution_bps_per_turnover,
        )
        if any(not math.isfinite(value) for value in cost_values) or min(cost_values) < 0:
            raise ValueError("cost assumptions cannot be negative")
        if self.seed < 0:
            raise ValueError("seed cannot be negative")

    @property
    def start_ms(self) -> int:
        return int(self.start_at.timestamp() * 1_000)

    @property
    def end_ms_exclusive(self) -> int:
        return int(self.end_at_exclusive.timestamp() * 1_000)

    @property
    def cost_per_turnover(self) -> float:
        return (
            self.assumed_fee_bps_per_turnover + self.assumed_execution_bps_per_turnover
        ) / 10_000

    def as_payload(self) -> dict[str, object]:
        return {
            "symbols": list(self.symbols),
            "source": "BINANCE_SPOT_PUBLIC_REST",
            "interval": INTERVAL,
            "start_at": _iso(self.start_at),
            "end_at_exclusive": _iso(self.end_at_exclusive),
            "forecast_horizon": "one-hour open-to-open return",
            "execution_delay": "decision after bar t close; enter at bar t+1 open",
            "train_hours": self.train_hours,
            "validation_hours": self.validation_hours,
            "calibration_hours": self.calibration_hours,
            "test_hours": self.test_hours,
            "purge_hours": self.purge_hours,
            "embargo_hours": self.embargo_hours,
            "step_hours": self.test_hours,
            "assumed_fee_bps_per_turnover": self.assumed_fee_bps_per_turnover,
            "assumed_execution_bps_per_turnover": self.assumed_execution_bps_per_turnover,
            "bootstrap_repetitions": self.bootstrap_repetitions,
            "bootstrap_block_hours": self.bootstrap_block_hours,
            "seed": self.seed,
            "final_holdout_opened": False,
        }


@dataclass(frozen=True, slots=True)
class Kline:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    base_volume: float
    close_time_ms: int
    quote_volume: float
    trade_count: int
    taker_buy_base_volume: float
    taker_buy_quote_volume: float

    def csv_row(self) -> tuple[object, ...]:
        return (
            self.open_time_ms,
            self.open,
            self.high,
            self.low,
            self.close,
            self.base_volume,
            self.close_time_ms,
            self.quote_volume,
            self.trade_count,
            self.taker_buy_base_volume,
            self.taker_buy_quote_volume,
        )


@dataclass(frozen=True, slots=True)
class DownloadedKlines:
    symbol: str
    rows: tuple[Kline, ...]
    cache_directory: Path
    source_manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class PreparedSamples:
    symbol: str
    sample_ids: tuple[str, ...]
    timestamps: tuple[datetime, ...]
    label_start_times: tuple[datetime, ...]
    label_end_times: tuple[datetime, ...]
    features: FloatArray
    targets: FloatArray
    realized_returns: FloatArray
    entry_quote_volume: FloatArray
    regimes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateDefinition:
    candidate_id: str
    feature_indices: tuple[int, ...] | None
    fixed_position: float | None = None


@dataclass(frozen=True, slots=True)
class ReturnPath:
    gross: FloatArray
    costs: FloatArray
    net: FloatArray
    turnover: FloatArray


@dataclass(frozen=True, slots=True)
class SymbolRun:
    symbol: str
    samples: PreparedSamples
    oos_indices: IntArray
    fold_ids: tuple[str, ...]
    selected_candidates: tuple[str, ...]
    selected_thresholds: FloatArray
    selected_probabilities: FloatArray
    selected_positions: FloatArray
    candidate_probabilities: Mapping[str, FloatArray]
    candidate_positions: Mapping[str, FloatArray]
    fold_ledger: tuple[dict[str, object], ...]


CANDIDATES: Final = (
    CandidateDefinition("always_flat", None, 0.0),
    CandidateDefinition("always_long", None, 1.0),
    CandidateDefinition("logistic_core", (0, 1, 2, 4, 7, 8, 9)),
    CandidateDefinition("logistic_slow", (2, 3, 4, 5, 6, 10)),
    CandidateDefinition("logistic_full", tuple(range(len(FEATURE_NAMES)))),
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decode_json(raw: bytes) -> object:
    def reject_constant(value: str) -> object:
        raise ValueError(f"non-standard JSON constant is forbidden: {value}")

    return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)


def _as_object(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return cast("dict[str, object]", value)


def _as_list(value: object, *, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return cast("list[object]", value)


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def _parse_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{field} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _report_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"report field {field} is not numeric")
    output = float(value)
    if not math.isfinite(output):
        raise ValueError(f"report field {field} must be finite")
    return output


def _report_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"report field {field} is not an integer")
    return value


def _parse_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def parse_kline_payload(payload: object) -> tuple[Kline, ...]:
    """Validate Binance's twelve-field kline wire format without coercing timestamps."""

    output: list[Kline] = []
    for index, raw_row in enumerate(_as_list(payload, name="kline payload")):
        row = _as_list(raw_row, name=f"kline[{index}]")
        if len(row) != 12:
            raise ValueError("each Binance kline must have exactly twelve fields")
        item = Kline(
            open_time_ms=_parse_integer(row[0], field="open_time"),
            open=_parse_number(row[1], field="open"),
            high=_parse_number(row[2], field="high"),
            low=_parse_number(row[3], field="low"),
            close=_parse_number(row[4], field="close"),
            base_volume=_parse_number(row[5], field="base_volume"),
            close_time_ms=_parse_integer(row[6], field="close_time"),
            quote_volume=_parse_number(row[7], field="quote_volume"),
            trade_count=_parse_integer(row[8], field="trade_count"),
            taker_buy_base_volume=_parse_number(row[9], field="taker_buy_base_volume"),
            taker_buy_quote_volume=_parse_number(row[10], field="taker_buy_quote_volume"),
        )
        if not (
            item.open_time_ms < item.close_time_ms <= item.open_time_ms + INTERVAL_MILLISECONDS - 1
        ):
            raise ValueError("kline close timestamp must remain inside its one-hour bucket")
        if min(item.open, item.high, item.low, item.close) <= 0:
            raise ValueError("kline prices must be positive")
        if item.high < max(item.open, item.close) or item.low > min(item.open, item.close):
            raise ValueError("kline OHLC bounds are invalid")
        if item.low > item.high:
            raise ValueError("kline low exceeds high")
        if (
            min(
                item.base_volume,
                item.quote_volume,
                item.taker_buy_base_volume,
                item.taker_buy_quote_volume,
                item.trade_count,
            )
            < 0
        ):
            raise ValueError("kline volume and trade counts cannot be negative")
        output.append(item)
    return tuple(output)


def _range_diagnostics(
    rows: Sequence[Kline], *, start_ms: int, end_ms_exclusive: int
) -> dict[str, object]:
    expected = (end_ms_exclusive - start_ms) // INTERVAL_MILLISECONDS
    if end_ms_exclusive - start_ms != expected * INTERVAL_MILLISECONDS:
        raise ValueError("download range must contain whole hours")
    if not rows or rows[0].open_time_ms != start_ms:
        raise ValueError("download range does not contain the requested first bar")
    if rows[-1].open_time_ms != end_ms_exclusive - INTERVAL_MILLISECONDS:
        raise ValueError("download range does not contain the requested final bar")
    gaps = 0
    missing = 0
    previous = start_ms - INTERVAL_MILLISECONDS
    for index, row in enumerate(rows):
        distance = row.open_time_ms - previous
        if distance < INTERVAL_MILLISECONDS or distance % INTERVAL_MILLISECONDS:
            raise ValueError(f"kline timestamp order or grid alignment failed at row {index}")
        if distance > INTERVAL_MILLISECONDS:
            gaps += 1
            missing += distance // INTERVAL_MILLISECONDS - 1
        previous = row.open_time_ms
    if missing != expected - len(rows):
        raise ValueError("kline missing-hour accounting does not conserve")
    return {
        "expected_hour_count": expected,
        "row_count": len(rows),
        "complete_hourly_grid": missing == 0,
        "gap_count": gaps,
        "missing_hour_count": missing,
        "early_close_count": sum(
            row.close_time_ms != row.open_time_ms + INTERVAL_MILLISECONDS - 1 for row in rows
        ),
    }


def _cache_request(config: RealBacktestConfig, symbol: str) -> dict[str, object]:
    return {
        "provider": "binance_public",
        "endpoint": RestEndpoint.SPOT_KLINES.value,
        "symbol": symbol,
        "interval": INTERVAL,
        "start_ms": config.start_ms,
        "end_ms_exclusive": config.end_ms_exclusive,
        "limit": 1_000,
    }


def _load_cached_klines(
    *, config: RealBacktestConfig, symbol: str, cache_directory: Path, manifest_path: Path
) -> DownloadedKlines:
    manifest = _as_object(_decode_json(manifest_path.read_bytes()), name="cache manifest")
    if manifest.get("schema_version") != "aegisquant-public-kline-cache-v1":
        raise ValueError("cached kline manifest schema is invalid")
    if manifest.get("request") != _cache_request(config, symbol):
        raise ValueError("cached kline request does not match the current experiment")
    pages = _as_list(manifest.get("pages"), name="cache pages")
    rows: list[Kline] = []
    committed_hashes: list[dict[str, str]] = []
    for page_value in pages:
        page = _as_object(page_value, name="cache page")
        filename = page.get("file")
        content = _as_object(page.get("content"), name="cache page content")
        expected_hash = content.get("sha256")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("cache page filename is unsafe")
        if not isinstance(expected_hash, str):
            raise ValueError("cache page hash is absent")
        page_path = cache_directory / filename
        raw = page_path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"cached page hash mismatch: {filename}")
        committed_hashes.append({"sha256": actual_hash})
        rows.extend(parse_kline_payload(_decode_json(raw)))
    diagnostics = _range_diagnostics(
        rows, start_ms=config.start_ms, end_ms_exclusive=config.end_ms_exclusive
    )
    dataset = _as_object(manifest.get("dataset"), name="cache dataset")
    if dataset.get("sha256") != canonical_sha256(committed_hashes):
        raise ValueError("cached dataset hash chain is invalid")
    for key, expected in diagnostics.items():
        if dataset.get(key) != expected:
            raise ValueError(f"cached dataset diagnostic is invalid: {key}")
    return DownloadedKlines(symbol, tuple(rows), cache_directory, manifest)


def load_or_download_spot_klines(
    *,
    config: RealBacktestConfig,
    symbol: str,
    raw_root: Path,
    client: PublicJsonClient,
) -> DownloadedKlines:
    """Load a hash-verified cache or fetch every exact public REST response page."""

    safe_path_segment(symbol, field_name="symbol")
    range_key = f"{config.start_ms}_{config.end_ms_exclusive}"
    cache_directory = raw_root / "binance" / "spot" / "klines" / symbol / INTERVAL / range_key
    manifest_path = cache_directory / "manifest.json"
    if manifest_path.is_file():
        return _load_cached_klines(
            config=config,
            symbol=symbol,
            cache_directory=cache_directory,
            manifest_path=manifest_path,
        )

    cache_directory.mkdir(parents=True, exist_ok=True)
    cursor = config.start_ms
    page_index = 0
    rows: list[Kline] = []
    pages: list[dict[str, object]] = []
    while cursor < config.end_ms_exclusive:
        envelope, decoded = client.get_json(
            RestEndpoint.SPOT_KLINES,
            {
                "symbol": symbol,
                "interval": INTERVAL,
                "startTime": cursor,
                "endTime": config.end_ms_exclusive - 1,
                "limit": 1_000,
            },
        )
        if envelope.status_code != 200:
            raise ValueError("public market response was not successful")
        if hashlib.sha256(envelope.content).hexdigest() != envelope.content_sha256:
            raise ValueError("public market response content hash is invalid")
        page_rows = parse_kline_payload(decoded)
        if not page_rows:
            raise ValueError("public market response ended before the requested range")
        first_distance = page_rows[0].open_time_ms - cursor
        if first_distance < 0 or first_distance % INTERVAL_MILLISECONDS:
            raise ValueError("public market page did not honor an aligned forward cursor")
        if page_rows[-1].open_time_ms >= config.end_ms_exclusive:
            raise ValueError("public market response exceeded the requested range")
        for left, right in pairwise(page_rows):
            distance = right.open_time_ms - left.open_time_ms
            if distance < INTERVAL_MILLISECONDS or distance % INTERVAL_MILLISECONDS:
                raise ValueError("public market response timestamps are not a strict hourly grid")
        filename = f"page-{page_index:04d}.json"
        _atomic_write(cache_directory / filename, envelope.content)
        pages.append(
            {
                "file": filename,
                "request_url": envelope.request_url,
                "request": {"sha256": envelope.request_hash},
                "content": {"sha256": envelope.content_sha256},
                "received_at": _iso(envelope.received_at),
                "elapsed_ms": envelope.elapsed_ms,
                "row_count": len(page_rows),
                "first_open_time_ms": page_rows[0].open_time_ms,
                "last_open_time_ms": page_rows[-1].open_time_ms,
            }
        )
        rows.extend(page_rows)
        cursor = page_rows[-1].open_time_ms + INTERVAL_MILLISECONDS
        page_index += 1
    diagnostics = _range_diagnostics(
        rows, start_ms=config.start_ms, end_ms_exclusive=config.end_ms_exclusive
    )
    page_hashes = [
        {"sha256": cast("dict[str, object]", page["content"])["sha256"]} for page in pages
    ]
    manifest: dict[str, object] = {
        "schema_version": "aegisquant-public-kline-cache-v1",
        "request": _cache_request(config, symbol),
        "source": {
            "provider": "Binance",
            "base_url": "https://data-api.binance.vision",
            "official_documentation": (
                "https://developers.binance.com/en/docs/catalog/"
                "core-trading-spot-trading/api/rest-api/market"
            ),
            "authentication_used": False,
        },
        "dataset": {
            "sha256": canonical_sha256(page_hashes),
            "page_count": len(pages),
            "first_open_time_ms": rows[0].open_time_ms,
            "last_open_time_ms": rows[-1].open_time_ms,
            **diagnostics,
        },
        "pages": pages,
    }
    _atomic_write(manifest_path, canonical_json_bytes(manifest))
    return DownloadedKlines(symbol, tuple(rows), cache_directory, manifest)


def write_bronze_csv(download: DownloadedKlines, path: Path) -> str:
    """Write a deterministic, typed bronze representation and return its SHA-256."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            (
                "open_time_ms",
                "open",
                "high",
                "low",
                "close",
                "base_volume",
                "close_time_ms",
                "quote_volume",
                "trade_count",
                "taker_buy_base_volume",
                "taker_buy_quote_volume",
            )
        )
        writer.writerows(row.csv_row() for row in download.rows)
    temporary.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rolling_mean_std(values: FloatArray, window: int) -> tuple[FloatArray, FloatArray]:
    if window < 2:
        raise ValueError("rolling window must be at least two")
    mean = np.full(values.shape, np.nan, dtype=np.float64)
    standard_deviation = np.full(values.shape, np.nan, dtype=np.float64)
    finite = np.isfinite(values)
    safe_values = np.where(finite, values, 0.0)
    cumulative = np.concatenate((np.zeros(1), np.cumsum(safe_values)))
    cumulative_sq = np.concatenate((np.zeros(1), np.cumsum(safe_values**2)))
    counts = np.concatenate((np.zeros(1), np.cumsum(finite.astype(np.float64))))
    sums = cumulative[window:] - cumulative[:-window]
    sums_sq = cumulative_sq[window:] - cumulative_sq[:-window]
    rolling_counts = counts[window:] - counts[:-window]
    valid = rolling_counts == window
    local_mean = np.divide(sums, rolling_counts, out=np.zeros_like(sums), where=valid)
    variance = np.divide(sums_sq, rolling_counts, out=np.zeros_like(sums_sq), where=valid)
    variance = np.maximum(variance - local_mean**2, 0.0)
    positions = np.arange(window - 1, len(values))
    mean[positions[valid]] = local_mean[valid]
    standard_deviation[positions[valid]] = np.sqrt(variance[valid])
    return mean, standard_deviation


def prepare_samples(download: DownloadedKlines) -> PreparedSamples:
    """Build trailing-only features and a two-open future label window."""

    rows = download.rows
    if len(rows) < 1_000:
        raise ValueError("real backtest requires at least one thousand complete bars")
    open_time = np.asarray([row.open_time_ms for row in rows], dtype=np.int64)
    close_time = np.asarray([row.close_time_ms for row in rows], dtype=np.int64)
    opens = np.asarray([row.open for row in rows], dtype=np.float64)
    highs = np.asarray([row.high for row in rows], dtype=np.float64)
    lows = np.asarray([row.low for row in rows], dtype=np.float64)
    closes = np.asarray([row.close for row in rows], dtype=np.float64)
    quote_volume = np.asarray([row.quote_volume for row in rows], dtype=np.float64)
    taker_quote = np.asarray([row.taker_buy_quote_volume for row in rows], dtype=np.float64)
    trade_count = np.asarray([row.trade_count for row in rows], dtype=np.float64)

    log_close = np.log(closes)
    log_return = np.full(closes.shape, np.nan, dtype=np.float64)
    log_return[1:] = np.diff(log_close)
    momentum_6 = np.full(closes.shape, np.nan, dtype=np.float64)
    momentum_24 = np.full(closes.shape, np.nan, dtype=np.float64)
    momentum_168 = np.full(closes.shape, np.nan, dtype=np.float64)
    momentum_6[6:] = log_close[6:] - log_close[:-6]
    momentum_24[24:] = log_close[24:] - log_close[:-24]
    momentum_168[168:] = log_close[168:] - log_close[:-168]
    _, volatility_24 = _rolling_mean_std(log_return, 24)
    _, volatility_168 = _rolling_mean_std(log_return, 168)
    log_quote_volume = np.log1p(quote_volume)
    volume_mean, volume_std = _rolling_mean_std(log_quote_volume, 168)
    volume_z = np.divide(
        log_quote_volume - volume_mean,
        volume_std,
        out=np.zeros_like(log_quote_volume),
        where=volume_std > 0,
    )
    trade_mean, trade_std = _rolling_mean_std(np.log1p(trade_count), 168)
    trade_z = np.divide(
        np.log1p(trade_count) - trade_mean,
        trade_std,
        out=np.zeros_like(trade_count),
        where=trade_std > 0,
    )
    range_fraction = (highs - lows) / opens
    close_to_open = closes / opens - 1.0
    taker_ratio = np.divide(
        taker_quote,
        quote_volume,
        out=np.full_like(taker_quote, 0.5),
        where=quote_volume > 0,
    )
    all_features = np.column_stack(
        (
            log_return,
            momentum_6,
            momentum_24,
            momentum_168,
            volatility_24,
            volatility_168,
            volume_z,
            range_fraction,
            close_to_open,
            taker_ratio,
            trade_z,
        )
    ).astype(np.float64)
    eligible = np.arange(168, len(rows) - 2, dtype=np.int64)
    continuous_lookback = (
        open_time[eligible] - open_time[eligible - 168] == 168 * INTERVAL_MILLISECONDS
    )
    continuous_label = (open_time[eligible + 1] - open_time[eligible] == INTERVAL_MILLISECONDS) & (
        open_time[eligible + 2] - open_time[eligible + 1] == INTERVAL_MILLISECONDS
    )
    selected = eligible[continuous_lookback & continuous_label]
    features = all_features[selected]
    if not np.all(np.isfinite(features)):
        raise ValueError("trailing feature construction produced non-finite values")
    realized = opens[selected + 2] / opens[selected + 1] - 1.0
    targets = np.where(realized > 0, 1.0, -1.0).astype(np.float64)
    timestamps = tuple(
        datetime.fromtimestamp(int(close_time[index]) / 1_000, tz=UTC) for index in selected
    )
    label_start = tuple(
        datetime.fromtimestamp(int(open_time[index + 1]) / 1_000, tz=UTC) for index in selected
    )
    label_end = tuple(
        datetime.fromtimestamp(int(open_time[index + 2]) / 1_000, tz=UTC) for index in selected
    )
    sample_ids = tuple(f"{download.symbol}:{int(open_time[index])}" for index in selected)
    annualized_volatility = volatility_168[selected] * math.sqrt(PERIODS_PER_YEAR)
    regimes = tuple(
        f"{'BULL' if trend > 0 else 'BEAR'}_{'HIGH_VOL' if vol >= 0.8 else 'LOW_VOL'}"
        for trend, vol in zip(momentum_168[selected], annualized_volatility, strict=True)
    )
    return PreparedSamples(
        symbol=download.symbol,
        sample_ids=sample_ids,
        timestamps=timestamps,
        label_start_times=label_start,
        label_end_times=label_end,
        features=features,
        targets=targets,
        realized_returns=realized.astype(np.float64),
        entry_quote_volume=quote_volume[selected + 1].astype(np.float64),
        regimes=regimes,
    )


def _dataset(
    samples: PreparedSamples, indices: IntArray, feature_indices: tuple[int, ...]
) -> BaselineDataset:
    return BaselineDataset(
        sample_ids=tuple(samples.sample_ids[int(index)] for index in indices),
        timestamps=tuple(samples.timestamps[int(index)] for index in indices),
        feature_names=tuple(FEATURE_NAMES[index] for index in feature_indices),
        features=tuple(
            tuple(float(value) for value in samples.features[int(index), feature_indices])
            for index in indices
        ),
        targets=tuple(float(samples.targets[int(index)]) for index in indices),
    )


def _candidate_probabilities(
    *,
    candidate: CandidateDefinition,
    samples: PreparedSamples,
    train_indices: IntArray,
    prediction_indices: IntArray,
    seed: int,
) -> tuple[FloatArray, str | None]:
    if candidate.fixed_position == 0.0:
        return np.full(len(prediction_indices), 0.5, dtype=np.float64), None
    if candidate.fixed_position == 1.0:
        return np.ones(len(prediction_indices), dtype=np.float64), None
    if candidate.feature_indices is None:
        raise ValueError("trainable candidate requires features")
    spec = BaselineModelSpec(
        model_id=candidate.candidate_id,
        kind=BaselineModelKind.LOGISTIC,
        seed=seed,
    )
    prediction = fit_predict_baseline(
        spec=spec,
        train=_dataset(samples, train_indices, candidate.feature_indices),
        test=_dataset(samples, prediction_indices, candidate.feature_indices),
    )
    if prediction.positive_probabilities is None:
        raise ValueError("logistic candidate did not return probabilities")
    return (
        np.asarray([float(value) for value in prediction.positive_probabilities], dtype=np.float64),
        prediction.model_spec_sha256,
    )


def positions_for(
    candidate: CandidateDefinition, probabilities: FloatArray, threshold: float
) -> FloatArray:
    if candidate.fixed_position is not None:
        return np.full(len(probabilities), candidate.fixed_position, dtype=np.float64)
    if threshold >= 1.0:
        return np.zeros(len(probabilities), dtype=np.float64)
    return (probabilities > threshold).astype(np.float64)


def return_path(
    realized_returns: FloatArray, positions: FloatArray, cost_per_turnover: float
) -> ReturnPath:
    """Apply long/flat positions, transition costs, and mandatory terminal liquidation."""

    if len(realized_returns) != len(positions) or not len(positions):
        raise ValueError("return and position vectors must be non-empty and aligned")
    if (
        not math.isfinite(cost_per_turnover)
        or cost_per_turnover < 0
        or not np.all(np.isfinite(realized_returns))
        or not np.all(np.isfinite(positions))
        or np.any((positions < 0) | (positions > 1))
    ):
        raise ValueError("long/flat positions and non-negative costs are required")
    previous = np.concatenate((np.zeros(1), positions[:-1]))
    turnover = np.abs(positions - previous)
    turnover = turnover.astype(np.float64)
    turnover[-1] += abs(float(positions[-1]))
    gross = positions * realized_returns
    costs = turnover * cost_per_turnover
    return ReturnPath(gross, costs, gross - costs, turnover)


def _fold_indices(ids: Sequence[str], index_by_id: Mapping[str, int]) -> IntArray:
    return np.asarray(sorted(index_by_id[item] for item in ids), dtype=np.int64)


def _labels_strictly_before(
    samples: PreparedSamples, indices: IntArray, boundary: datetime
) -> IntArray:
    filtered = np.asarray(
        [int(index) for index in indices if samples.label_end_times[int(index)] < boundary],
        dtype=np.int64,
    )
    if len(filtered) < 4:
        raise ValueError("label-boundary purge removed too many training observations")
    return filtered


def run_symbol_walk_forward(samples: PreparedSamples, config: RealBacktestConfig) -> SymbolRun:
    """Run rolling candidate selection, calibration, and untouched fold tests."""

    spans = tuple(
        SampleSpan(
            sample_id=sample_id,
            group_time=samples.timestamps[index],
            label_start_time=samples.label_start_times[index],
            label_end_time=samples.label_end_times[index],
            regime=samples.regimes[index],
        )
        for index, sample_id in enumerate(samples.sample_ids)
    )
    policy = TemporalSplitPolicy(
        policy_id="real-binance-hourly-rolling-v1",
        mode=WalkForwardMode.ROLLING,
        train_groups=config.train_hours,
        validation_groups=config.validation_hours,
        calibration_groups=config.calibration_hours,
        test_groups=config.test_hours,
        purge_groups=config.purge_hours,
        embargo_groups=config.embargo_hours,
        step_groups=config.test_hours,
        minimum_folds=3,
        shuffle=False,
    )
    folds = walk_forward_splits(spans, policy)
    index_by_id = {sample_id: index for index, sample_id in enumerate(samples.sample_ids)}
    candidate_probability_parts: dict[str, list[FloatArray]] = {
        item.candidate_id: [] for item in CANDIDATES
    }
    candidate_position_parts: dict[str, list[FloatArray]] = {
        item.candidate_id: [] for item in CANDIDATES
    }
    oos_parts: list[IntArray] = []
    selected_probability_parts: list[FloatArray] = []
    selected_position_parts: list[FloatArray] = []
    selected_threshold_parts: list[FloatArray] = []
    selected_candidate_parts: list[str] = []
    fold_id_parts: list[str] = []
    ledger: list[dict[str, object]] = []

    for fold_number, fold in enumerate(folds):
        train = _fold_indices(fold.train_ids, index_by_id)
        validation = _fold_indices(fold.validation_ids, index_by_id)
        calibration = _fold_indices(fold.calibration_ids, index_by_id)
        test = _fold_indices(fold.test_ids, index_by_id)
        train_validation = _labels_strictly_before(
            samples,
            np.sort(np.concatenate((train, validation))).astype(np.int64),
            samples.timestamps[int(calibration[0])],
        )
        train_calibration = _labels_strictly_before(
            samples,
            np.sort(np.concatenate((train, validation, calibration))).astype(np.int64),
            samples.timestamps[int(test[0])],
        )
        validation_scores: dict[str, float] = {}
        model_hashes: dict[str, str | None] = {}
        for candidate in CANDIDATES:
            probabilities, model_hash = _candidate_probabilities(
                candidate=candidate,
                samples=samples,
                train_indices=train,
                prediction_indices=validation,
                seed=config.seed,
            )
            positions = positions_for(candidate, probabilities, 0.5)
            path = return_path(
                samples.realized_returns[validation], positions, config.cost_per_turnover
            )
            validation_scores[candidate.candidate_id] = float(np.sum(path.net))
            model_hashes[candidate.candidate_id] = model_hash
        selected = max(
            CANDIDATES,
            key=lambda item: validation_scores[item.candidate_id],
        )

        thresholds: dict[str, float] = {}
        calibration_scores: dict[str, float] = {}
        test_probabilities: dict[str, FloatArray] = {}
        test_positions: dict[str, FloatArray] = {}
        for candidate in CANDIDATES:
            calibration_probabilities, _ = _candidate_probabilities(
                candidate=candidate,
                samples=samples,
                train_indices=train_validation,
                prediction_indices=calibration,
                seed=config.seed,
            )
            threshold_grid = CALIBRATION_THRESHOLDS if candidate.fixed_position is None else (0.5,)
            threshold = max(
                threshold_grid,
                key=lambda value: (
                    float(
                        np.sum(
                            return_path(
                                samples.realized_returns[calibration],
                                positions_for(candidate, calibration_probabilities, value),
                                config.cost_per_turnover,
                            ).net
                        )
                    ),
                    value,
                ),
            )
            thresholds[candidate.candidate_id] = threshold
            calibration_scores[candidate.candidate_id] = float(
                np.sum(
                    return_path(
                        samples.realized_returns[calibration],
                        positions_for(candidate, calibration_probabilities, threshold),
                        config.cost_per_turnover,
                    ).net
                )
            )
            probability, _ = _candidate_probabilities(
                candidate=candidate,
                samples=samples,
                train_indices=train_calibration,
                prediction_indices=test,
                seed=config.seed,
            )
            position = positions_for(candidate, probability, threshold)
            test_probabilities[candidate.candidate_id] = probability
            test_positions[candidate.candidate_id] = position
            candidate_probability_parts[candidate.candidate_id].append(probability)
            candidate_position_parts[candidate.candidate_id].append(position)

        chosen_probability = test_probabilities[selected.candidate_id]
        chosen_position = test_positions[selected.candidate_id]
        selected_probability_parts.append(chosen_probability)
        selected_position_parts.append(chosen_position)
        selected_threshold_parts.append(
            np.full(len(test), thresholds[selected.candidate_id], dtype=np.float64)
        )
        selected_candidate_parts.extend((selected.candidate_id,) * len(test))
        fold_id_parts.extend((fold.fold_id,) * len(test))
        oos_parts.append(test)
        ledger.append(
            {
                "symbol": samples.symbol,
                "fold_number": fold_number,
                "fold_id": fold.fold_id,
                "train": {
                    "rows": len(train),
                    "starts_at": _iso(samples.timestamps[int(train[0])]),
                    "ends_at": _iso(samples.timestamps[int(train[-1])]),
                },
                "validation": {
                    "rows": len(validation),
                    "starts_at": _iso(samples.timestamps[int(validation[0])]),
                    "ends_at": _iso(samples.timestamps[int(validation[-1])]),
                },
                "calibration": {
                    "rows": len(calibration),
                    "starts_at": _iso(samples.timestamps[int(calibration[0])]),
                    "ends_at": _iso(samples.timestamps[int(calibration[-1])]),
                },
                "test": {
                    "rows": len(test),
                    "starts_at": _iso(samples.timestamps[int(test[0])]),
                    "ends_at": _iso(samples.timestamps[int(test[-1])]),
                },
                "purged_rows": len(fold.purged_ids),
                "refit_rows_after_label_boundary_purge": {
                    "for_calibration": len(train_validation),
                    "for_test": len(train_calibration),
                },
                "selected_candidate": selected.candidate_id,
                "validation_net_returns": validation_scores,
                "calibration_thresholds": thresholds,
                "calibration_net_returns": calibration_scores,
                "model_spec_sha256": {
                    key: ({"sha256": value} if value is not None else None)
                    for key, value in model_hashes.items()
                },
            }
        )

    oos_indices = np.concatenate(oos_parts).astype(np.int64)
    if np.any(np.diff(oos_indices) != 1):
        raise ValueError("walk-forward test windows must be chronological and contiguous")
    return SymbolRun(
        symbol=samples.symbol,
        samples=samples,
        oos_indices=oos_indices,
        fold_ids=tuple(fold_id_parts),
        selected_candidates=tuple(selected_candidate_parts),
        selected_thresholds=np.concatenate(selected_threshold_parts).astype(np.float64),
        selected_probabilities=np.concatenate(selected_probability_parts).astype(np.float64),
        selected_positions=np.concatenate(selected_position_parts).astype(np.float64),
        candidate_probabilities={
            key: np.concatenate(parts).astype(np.float64)
            for key, parts in candidate_probability_parts.items()
        },
        candidate_positions={
            key: np.concatenate(parts).astype(np.float64)
            for key, parts in candidate_position_parts.items()
        },
        fold_ledger=tuple(ledger),
    )


def classification_metrics(probabilities: FloatArray, targets: FloatArray) -> dict[str, object]:
    if len(probabilities) != len(targets) or not len(targets):
        raise ValueError("classification inputs must be non-empty and aligned")
    if (
        not np.all(np.isfinite(probabilities))
        or np.any((probabilities < 0) | (probabilities > 1))
        or not set(np.unique(targets)).issubset({-1.0, 1.0})
    ):
        raise ValueError("classification probabilities or binary targets are invalid")
    labels = targets > 0
    predicted = probabilities > 0.5
    correct = predicted == labels
    positive_count = int(np.sum(labels))
    negative_count = len(labels) - positive_count
    true_positive_rate = float(np.mean(predicted[labels])) if positive_count else 0.0
    true_negative_rate = float(np.mean(~predicted[~labels])) if negative_count else 0.0
    clipped = np.clip(probabilities, 1e-12, 1.0 - 1e-12)
    binary = labels.astype(np.float64)
    brier = float(np.mean((probabilities - binary) ** 2))
    log_loss = float(-np.mean(binary * np.log(clipped) + (1.0 - binary) * np.log(1.0 - clipped)))
    calibration: list[dict[str, object]] = []
    ece = 0.0
    for bin_index in range(10):
        lower = bin_index / 10
        upper = (bin_index + 1) / 10
        members = (probabilities >= lower) & (
            probabilities <= upper if bin_index == 9 else probabilities < upper
        )
        count = int(np.sum(members))
        if not count:
            continue
        mean_probability = float(np.mean(probabilities[members]))
        observed_frequency = float(np.mean(binary[members]))
        ece += count / len(binary) * abs(mean_probability - observed_frequency)
        calibration.append(
            {
                "lower": lower,
                "upper": upper,
                "observations": count,
                "mean_probability": mean_probability,
                "observed_positive_frequency": observed_frequency,
            }
        )
    return {
        "observations": len(targets),
        "direction_accuracy": float(np.mean(correct)),
        "balanced_accuracy": (true_positive_rate + true_negative_rate) / 2,
        "positive_label_rate": float(np.mean(labels)),
        "brier_score": brier,
        "bernoulli_crps": brier,
        "log_loss": log_loss,
        "expected_calibration_error_10_bin": ece,
        "calibration_curve": calibration,
        "return_quantile_pinball_loss": "NOT_EVALUATED_NO_QUANTILE_FORECAST",
    }


def performance_metrics(path: ReturnPath, positions: FloatArray) -> dict[str, object]:
    if len(path.net) != len(positions):
        raise ValueError("performance inputs are not aligned")
    net_wealth = np.cumprod(1.0 + path.net)
    gross_wealth = np.cumprod(1.0 + path.gross)
    running_peak = np.maximum.accumulate(np.concatenate((np.ones(1), net_wealth)))
    wealth_with_origin = np.concatenate((np.ones(1), net_wealth))
    drawdowns = wealth_with_origin / running_peak - 1.0
    standard_deviation = float(np.std(path.net, ddof=1)) if len(path.net) > 1 else 0.0
    hourly_sharpe = float(np.mean(path.net) / standard_deviation) if standard_deviation else 0.0
    annualized_sharpe = hourly_sharpe * math.sqrt(PERIODS_PER_YEAR)
    downside = path.net[path.net < 0]
    downside_deviation = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        float(np.mean(path.net) / downside_deviation * math.sqrt(PERIODS_PER_YEAR))
        if downside_deviation
        else 0.0
    )
    tail_count = max(1, math.ceil(len(path.net) * 0.05))
    expected_shortfall = float(np.mean(np.sort(path.net)[:tail_count]))
    years = len(path.net) / PERIODS_PER_YEAR
    annualized_return = (
        float(net_wealth[-1] ** (1.0 / years) - 1.0) if years > 0 and net_wealth[-1] > 0 else -1.0
    )
    maximum_drawdown = abs(float(np.min(drawdowns)))
    calmar = annualized_return / maximum_drawdown if maximum_drawdown else 0.0
    total_cost = float(np.sum(path.costs))
    gross_sum = float(np.sum(path.gross))
    active = positions > 0
    return {
        "observations": len(path.net),
        "gross_compound_return": float(gross_wealth[-1] - 1.0),
        "net_compound_return": float(net_wealth[-1] - 1.0),
        "annualized_net_return": annualized_return,
        "annualized_volatility": standard_deviation * math.sqrt(PERIODS_PER_YEAR),
        "annualized_sharpe": annualized_sharpe,
        "hourly_sharpe_for_inference": hourly_sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "maximum_drawdown": maximum_drawdown,
        "expected_shortfall_5pct_hourly": expected_shortfall,
        "total_transaction_cost_return_units": total_cost,
        "cost_to_absolute_gross_sum_ratio": (total_cost / abs(gross_sum) if gross_sum else None),
        "turnover_units": float(np.sum(path.turnover)),
        "position_change_count": int(np.sum(path.turnover > 0)),
        "active_fraction": float(np.mean(active)),
        "active_hit_rate": float(np.mean(path.gross[active] > 0)) if np.any(active) else None,
    }


def moving_block_mean_interval(
    values: FloatArray, *, block_length: int, repetitions: int, seed: int
) -> tuple[float, float]:
    """Return a deterministic 95% moving-block bootstrap interval for the mean."""

    if not len(values) or block_length < 1 or repetitions < 20:
        raise ValueError("valid block bootstrap inputs are required")
    rng = np.random.default_rng(seed)
    offsets = np.arange(block_length, dtype=np.int64)
    block_count = math.ceil(len(values) / block_length)
    means = np.empty(repetitions, dtype=np.float64)
    for repetition in range(repetitions):
        starts = rng.integers(0, len(values), size=block_count)
        indices = ((starts[:, None] + offsets[None, :]) % len(values)).reshape(-1)
        means[repetition] = float(np.mean(values[indices[: len(values)]]))
    lower, upper = np.quantile(means, (0.025, 0.975))
    return float(lower), float(upper)


def _one_sided_mean_p_value(
    values: FloatArray, *, block_length: int, repetitions: int, seed: int
) -> float:
    observed = float(np.mean(values))
    centered = values - observed
    rng = np.random.default_rng(seed)
    offsets = np.arange(block_length, dtype=np.int64)
    block_count = math.ceil(len(values) / block_length)
    exceedances = 0
    for _ in range(repetitions):
        starts = rng.integers(0, len(values), size=block_count)
        indices = ((starts[:, None] + offsets[None, :]) % len(values)).reshape(-1)
        if float(np.mean(centered[indices[: len(values)]])) >= observed:
            exceedances += 1
    return (exceedances + 1) / (repetitions + 1)


def white_reality_check(
    returns_by_strategy: FloatArray,
    *,
    block_length: int,
    repetitions: int,
    seed: int,
) -> dict[str, object]:
    """Moving-block White Reality Check of the best mean net return against zero."""

    if returns_by_strategy.ndim != 2 or returns_by_strategy.shape[1] < 2:
        raise ValueError("reality check requires at least two strategy trials")
    observed_means = np.mean(returns_by_strategy, axis=0)
    observed_max = float(np.max(observed_means))
    centered = returns_by_strategy - observed_means
    rng = np.random.default_rng(seed)
    offsets = np.arange(block_length, dtype=np.int64)
    block_count = math.ceil(len(centered) / block_length)
    exceedances = 0
    for _ in range(repetitions):
        starts = rng.integers(0, len(centered), size=block_count)
        indices = ((starts[:, None] + offsets[None, :]) % len(centered)).reshape(-1)
        bootstrap_max = float(np.max(np.mean(centered[indices[: len(centered)]], axis=0)))
        if bootstrap_max >= observed_max:
            exceedances += 1
    return {
        "method": "WHITE_REALITY_CHECK_MOVING_BLOCK_BOOTSTRAP",
        "null": "maximum mean net return across declared trials is not positive",
        "observed_best_hourly_mean_net_return": observed_max,
        "p_value": (exceedances + 1) / (repetitions + 1),
        "block_length_hours": block_length,
        "repetitions": repetitions,
    }


def _moments(values: FloatArray) -> tuple[float, float, float]:
    standard_deviation = float(np.std(values, ddof=1))
    if not standard_deviation:
        return 0.0, 0.0, 3.0
    centered = (values - float(np.mean(values))) / standard_deviation
    return (
        float(np.mean(values) / standard_deviation),
        float(np.mean(centered**3)),
        float(np.mean(centered**4)),
    )


def _aggregate_paths(
    runs: Sequence[SymbolRun], config: RealBacktestConfig
) -> tuple[dict[str, ReturnPath], ReturnPath]:
    if not runs:
        raise ValueError("at least one symbol run is required")
    timestamps = tuple(
        runs[0].samples.label_start_times[int(index)] for index in runs[0].oos_indices
    )
    for run in runs[1:]:
        other = tuple(run.samples.label_start_times[int(index)] for index in run.oos_indices)
        if other != timestamps:
            raise ValueError("cross-asset OOS timestamps must align")
    candidate_paths: dict[str, ReturnPath] = {}
    for candidate in CANDIDATES:
        paths = [
            return_path(
                run.samples.realized_returns[run.oos_indices],
                run.candidate_positions[candidate.candidate_id],
                config.cost_per_turnover,
            )
            for run in runs
        ]
        candidate_paths[candidate.candidate_id] = ReturnPath(
            gross=np.mean(np.vstack([item.gross for item in paths]), axis=0),
            costs=np.mean(np.vstack([item.costs for item in paths]), axis=0),
            net=np.mean(np.vstack([item.net for item in paths]), axis=0),
            turnover=np.mean(np.vstack([item.turnover for item in paths]), axis=0),
        )
    selected_paths = [
        return_path(
            run.samples.realized_returns[run.oos_indices],
            run.selected_positions,
            config.cost_per_turnover,
        )
        for run in runs
    ]
    selected_path = ReturnPath(
        gross=np.mean(np.vstack([item.gross for item in selected_paths]), axis=0),
        costs=np.mean(np.vstack([item.costs for item in selected_paths]), axis=0),
        net=np.mean(np.vstack([item.net for item in selected_paths]), axis=0),
        turnover=np.mean(np.vstack([item.turnover for item in selected_paths]), axis=0),
    )
    return candidate_paths, selected_path


def statistical_report(runs: Sequence[SymbolRun], config: RealBacktestConfig) -> dict[str, object]:
    candidate_paths, selected_path = _aggregate_paths(runs, config)
    candidate_ids = tuple(item.candidate_id for item in CANDIDATES)
    trial_ids = (*candidate_ids, "selected_meta_policy")
    trial_returns = {
        **{candidate_id: candidate_paths[candidate_id].net for candidate_id in candidate_ids},
        "selected_meta_policy": selected_path.net,
    }
    return_matrix = np.column_stack([trial_returns[item] for item in trial_ids])
    segments = np.array_split(np.arange(len(return_matrix)), 8)
    segment_returns = tuple(
        tuple(
            Decimal(format(float(np.sum(return_matrix[segment, column])), ".15g"))
            for column in range(len(trial_ids))
        )
        for segment in segments
    )
    pbo = probability_of_backtest_overfitting(segment_returns)
    p_values = {
        candidate_id: Decimal(
            format(
                _one_sided_mean_p_value(
                    trial_returns[candidate_id],
                    block_length=config.bootstrap_block_hours,
                    repetitions=config.bootstrap_repetitions,
                    seed=config.seed + index,
                ),
                ".15g",
            )
        )
        for index, candidate_id in enumerate(trial_ids)
        if candidate_id != "always_flat"
    }
    fdr = benjamini_hochberg(p_values, alpha=Decimal("0.05"))
    hourly_sharpe, skewness, kurtosis = _moments(selected_path.net)
    trial_sharpes = tuple(
        Decimal(format(_moments(trial_returns[trial_id])[0], ".15g")) for trial_id in trial_ids
    )
    psr = probabilistic_sharpe_ratio(
        observed_sharpe=Decimal(format(hourly_sharpe, ".15g")),
        benchmark_sharpe=Decimal("0"),
        observations=len(selected_path.net),
        skewness=Decimal(format(skewness, ".15g")),
        kurtosis=Decimal(format(max(kurtosis, 1.0), ".15g")),
    )
    dsr = deflated_sharpe_ratio(
        observed_sharpe=Decimal(format(hourly_sharpe, ".15g")),
        observations=len(selected_path.net),
        skewness=Decimal(format(skewness, ".15g")),
        kurtosis=Decimal(format(max(kurtosis, 1.0), ".15g")),
        trial_sharpes=trial_sharpes,
    )
    reality = white_reality_check(
        return_matrix[:, 1:],
        block_length=config.bootstrap_block_hours,
        repetitions=config.bootstrap_repetitions,
        seed=config.seed,
    )
    return {
        "inference_return_frequency": "HOURLY_UNANNUALIZED",
        "declared_trial_ids": list(trial_ids),
        "trial_count": len(trial_ids),
        "pbo": pbo.model_dump(mode="json"),
        "probabilistic_sharpe_ratio": psr.model_dump(mode="json"),
        "deflated_sharpe_ratio": dsr.model_dump(mode="json"),
        "white_reality_check": reality,
        "benjamini_hochberg_fdr": fdr.model_dump(mode="json"),
        "block_bootstrap": {
            "kind": "CIRCULAR_MOVING_BLOCK",
            "block_length_hours": config.bootstrap_block_hours,
            "repetitions": config.bootstrap_repetitions,
            "seed": config.seed,
        },
    }


def _selected_symbol_report(run: SymbolRun, config: RealBacktestConfig) -> dict[str, object]:
    realized = run.samples.realized_returns[run.oos_indices]
    targets = run.samples.targets[run.oos_indices]
    path = return_path(realized, run.selected_positions, config.cost_per_turnover)
    classification = classification_metrics(run.selected_probabilities, targets)
    correct = ((run.selected_probabilities > 0.5) == (targets > 0)).astype(np.float64)
    accuracy_interval = moving_block_mean_interval(
        correct,
        block_length=config.bootstrap_block_hours,
        repetitions=config.bootstrap_repetitions,
        seed=config.seed,
    )
    candidate_metrics: dict[str, object] = {}
    for candidate in CANDIDATES:
        candidate_path = return_path(
            realized,
            run.candidate_positions[candidate.candidate_id],
            config.cost_per_turnover,
        )
        candidate_metrics[candidate.candidate_id] = {
            "classification": classification_metrics(
                run.candidate_probabilities[candidate.candidate_id], targets
            ),
            "performance": performance_metrics(
                candidate_path, run.candidate_positions[candidate.candidate_id]
            ),
        }
    cost_stress = {}
    for factor in (1.0, 1.5, 2.0, 3.0):
        stressed = return_path(realized, run.selected_positions, config.cost_per_turnover * factor)
        cost_stress[f"{factor:.1f}x"] = performance_metrics(stressed, run.selected_positions)
    latency_stress = {}
    for additional_delay in (0, 1, 6, 24):
        delayed = np.zeros_like(run.selected_positions)
        if additional_delay == 0:
            delayed[:] = run.selected_positions
        else:
            delayed[additional_delay:] = run.selected_positions[:-additional_delay]
        latency_stress[f"additional_{additional_delay}h"] = performance_metrics(
            return_path(realized, delayed, config.cost_per_turnover), delayed
        )
    regimes: dict[str, object] = {}
    oos_regimes = np.asarray(
        [run.samples.regimes[int(index)] for index in run.oos_indices], dtype=np.str_
    )
    for regime in sorted(set(oos_regimes.tolist())):
        members = oos_regimes == regime
        regimes[regime] = {
            "observations": int(np.sum(members)),
            "direction_accuracy": float(
                np.mean((run.selected_probabilities[members] > 0.5) == (targets[members] > 0))
            ),
            "mean_net_return": float(np.mean(path.net[members])),
            "active_fraction": float(np.mean(run.selected_positions[members] > 0)),
        }
    changes = path.turnover > 0
    capacity: dict[str, object] = {}
    for notional in (1_000, 10_000, 100_000, 1_000_000):
        if not np.any(changes):
            capacity[str(notional)] = {"status": "NO_TRADES"}
            continue
        participation = (
            path.turnover[changes]
            * notional
            / run.samples.entry_quote_volume[run.oos_indices][changes]
        )
        capacity[str(notional)] = {
            "currency": "USDT",
            "median_participation": float(np.median(participation)),
            "p95_participation": float(np.quantile(participation, 0.95)),
            "maximum_participation": float(np.max(participation)),
            "fraction_at_or_below_1pct": float(np.mean(participation <= 0.01)),
            "interpretation": "DIAGNOSTIC_ONLY_NO_ORDER_BOOK_IMPACT_CALIBRATION",
        }
    return {
        "symbol": run.symbol,
        "fold_count": len(run.fold_ledger),
        "oos_starts_at": _iso(run.samples.timestamps[int(run.oos_indices[0])]),
        "oos_ends_at": _iso(run.samples.timestamps[int(run.oos_indices[-1])]),
        "selected_candidate_counts": {
            candidate.candidate_id: run.selected_candidates.count(candidate.candidate_id)
            // config.test_hours
            for candidate in CANDIDATES
        },
        "selected_policy": {
            "classification": {
                **classification,
                "direction_accuracy_block_bootstrap_95pct_interval": list(accuracy_interval),
            },
            "performance": performance_metrics(path, run.selected_positions),
        },
        "candidate_trials": candidate_metrics,
        "cost_stress": cost_stress,
        "additional_execution_latency_stress": latency_stress,
        "pit_regime_slices": regimes,
        "capacity_participation_diagnostic": capacity,
    }


def build_backtest_report(
    *,
    config: RealBacktestConfig,
    downloads: Sequence[DownloadedKlines],
    runs: Sequence[SymbolRun],
    generated_at: datetime,
) -> dict[str, object]:
    """Assemble an honest report that cannot be mistaken for a promotion artifact."""

    if tuple(item.symbol for item in downloads) != tuple(item.symbol for item in runs):
        raise ValueError("downloads and backtest runs are not aligned")
    symbol_reports = [_selected_symbol_report(run, config) for run in runs]
    statistics = statistical_report(runs, config)
    candidate_paths, aggregate_path = _aggregate_paths(runs, config)
    average_position = np.mean(np.vstack([run.selected_positions for run in runs]), axis=0).astype(
        np.float64
    )
    aggregate_performance = performance_metrics(aggregate_path, average_position)
    aggregate_probabilities = np.concatenate([run.selected_probabilities for run in runs]).astype(
        np.float64
    )
    aggregate_targets = np.concatenate(
        [run.samples.targets[run.oos_indices] for run in runs]
    ).astype(np.float64)
    aggregate_classification = classification_metrics(aggregate_probabilities, aggregate_targets)
    aligned_correct = np.mean(
        np.vstack(
            [
                (run.selected_probabilities > 0.5) == (run.samples.targets[run.oos_indices] > 0)
                for run in runs
            ]
        ),
        axis=0,
    ).astype(np.float64)
    aggregate_classification["direction_accuracy_block_bootstrap_95pct_interval"] = list(
        moving_block_mean_interval(
            aligned_correct,
            block_length=config.bootstrap_block_hours,
            repetitions=config.bootstrap_repetitions,
            seed=config.seed,
        )
    )
    aggregate_classification["direction_accuracy_one_sided_block_bootstrap_p_value"] = (
        _one_sided_mean_p_value(
            aligned_correct - 0.5,
            block_length=config.bootstrap_block_hours,
            repetitions=config.bootstrap_repetitions,
            seed=config.seed,
        )
    )
    candidate_classification: dict[str, dict[str, object]] = {}
    direction_p_values: dict[str, Decimal] = {
        "selected_meta_policy": Decimal(
            format(
                _report_float(
                    aggregate_classification[
                        "direction_accuracy_one_sided_block_bootstrap_p_value"
                    ],
                    field="selected_accuracy_p_value",
                ),
                ".15g",
            )
        )
    }
    for candidate_number, candidate in enumerate(CANDIDATES):
        probabilities = np.concatenate(
            [run.candidate_probabilities[candidate.candidate_id] for run in runs]
        ).astype(np.float64)
        metrics = classification_metrics(probabilities, aggregate_targets)
        candidate_aligned_correct = np.mean(
            np.vstack(
                [
                    (run.candidate_probabilities[candidate.candidate_id] > 0.5)
                    == (run.samples.targets[run.oos_indices] > 0)
                    for run in runs
                ]
            ),
            axis=0,
        ).astype(np.float64)
        metrics["direction_accuracy_block_bootstrap_95pct_interval"] = list(
            moving_block_mean_interval(
                candidate_aligned_correct,
                block_length=config.bootstrap_block_hours,
                repetitions=config.bootstrap_repetitions,
                seed=config.seed + candidate_number + 1,
            )
        )
        direction_p_value = _one_sided_mean_p_value(
            candidate_aligned_correct - 0.5,
            block_length=config.bootstrap_block_hours,
            repetitions=config.bootstrap_repetitions,
            seed=config.seed + candidate_number + 1,
        )
        metrics["direction_accuracy_one_sided_block_bootstrap_p_value"] = direction_p_value
        direction_p_values[candidate.candidate_id] = Decimal(format(direction_p_value, ".15g"))
        candidate_classification[candidate.candidate_id] = metrics
    direction_fdr = benjamini_hochberg(direction_p_values, alpha=Decimal("0.05")).model_dump(
        mode="json"
    )
    reality = cast("dict[str, object]", statistics["white_reality_check"])
    dsr = cast("dict[str, object]", statistics["deflated_sharpe_ratio"])
    pbo = cast("dict[str, object]", statistics["pbo"])
    fdr = cast("dict[str, object]", statistics["benjamini_hochberg_fdr"])
    fdr_results = cast("list[dict[str, object]]", fdr["results"])
    selected_fdr_rejected = any(
        item.get("hypothesis_id") == "selected_meta_policy" and item.get("rejected") is True
        for item in fdr_results
    )
    statistical_pass = (
        _report_float(reality["p_value"], field="reality_check.p_value") <= 0.05
        and _report_float(dsr["probability"], field="dsr.probability") >= 0.95
        and _report_float(pbo["probability"], field="pbo.probability") <= 0.25
        and _report_float(
            aggregate_performance["net_compound_return"],
            field="aggregate.net_compound_return",
        )
        > 0
        and selected_fdr_rejected
    )
    accuracy_interval = aggregate_classification[
        "direction_accuracy_block_bootstrap_95pct_interval"
    ]
    always_long_path = candidate_paths["always_long"]
    always_long_position = np.ones(len(always_long_path.net), dtype=np.float64)
    always_long_performance = performance_metrics(always_long_path, always_long_position)
    gap_count = sum(
        _report_int(
            cast("dict[str, object]", item.source_manifest["dataset"]).get("gap_count", 0),
            field="dataset.gap_count",
        )
        for item in downloads
    )
    statistics["direction_accuracy_benjamini_hochberg_fdr"] = direction_fdr
    best_directional_candidate = max(
        CANDIDATES,
        key=lambda candidate: _report_float(
            candidate_classification[candidate.candidate_id]["direction_accuracy"],
            field="candidate.direction_accuracy",
        ),
    )
    direction_fdr_results = cast("list[dict[str, object]]", direction_fdr["results"])
    best_directional_significant = any(
        item.get("hypothesis_id") == best_directional_candidate.candidate_id
        and item.get("rejected") is True
        for item in direction_fdr_results
    )
    return {
        "schema_version": "aegisquant-real-market-backtest-v1",
        "generated_at_utc": _iso(generated_at),
        "scope": {
            "mode": "OOS_DEVELOPMENT_WALK_FORWARD",
            "market_modality": "MARKET_ONLY",
            "venue": "BINANCE_SPOT",
            "final_holdout": "SEALED_NOT_OPENED",
            "live_trading": "LOCKED",
            "claims": [
                "Measures one-hour market-direction forecasts only.",
                "Does not measure event extraction, event truth, causal truth, or news latency.",
                "Does not use account-specific realized execution costs.",
            ],
        },
        "experiment": config.as_payload(),
        "data": {
            item.symbol: {
                "rows": len(item.rows),
                "eligible_trailing_feature_samples": len(run.samples.sample_ids),
                "dataset": cast("dict[str, object]", item.source_manifest["dataset"]),
                "cache_directory": item.cache_directory.as_posix(),
            }
            for item, run in zip(downloads, runs, strict=True)
        },
        "feature_contract": {
            "feature_names": list(FEATURE_NAMES),
            "all_features_trailing_only": True,
            "split_window_unit": "ELIGIBLE_HOURLY_OBSERVATIONS",
            "samples_touching_exchange_data_gaps": "EXCLUDED",
            "normalization_fit_scope": "EACH_FOLD_TRAINING_ONLY",
            "label": "open[t+2] / open[t+1] - 1",
            "signal_available_after": "close[t]",
            "earliest_execution": "open[t+1]",
            "lookahead_detected": False,
        },
        "aggregate_selected_policy": {
            "classification": aggregate_classification,
            "performance": aggregate_performance,
        },
        "result_interpretation": {
            "selected_policy_directional_edge": (
                "DEMONSTRATED_ABOVE_50PCT"
                if accuracy_interval[0] > 0.5
                else "NOT_DEMONSTRATED_CONFIDENCE_INTERVAL_INCLUDES_50PCT"
            ),
            "best_directional_candidate": best_directional_candidate.candidate_id,
            "best_directional_candidate_accuracy": candidate_classification[
                best_directional_candidate.candidate_id
            ]["direction_accuracy"],
            "best_directional_candidate_signal": (
                "SURVIVES_DIRECTION_ACCURACY_FDR"
                if best_directional_significant
                else "DOES_NOT_SURVIVE_DIRECTION_ACCURACY_FDR"
            ),
            "robust_net_alpha": (
                "DEMONSTRATED_IN_DEVELOPMENT_OOS" if statistical_pass else "NOT_DEMONSTRATED"
            ),
            "selected_net_return_minus_always_long_return": (
                _report_float(
                    aggregate_performance["net_compound_return"],
                    field="aggregate.net_compound_return",
                )
                - _report_float(
                    always_long_performance["net_compound_return"],
                    field="always_long.net_compound_return",
                )
            ),
            "positive_return_attribution": (
                "LONG_OR_FLAT_MARKET_BETA_SELECTION_NOT_PROVEN_FORECAST_ALPHA"
            ),
        },
        "symbols": symbol_reports,
        "statistics": statistics,
        "candidate_portfolio_classification": candidate_classification,
        "candidate_portfolio_performance": {
            candidate.candidate_id: performance_metrics(
                candidate_paths[candidate.candidate_id],
                np.mean(
                    np.vstack([run.candidate_positions[candidate.candidate_id] for run in runs]),
                    axis=0,
                ).astype(np.float64),
            )
            for candidate in CANDIDATES
        },
        "gate_assessment": {
            "data": (
                "PASS_DEVELOPMENT_REAL_PUBLIC_GAPS_DISCLOSED_AND_EXCLUDED"
                if gap_count
                else "PASS_DEVELOPMENT_REAL_PUBLIC_COMPLETE_GRID_HASHED"
            ),
            "economics": "BLOCKED_ASSUMED_COSTS_NO_ACCOUNT_TCA",
            "statistics": ("PASS_DEVELOPMENT" if statistical_pass else "FAIL_NO_ROBUST_OOS_ALPHA"),
            "event_truth": "NOT_EVALUATED_MARKET_ONLY",
            "causal_truth": "NOT_EVALUATED_MARKET_ONLY",
            "forward_shadow": "BLOCKED_NO_FORWARD_OR_SHADOW_OBSERVATION",
            "final_holdout": "SEALED_NOT_OPENED",
            "global_promotion": "NO_PROMOTION",
            "required_action": "KEEP_LIVE_LOCKED",
        },
        "limitations": [
            "Fees and spread/slippage/impact are conservative assumptions, not realized TCA.",
            "Hourly OHLCV cannot reproduce queue position, partial fills, or intrabar path.",
            "Binance is one venue; BTCUSDT and ETHUSDT are two correlated crypto assets.",
            "This development OOS run is not the one-time final holdout and is not forward proof.",
            "Market-only results cannot validate AegisQuant event, truth, or causal subsystems.",
        ],
    }


def write_oos_csv(runs: Sequence[SymbolRun], config: RealBacktestConfig, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            (
                "symbol",
                "sample_id",
                "decision_time_utc",
                "label_start_time_utc",
                "label_end_time_utc",
                "fold_id",
                "selected_candidate",
                "threshold",
                "positive_probability",
                "position",
                "realized_return",
                "gross_return",
                "cost_return",
                "net_return",
            )
        )
        for run in runs:
            realized = run.samples.realized_returns[run.oos_indices]
            path_values = return_path(realized, run.selected_positions, config.cost_per_turnover)
            for output_index, sample_index in enumerate(run.oos_indices):
                index = int(sample_index)
                writer.writerow(
                    (
                        run.symbol,
                        run.samples.sample_ids[index],
                        _iso(run.samples.timestamps[index]),
                        _iso(run.samples.label_start_times[index]),
                        _iso(run.samples.label_end_times[index]),
                        run.fold_ids[output_index],
                        run.selected_candidates[output_index],
                        run.selected_thresholds[output_index],
                        run.selected_probabilities[output_index],
                        run.selected_positions[output_index],
                        realized[output_index],
                        path_values.gross[output_index],
                        path_values.costs[output_index],
                        path_values.net[output_index],
                    )
                )
    temporary.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_markdown(report: Mapping[str, object]) -> str:
    aggregate = cast("dict[str, object]", report["aggregate_selected_policy"])
    classification = cast("dict[str, object]", aggregate["classification"])
    performance = cast("dict[str, object]", aggregate["performance"])
    gates = cast("dict[str, object]", report["gate_assessment"])
    statistics = cast("dict[str, object]", report["statistics"])
    pbo = cast("dict[str, object]", statistics["pbo"])
    dsr = cast("dict[str, object]", statistics["deflated_sharpe_ratio"])
    reality = cast("dict[str, object]", statistics["white_reality_check"])
    candidate_classification = cast(
        "dict[str, dict[str, object]]", report["candidate_portfolio_classification"]
    )
    candidate_performance = cast(
        "dict[str, dict[str, object]]", report["candidate_portfolio_performance"]
    )
    interpretation = cast("dict[str, object]", report["result_interpretation"])
    interval = cast(
        "list[object]", classification["direction_accuracy_block_bootstrap_95pct_interval"]
    )

    def candidate_row(candidate: CandidateDefinition) -> str:
        metrics = candidate_classification[candidate.candidate_id]
        candidate_interval = cast(
            "list[object]", metrics["direction_accuracy_block_bootstrap_95pct_interval"]
        )
        return (
            f"| `{candidate.candidate_id}` | "
            f"{_report_float(metrics['direction_accuracy'], field='candidate_accuracy'):.4%} | "
            f"[{_report_float(candidate_interval[0], field='candidate_ci_lower'):.4%}, "
            f"{_report_float(candidate_interval[1], field='candidate_ci_upper'):.4%}] | "
            f"{_report_float(candidate_performance[candidate.candidate_id]['net_compound_return'], field='candidate_net_return'):.4%} | "
            f"{_report_float(candidate_performance[candidate.candidate_id]['annualized_sharpe'], field='candidate_sharpe'):.4f} |"
        )

    lines = [
        "# AegisQuant 真实公开市场样本外回测",
        "",
        f"- 模式：`{cast('dict[str, object]', report['scope'])['mode']}`（不是最终盲测）",
        f"- 方向准确率：`{_report_float(classification['direction_accuracy'], field='accuracy'):.4%}`",
        f"- 方向准确率 95% 块自助区间：`[{_report_float(interval[0], field='accuracy_ci_lower'):.4%}, {_report_float(interval[1], field='accuracy_ci_upper'):.4%}]`",
        f"- Brier：`{_report_float(classification['brier_score'], field='brier'):.6f}`",
        f"- ECE（10 桶）：`{_report_float(classification['expected_calibration_error_10_bin'], field='ece'):.6f}`",
        f"- 扣费后复合收益：`{_report_float(performance['net_compound_return'], field='net_return'):.4%}`",
        f"- 年化 Sharpe：`{_report_float(performance['annualized_sharpe'], field='sharpe'):.4f}`",
        f"- 最大回撤：`{_report_float(performance['maximum_drawdown'], field='drawdown'):.4%}`",
        f"- PBO：`{_report_float(pbo['probability'], field='pbo'):.4f}`",
        f"- DSR 概率：`{_report_float(dsr['probability'], field='dsr'):.4f}`",
        f"- White Reality Check p 值：`{_report_float(reality['p_value'], field='reality_check'):.4f}`",
        f"- 全局结论：`{gates['global_promotion']}` / `{gates['required_action']}`",
        "",
        "## 候选对照",
        "",
        "| 候选 | 方向准确率 | 95% 块自助区间 | 扣成本复合收益 | 年化 Sharpe |",
        "|---|---:|---:|---:|---:|",
        *(candidate_row(candidate) for candidate in CANDIDATES),
        "",
        f"所选元策略方向优势：`{interpretation['selected_policy_directional_edge']}`；最佳方向候选：`{interpretation['best_directional_candidate']}` / `{interpretation['best_directional_candidate_signal']}`；稳健净 Alpha：`{interpretation['robust_net_alpha']}`。即使部分分类器方向命中率显著高于 50%，其幅度仍不足以覆盖预设交易成本；当前正收益主要来自滚动验证选择出的 long/flat 市场 Beta 暴露，并不构成预测 Alpha 证明。",
        "",
        "## 结论边界",
        "",
        "该结果只衡量 Binance Spot 的 BTCUSDT/ETHUSDT 一小时市场方向预测。成本为预先声明的保守假设，不是账户真实 TCA；事件真值、因果链、新闻时延、Forward/Shadow 和最终盲测均未被验证，因此无论历史指标好坏都不得晋级实盘。",
        "",
    ]
    return "\n".join(lines)


def write_evidence(
    *,
    root: Path,
    config: RealBacktestConfig,
    downloads: Sequence[DownloadedKlines],
    runs: Sequence[SymbolRun],
    report: Mapping[str, object],
    report_directory: Path,
    bronze_directory: Path,
    gold_directory: Path,
) -> dict[str, object]:
    """Persist compact versioned evidence plus ignored reproducible row-level artifacts."""

    report_directory.mkdir(parents=True, exist_ok=True)
    bronze_hashes: dict[str, dict[str, str]] = {}
    artifact_paths: list[Path] = []
    for download in downloads:
        bronze_path = bronze_directory / f"{download.symbol}_{INTERVAL}.csv"
        bronze_hashes[download.symbol] = {"sha256": write_bronze_csv(download, bronze_path)}
        artifact_paths.append(bronze_path)
    oos_path = gold_directory / "OOS_PREDICTIONS.csv"
    oos_hash = write_oos_csv(runs, config, oos_path)
    artifact_paths.append(oos_path)

    source_manifest_path = report_directory / "SOURCE_DATA_MANIFEST.json"
    trial_ledger_path = report_directory / "TRIAL_LEDGER.json"
    report_path = report_directory / "BACKTEST_REPORT.json"
    markdown_path = report_directory / "BACKTEST_REPORT.md"
    source_payload = {
        "schema_version": "aegisquant-real-source-evidence-v1",
        "official_public_source": True,
        "authentication_used": False,
        "downloads": [item.source_manifest for item in downloads],
        "bronze": bronze_hashes,
    }
    trial_payload = {
        "schema_version": "aegisquant-real-trial-ledger-v1",
        "precommitted_candidate_ids": [item.candidate_id for item in CANDIDATES],
        "calibration_thresholds": list(CALIBRATION_THRESHOLDS),
        "folds": [entry for run in runs for entry in run.fold_ledger],
        "post_test_tuning_performed": False,
    }
    _atomic_write(source_manifest_path, canonical_json_bytes(source_payload))
    _atomic_write(trial_ledger_path, canonical_json_bytes(trial_payload))
    _atomic_write(report_path, canonical_json_bytes(dict(report)))
    _atomic_write(markdown_path, render_markdown(report).encode("utf-8"))
    artifact_paths.extend((source_manifest_path, trial_ledger_path, report_path, markdown_path))

    code_paths = (
        root / "src/aegisquant/research/validation/public_market_backtest.py",
        root / "scripts/run_real_market_backtest.py",
    )
    artifact_paths.extend(code_paths)
    entries: list[dict[str, object]] = []
    for path in sorted(artifact_paths, key=lambda item: item.as_posix()):
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "content": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
            }
        )
    manifest: dict[str, object] = {
        "schema_version": "aegisquant-real-backtest-run-manifest-v1",
        "experiment": config.as_payload(),
        "experiment_sha256": {"sha256": canonical_sha256(config.as_payload())},
        "backtest_result_excluding_generated_at_sha256": {
            "sha256": canonical_sha256(
                {key: value for key, value in report.items() if key != "generated_at_utc"}
            )
        },
        "oos_predictions": {"sha256": oos_hash},
        "artifacts": entries,
        "artifact_set_sha256": {"sha256": canonical_sha256(entries)},
        "replay_from_current_workspace_cache_requires_network": False,
        "replay_from_git_archive_requires_network": True,
        "redownload_supported": True,
        "promotion_authority": False,
    }
    manifest_path = report_directory / "RUN_MANIFEST.json"
    _atomic_write(manifest_path, canonical_json_bytes(manifest))
    return manifest


def verify_evidence(root: Path, manifest_path: Path) -> None:
    manifest = _as_object(_decode_json(manifest_path.read_bytes()), name="run manifest")
    entries = _as_list(manifest.get("artifacts"), name="run artifacts")
    normalized: list[dict[str, object]] = []
    for value in entries:
        entry = _as_object(value, name="run artifact")
        relative = entry.get("path")
        content = _as_object(entry.get("content"), name="run artifact content")
        expected = content.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("run artifact entry is invalid")
        path = root / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"run artifact hash mismatch: {relative}")
        normalized.append(entry)
    commitment = _as_object(manifest.get("artifact_set_sha256"), name="artifact set commitment")
    if commitment.get("sha256") != canonical_sha256(normalized):
        raise ValueError("run artifact set commitment is invalid")
