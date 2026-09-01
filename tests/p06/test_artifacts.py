"""Exact, deterministic and machine-readable P06 backtest artifact contract."""

import json
from decimal import Decimal
from pathlib import Path

from aegisquant.backtest.artifacts import (
    REQUIRED_BACKTEST_ARTIFACTS,
    write_backtest_artifacts,
)
from aegisquant.backtest.vector import buy_and_hold_benchmark
from aegisquant.data.manifest import inspect_parquet_file
from tests.p06.helpers import bars, engine, run_spec, spot_instrument


def test_backtest_writer_emits_exact_required_artifacts_and_stable_hashes(
    tmp_path: Path,
) -> None:
    values = bars()
    instrument = spot_instrument()
    result = engine().run(
        spec=run_spec(run_id="p06-artifact-golden"),
        instrument=instrument,
        market_events=values,
        orders=buy_and_hold_benchmark(bars=values, instrument=instrument, quantity=Decimal("1")),
    )

    first = write_backtest_artifacts(result, tmp_path / "first")
    second = write_backtest_artifacts(result, tmp_path / "second")

    assert {path.name for path in first.paths} == set(REQUIRED_BACKTEST_ARTIFACTS)
    assert first.sha256_by_name == second.sha256_by_name
    manifest = json.loads((tmp_path / "first/run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["live_trading_locked"] is True
    assert manifest["real_account_connected"] is False
    assert manifest["economic_event_hash"] == result.economic_event_hash
    assert set(manifest["artifact_sha256"]) == set(REQUIRED_BACKTEST_ARTIFACTS) - {
        "run_manifest.json"
    }
    assert inspect_parquet_file(
        root=tmp_path / "first", path=tmp_path / "first/orders.parquet"
    ).rows == len(result.orders)
    assert inspect_parquet_file(
        root=tmp_path / "first", path=tmp_path / "first/fills.parquet"
    ).rows == len(result.fills)
    assert inspect_parquet_file(
        root=tmp_path / "first", path=tmp_path / "first/ledger_entries.parquet"
    ).rows == len(result.ledger_records)
    assert "LIVE_TRADING locked: `true`" in (tmp_path / "first/validation_report.md").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "first/reproduction_command.txt").read_text(
        encoding="utf-8"
    ).strip() == result.spec.reproduction_command
