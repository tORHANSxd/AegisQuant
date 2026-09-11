"""Entry-point boundaries: protected data, immutable slots and actual PIT eligibility."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from aegisquant.research.datasets.pit_universe import LiquidityObservation, eligible_universe_at
from aegisquant.research.datasets.universe import (
    PointInTimeUniverse,
    UniverseMembership,
    membership_id,
)
from aegisquant.research.experiments.journal import ExperimentEventJournal, ExperimentEventType
from aegisquant.research.validation.cat_replay import load_completed_bars
from aegisquant.research.validation.experiment_registry import (
    checked_development_path,
    registered_run,
    require_promotion_evidence,
)


def test_development_guard_rejects_holdout_before_any_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    protected = tmp_path / "holdout"
    secret = protected / "prices.csv"
    opened: list[Path] = []

    def forbidden_open(path: Path, *args: object, **kwargs: object):
        opened.append(path)
        raise AssertionError("protected loader was reached")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(PermissionError, match="HOLDOUT-PATH"):
        checked_development_path(
            tmp_path,
            secret,
            allowed_sources={"holdout/prices.csv": "a" * 64},
            protected_roots=[protected],
        )
    assert not opened


def test_unknown_and_changed_development_bytes_fail_closed(tmp_path: Path):
    source = tmp_path / "known.csv"
    source.write_bytes(b"original")
    allowed = {"known.csv": hashlib.sha256(b"original").hexdigest()}
    assert (
        checked_development_path(tmp_path, source, allowed_sources=allowed, protected_roots=[])
        == source
    )
    with pytest.raises(PermissionError, match="NOT-REGISTERED"):
        checked_development_path(
            tmp_path, tmp_path / "other.csv", allowed_sources=allowed, protected_roots=[]
        )
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="HASH-MISMATCH"):
        checked_development_path(tmp_path, source, allowed_sources=allowed, protected_roots=[])


def test_failed_experiment_remains_consumed_and_unregistered_run_cannot_start(tmp_path: Path):
    with (
        pytest.raises(RuntimeError, match="simulation failed"),
        registered_run(tmp_path, "one", planned_run_ids=["one"], bindings={}),
    ):
        raise RuntimeError("simulation failed")
    events = ExperimentEventJournal(tmp_path / "experiment_events.jsonl").entries()
    assert [e.event.event_type for e in events] == [
        ExperimentEventType.STARTED,
        ExperimentEventType.ERROR,
    ]
    with (
        pytest.raises(FileExistsError),
        registered_run(tmp_path, "one", planned_run_ids=["one"], bindings={}),
    ):
        pytest.fail("a failed slot was rerun")
    with (
        pytest.raises(PermissionError),
        registered_run(tmp_path, "two", planned_run_ids=["one"], bindings={}),
    ):
        pytest.fail("an unregistered slot ran")
    assert len(ExperimentEventJournal(tmp_path / "experiment_events.jsonl").entries()) == 2


@pytest.mark.parametrize(
    "pit,execution,months", [(False, True, 12), (True, False, 12), (True, True, 11)]
)
def test_missing_promotion_evidence_never_admits(pit: bool, execution: bool, months: int):
    with pytest.raises(PermissionError, match="INSUFFICIENT"):
        require_promotion_evidence(
            point_in_time_universe=pit, verified_execution=execution, unused_holdout_months=months
        )


def test_point_in_time_listing_delisting_liquidity_and_future_revision():
    time = datetime(2024, 6, 1, tzinfo=UTC)

    def member(
        symbol: str,
        effective: datetime,
        known: datetime,
        *,
        eligible: bool = True,
        revision: int = 1,
    ):
        fields: dict[str, Any] = dict(
            instrument_id=symbol,
            eligible=eligible,
            effective_from=effective,
            effective_to=None,
            available_time=known,
            revision_time=None,
            revision=revision,
            reason_codes=("LISTING" if eligible else "DELISTING",),
            source_dataset_id="fixture-only",
        )
        return UniverseMembership(membership_id=membership_id(**fields), **fields)

    observations = [
        LiquidityObservation(
            instrument_id=s,
            window_start=time - timedelta(days=30),
            window_end=time,
            available_time=time,
            complete_history_4h_bars=bars,
            trailing_quote_volume=Decimal(volume),
            source_sha256="a" * 64,
        )
        for s, bars, volume in (
            ("OLD", 240, "1000"),
            ("NEW", 239, "1000"),
            ("DRY", 300, "999"),
            ("DELISTED", 400, "2000"),
        )
    ]
    rows = [
        member(s, time - timedelta(days=50), time - timedelta(days=50))
        for s in ("OLD", "NEW", "DRY", "DELISTED", "MISSING")
    ]
    rows += [
        member("DELISTED", time, time, eligible=False, revision=2),
        member("FUTURE", time + timedelta(days=1), time),
    ]
    rows += [member("UNKNOWN", time - timedelta(days=1), time + timedelta(days=1))]
    rows += [
        member(
            "OLD", time - timedelta(days=10), time + timedelta(days=1), eligible=False, revision=2
        )
    ]
    universe = PointInTimeUniverse(rows)
    _, eligible = eligible_universe_at(
        universe, observations, decision_time=time, minimum_quote_volume=Decimal("1000")
    )
    assert eligible == ("OLD",)
    _, future = eligible_universe_at(
        universe,
        observations,
        decision_time=time + timedelta(days=1),
        minimum_quote_volume=Decimal("1000"),
    )
    assert future == ()
    _, expired = eligible_universe_at(
        universe,
        observations,
        decision_time=time + timedelta(hours=5),
        minimum_quote_volume=Decimal("1000"),
    )
    assert expired == ()


@pytest.mark.parametrize("corruption", ["duplicate", "negative_volume", "bad_high", "nan"])
def test_strict_source_rejects_bad_hourly_rows_before_aggregation(tmp_path: Path, corruption: str):
    rows = [f"{i * 3600000},{(i + 1) * 3600000 - 1},100,101,99,100,1" for i in range(4)]
    if corruption == "duplicate":
        rows[1] = rows[0]
    else:
        parts = rows[1].split(",")
        index, value = {"negative_volume": (6, "-1"), "bad_high": (3, "99"), "nan": (2, "NaN")}[
            corruption
        ]
        parts[index] = value
        rows[1] = ",".join(parts)
    source = tmp_path / "source.csv"
    source.write_text(
        "open_time_ms,close_time_ms,open,high,low,close,base_volume\n" + "\n".join(rows),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source OHLCV"):
        load_completed_bars(source, strict_source=True)


def test_actual_research_reader_cannot_redirect_to_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from collections.abc import Callable

    from scripts import run_alpha_v5_research as runner

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    protected = tmp_path / "holdout"

    def redirected_inputs(symbol: str, *, source_guard: Callable[[Path], Path] | None = None):
        assert source_guard is not None
        source_guard(protected / "secret.csv")
        raise AssertionError("raw loader must never execute")

    monkeypatch.setattr(runner, "inputs", redirected_inputs)
    manifest = {
        "sources_by_symbol": {"BTCUSDT": "approved.csv"},
        "allowed_sources": {"approved.csv": "a" * 64},
        "protected_roots": [str(protected)],
    }
    with pytest.raises(PermissionError, match="HOLDOUT-PATH"):
        runner.guarded_inputs("BTCUSDT", manifest)


def test_development_partition_excludes_source_tail_before_parsing_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from scripts import run_alpha_v5_research as runner

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    source = tmp_path / "approved.csv"
    first = int(datetime(2025, 9, 30, 20, tzinfo=UTC).timestamp() * 1000)
    rows = [
        f"{first + i * 3600000},{first + (i + 1) * 3600000 - 1},{'100' if i < 4 else 'NaN'},101,99,100,1"
        for i in range(8)
    ]
    source.write_text(
        "open_time_ms,close_time_ms,open,high,low,close,base_volume\n" + "\n".join(rows),
        encoding="utf-8",
    )
    manifest = {
        "config": {
            "development": {
                "start": "2025-09-30T00:00:00Z",
                "end_exclusive": "2025-10-01T00:00:00Z",
            }
        },
        "sources_by_symbol": {"BTCUSDT": "approved.csv"},
        "allowed_sources": {"approved.csv": hashlib.sha256(source.read_bytes()).hexdigest()},
        "protected_roots": [str(tmp_path / "holdout")],
    }
    prepared = runner.prepare_development_inputs(tmp_path / "evidence", manifest)
    assert prepared["BTCUSDT"]["included_hourly_rows"] == 4
    assert prepared["BTCUSDT"]["excluded_outside_window_rows"] == 4
    assert prepared["BTCUSDT"]["complete_4h_bars"] == 1
    assert "NaN" not in (tmp_path / prepared["BTCUSDT"]["path"]).read_text(encoding="utf-8")
