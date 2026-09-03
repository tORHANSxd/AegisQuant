from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from aegisquant.data.hashing import canonical_json_bytes
from aegisquant.data.providers.binance.contracts import RestEndpoint
from aegisquant.data.providers.binance.models import RawResponseEnvelope
from aegisquant.research.validation.public_market_backtest import (
    DownloadedKlines,
    RealBacktestConfig,
    build_backtest_report,
    load_or_download_spot_klines,
    moving_block_mean_interval,
    parse_kline_payload,
    prepare_samples,
    return_path,
    run_symbol_walk_forward,
    white_reality_check,
)

NOW = datetime(2021, 1, 1, tzinfo=UTC)
HOUR_MS = 3_600_000


def raw_row(index: int, price: float) -> list[object]:
    opened = int(NOW.timestamp() * 1_000) + index * HOUR_MS
    return [
        opened,
        f"{price:.8f}",
        f"{price * 1.01:.8f}",
        f"{price * 0.99:.8f}",
        f"{price * (1 + 0.002 * math.sin(index)):.8f}",
        "100.0",
        opened + HOUR_MS - 1,
        f"{price * 100:.8f}",
        100 + index,
        "51.0",
        f"{price * 51:.8f}",
        "0",
    ]


def downloaded(count: int = 1_200, *, mutate_from: int | None = None) -> DownloadedKlines:
    payload: list[list[object]] = []
    for index in range(count):
        price = 100 + 5 * math.sin(index / 7) + index * 0.01
        if mutate_from is not None and index >= mutate_from:
            price *= 3
        payload.append(raw_row(index, price))
    return DownloadedKlines(
        symbol="BTCUSDT",
        rows=parse_kline_payload(payload),
        cache_directory=Path("data/raw/test"),
        source_manifest={"dataset": {"sha256": "0" * 64}},
    )


def config(*, end_hours: int = 1_200) -> RealBacktestConfig:
    return RealBacktestConfig(
        symbols=("BTCUSDT",),
        start_at=NOW,
        end_at_exclusive=NOW + timedelta(hours=end_hours),
        train_hours=300,
        validation_hours=50,
        calibration_hours=50,
        test_hours=100,
        purge_hours=2,
        embargo_hours=2,
        bootstrap_repetitions=20,
        bootstrap_block_hours=4,
        seed=7,
    )


def test_parse_kline_payload_requires_exact_wire_contract() -> None:
    parsed = parse_kline_payload([raw_row(0, 100.0)])
    assert parsed[0].close_time_ms == parsed[0].open_time_ms + HOUR_MS - 1
    early_close = raw_row(0, 100.0)
    early_open = early_close[0]
    assert isinstance(early_open, int)
    early_close[6] = early_open + HOUR_MS // 2
    assert parse_kline_payload([early_close])[0].close_time_ms == early_close[6]
    malformed = raw_row(0, 100.0)[:-1]
    try:
        parse_kline_payload([malformed])
    except ValueError as error:
        assert "twelve fields" in str(error)
    else:
        raise AssertionError("malformed kline was accepted")


def test_future_market_mutation_cannot_change_prior_features() -> None:
    baseline = prepare_samples(downloaded())
    mutated = prepare_samples(downloaded(mutate_from=1_100))
    prior_samples = 1_100 - 168
    np.testing.assert_array_equal(
        baseline.features[:prior_samples], mutated.features[:prior_samples]
    )
    np.testing.assert_array_equal(
        baseline.realized_returns[: prior_samples - 2],
        mutated.realized_returns[: prior_samples - 2],
    )


def test_long_flat_return_path_charges_entry_exit_and_terminal_liquidation() -> None:
    realized = np.asarray([0.01, 0.02, -0.01, 0.03], dtype=np.float64)
    positions = np.asarray([0.0, 1.0, 1.0, 1.0], dtype=np.float64)
    path = return_path(realized, positions, 0.001)
    assert np.sum(path.turnover) == 2.0
    assert np.sum(path.costs) == 0.002
    assert np.sum(path.gross) == 0.04
    assert np.sum(path.net) == 0.038


def test_block_statistics_are_seeded_and_finite() -> None:
    values = np.asarray([0.01, -0.005, 0.003, 0.002] * 20, dtype=np.float64)
    first = moving_block_mean_interval(values, block_length=4, repetitions=40, seed=3)
    second = moving_block_mean_interval(values, block_length=4, repetitions=40, seed=3)
    assert first == second
    reality = white_reality_check(
        np.column_stack((values, values * 0.5)),
        block_length=4,
        repetitions=40,
        seed=3,
    )
    p_value = reality["p_value"]
    assert isinstance(p_value, (int, float))
    assert 0 <= p_value <= 1


def test_walk_forward_outputs_contiguous_untouched_oos_rows() -> None:
    source = downloaded()
    samples = prepare_samples(source)
    experiment = config()
    run = run_symbol_walk_forward(samples, experiment)
    assert len(run.fold_ledger) >= 3
    assert np.all(np.diff(run.oos_indices) == 1)
    assert len(run.oos_indices) == len(run.selected_probabilities)
    assert set(run.selected_candidates) <= {
        "always_flat",
        "always_long",
        "logistic_core",
        "logistic_slow",
        "logistic_full",
    }
    report = build_backtest_report(
        config=experiment,
        downloads=(source,),
        runs=(run,),
        generated_at=NOW,
    )
    assert canonical_json_bytes(report)
    gates = report["gate_assessment"]
    assert isinstance(gates, dict)
    assert gates["global_promotion"] == "NO_PROMOTION"


class OnePageClient:
    def __init__(self, payload: list[list[object]]) -> None:
        self.payload = payload
        self.calls = 0

    def get_json(
        self, endpoint: RestEndpoint, parameters: dict[str, str | int] | None = None
    ) -> tuple[RawResponseEnvelope, object]:
        assert endpoint is RestEndpoint.SPOT_KLINES
        assert parameters is not None
        self.calls += 1
        raw = json.dumps(self.payload, separators=(",", ":")).encode()
        return (
            RawResponseEnvelope(
                endpoint=endpoint.value,
                request_url="https://data-api.binance.vision/api/v3/klines",
                request_hash="1" * 64,
                status_code=200,
                received_at=NOW,
                elapsed_ms=1,
                rate_limit_headers={},
                content_sha256=hashlib.sha256(raw).hexdigest(),
                content=raw,
            ),
            self.payload,
        )


class FailingClient:
    def get_json(
        self, endpoint: RestEndpoint, parameters: dict[str, str | int] | None = None
    ) -> tuple[RawResponseEnvelope, object]:
        raise AssertionError(f"cache unexpectedly called {endpoint} with {parameters}")


def test_public_download_cache_replays_only_after_hash_verification(tmp_path: Path) -> None:
    tiny_config = config(end_hours=4)
    client = OnePageClient([raw_row(index, 100 + index) for index in range(4)])
    first = load_or_download_spot_klines(
        config=tiny_config,
        symbol="BTCUSDT",
        raw_root=tmp_path,
        client=client,
    )
    assert client.calls == 1
    second = load_or_download_spot_klines(
        config=tiny_config,
        symbol="BTCUSDT",
        raw_root=tmp_path,
        client=FailingClient(),
    )
    assert first.rows == second.rows
    assert first.source_manifest == second.source_manifest
    page = first.cache_directory / "page-0000.json"
    page.write_bytes(b"[]")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_or_download_spot_klines(
            config=tiny_config,
            symbol="BTCUSDT",
            raw_root=tmp_path,
            client=FailingClient(),
        )
