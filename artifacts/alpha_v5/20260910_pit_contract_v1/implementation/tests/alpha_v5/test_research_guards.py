"""Entry-point boundaries: protected data, immutable slots and actual PIT eligibility."""

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from aegisquant.research.datasets.pit_universe import (
    LiquidityObservation,
    PITUniverseSnapshot,
    RuleProvenance,
    eligible_universe_at,
)
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


# B2 fixtures below contain metadata and Decimal quote evidence only, never prices/replays.
B2_TIME = datetime(2024, 6, 1, tzinfo=UTC)


def pit_member(
    uid: str = "asset-uid-1",
    *,
    kind: str = "TRADING_STARTED",
    event: str | None = None,
    effective: datetime = B2_TIME - timedelta(days=500),
    known: datetime = B2_TIME - timedelta(days=501),
    revision: int = 1,
    symbol: str = "TESTUSDT",
    **proof_fields: Any,
) -> UniverseMembership:
    from aegisquant.research.datasets.universe import MembershipEvidence

    evidence = MembershipEvidence.model_validate(
        {
            "event_id": event or uid + ":" + kind,
            "symbol": symbol,
            "venue": "SYNTHETIC",
            "event_kind": kind,
            "source_published_at": known,
            "first_observed_at": known,
            "availability_evidence_kind": "SYNTHETIC",
            "source_sha256": "a" * 64,
            **proof_fields,
        }
    )
    fields: dict[str, Any] = {
        "instrument_id": uid,
        "eligible": kind not in {"LISTED", "SUSPENDED", "DELISTED", "MIGRATED"},
        "effective_from": effective,
        "effective_to": None,
        "available_time": known,
        "revision_time": None,
        "revision": revision,
        "reason_codes": (kind,),
        "source_dataset_id": "B2_SYNTHETIC_ONLY",
        "evidence": evidence,
    }
    return UniverseMembership(membership_id=membership_id(**fields), **fields)


def pit_liquidity(
    uid: str = "asset-uid-1",
    *,
    count: int = 961,
    quote: str = "10",
    end: datetime = B2_TIME,
    known: datetime | None = None,
    gaps: tuple[int, ...] = (),
    method: str = "SYNTHETIC",
    revision: int = 1,
) -> LiquidityObservation:
    from aegisquant.data.hashing import canonical_sha256
    from aegisquant.research.datasets.pit_universe import ClosedLiquidityBar, LiquidityEvidence

    bars = tuple(
        ClosedLiquidityBar(
            close_time=end - timedelta(hours=4 * i),
            available_time=end - timedelta(hours=4 * i),
            quote_turnover=Decimal(quote),
            source_sha256="b" * 64,
        )
        for i in reversed(range(count))
        if i not in gaps
    )
    continuous = min((*gaps, count)) if gaps else count
    detail = LiquidityEvidence.model_validate(
        {
            "quote_method": method,
            "bars": bars,
            "detail_sha256": canonical_sha256([bar.model_dump(mode="json") for bar in bars]),
        }
    )
    return LiquidityObservation(
        instrument_id=uid,
        window_start=end - timedelta(days=30),
        window_end=end,
        available_time=known or end,
        complete_history_4h_bars=continuous,
        trailing_quote_volume=sum(
            (
                bar.quote_turnover
                for bar in bars
                if end - timedelta(days=30) < bar.close_time <= end
            ),
            Decimal(0),
        ),
        source_sha256="c" * 64,
        evidence=detail,
        revision=revision,
    )


def pit_rule(
    uid: str = "asset-uid-1",
    *,
    known: datetime = B2_TIME - timedelta(days=501),
    effective: datetime = B2_TIME - timedelta(days=500),
    end: datetime | None = None,
    kind: str = "SYNTHETIC",
    trading: bool = True,
    revision: int = 1,
) -> RuleProvenance:
    from aegisquant.backtest.models import HistoricalInstrumentRule
    from aegisquant.data.hashing import canonical_sha256
    from aegisquant.domain.identifiers import InstrumentId, InstrumentRuleId, VenueId
    from aegisquant.research.datasets.pit_universe import RuleProvenance

    rule = HistoricalInstrumentRule(
        instrument_rule_id=InstrumentRuleId(uid + ":rule"),
        instrument_id=InstrumentId(uid),
        venue_id=VenueId("SYNTHETIC"),
        version="B2_SYNTHETIC_ONLY",
        effective_from=effective,
        effective_to=end,
        tick_size=Decimal(".01"),
        step_size=Decimal(".01"),
        minimum_quantity=Decimal(".01"),
        maximum_quantity=Decimal("1000"),
        minimum_notional=Decimal("10"),
        trading_enabled=trading,
        source="B2_SYNTHETIC_ONLY",
    )
    filters = {
        "PRICE_FILTER": {"tickSize": ".01"},
        "LOT_SIZE": {"minQty": ".01", "maxQty": "1000", "stepSize": ".01"},
        "MARKET_LOT_SIZE": {"minQty": ".01", "maxQty": "1000", "stepSize": ".01"},
        "NOTIONAL": {"minNotional": "10", "applyMinToMarket": True, "avgPriceMins": 0},
        "ORDER_PERMISSIONS": {"orderTypes": ["MARKET", "LIMIT"]},
    }
    return RuleProvenance.model_validate(
        {
            "record_id": uid + ":rule",
            "revision": revision,
            "available_time": known,
            "verified_kind": kind,
            "rule": rule,
            "source_sha256": "d" * 64,
            "filter_payload_json": json.dumps(filters),
            "payload_sha256": canonical_sha256(
                {"rule": rule.model_dump(mode="json"), "filters": filters}
            ),
        }
    )


def pit_snapshot(
    *,
    members: Iterable[UniverseMembership] | None = None,
    liquidity: Iterable[LiquidityObservation] | None = None,
    rules: Iterable[RuleProvenance] | None = None,
    **overrides: Any,
) -> PITUniverseSnapshot:
    from aegisquant.research.datasets.pit_universe import audit_universe_at

    arguments: dict[str, Any] = {
        "rules": [pit_rule()] if rules is None else rules,
        "decision_time": B2_TIME,
        "minimum_quote_volume": Decimal("1000"),
        "warmup_requirements": {"slow_trend_160d": 961, "return_240": 241, "vol_42_returns": 43},
        "allow_synthetic": True,
        **overrides,
    }
    return audit_universe_at(
        PointInTimeUniverse([pit_member()] if members is None else members),
        [pit_liquidity()] if liquidity is None else liquidity,
        **arguments,
    )


def test_b2_event_lifecycle_and_relisting_use_instrument_uid():
    rows = [
        pit_member(
            kind="LISTED",
            effective=B2_TIME - timedelta(days=510),
            known=B2_TIME - timedelta(days=511),
        ),
        pit_member(),
        pit_member(
            kind="SUSPENDED",
            effective=B2_TIME - timedelta(days=2),
            known=B2_TIME - timedelta(days=3),
        ),
        pit_member(
            kind="RESUMED",
            effective=B2_TIME - timedelta(days=1),
            known=B2_TIME - timedelta(days=1, hours=4),
        ),
        pit_member(kind="DELISTED", effective=B2_TIME, known=B2_TIME - timedelta(days=2)),
        pit_member(
            "asset-uid-2",
            kind="RELISTED",
            effective=B2_TIME + timedelta(days=1),
            known=B2_TIME - timedelta(days=1),
        ),
    ]
    universe = PointInTimeUniverse(rows)
    for offset, expected in (
        (-512, ()),
        (-502, ()),
        (-499, ("asset-uid-1",)),
        (-1.5, ()),
        (-0.5, ("asset-uid-1",)),
        (0.5, ()),
        (2, ("asset-uid-2",)),
    ):
        assert (
            universe.snapshot(as_of_time=B2_TIME + timedelta(days=offset)).instrument_ids
            == expected
        )
    held = pit_snapshot(members=rows, held_instrument_ids=("asset-uid-1",))
    assert held.held_instrument_ids == ("asset-uid-1",) and held.eligible_instrument_ids == ()
    assert held.known_future_event_ids


def test_b2_archived_publication_and_late_receipt_are_different_clocks():
    archived = pit_member(
        availability_evidence_kind="ARCHIVED_PUBLICATION",
        first_observed_at=B2_TIME + timedelta(days=100),
    )
    assert PointInTimeUniverse([archived]).snapshot(as_of_time=B2_TIME).instrument_ids == (
        "asset-uid-1",
    )
    with pytest.raises(ValueError, match="receipt evidence"):
        pit_member(
            availability_evidence_kind="OBSERVED_AT_RECEIPT",
            first_observed_at=B2_TIME + timedelta(days=100),
        )
    with pytest.raises(ValueError, match="publication evidence"):
        pit_member(availability_evidence_kind="ARCHIVED_PUBLICATION", source_published_at=None)


def test_b2_event_revision_changes_effective_time_without_applying_early():
    original = pit_member(
        kind="DELISTED",
        event="scheduled-exit",
        effective=B2_TIME,
        known=B2_TIME - timedelta(days=2),
    )
    revised = pit_member(
        kind="DELISTED",
        event="scheduled-exit",
        effective=B2_TIME + timedelta(days=2),
        known=B2_TIME - timedelta(days=1),
        revision=2,
    )
    universe = PointInTimeUniverse([pit_member(), original, revised])
    assert universe.snapshot(as_of_time=B2_TIME).instrument_ids == ("asset-uid-1",)
    assert universe.snapshot(as_of_time=B2_TIME + timedelta(days=2)).instrument_ids == ()


def test_b2_membership_revision_conflict_fails_only_when_known():
    first, conflict = pit_member(), pit_member(source_sha256="f" * 64)
    for rows in ([first, conflict], [conflict, first]):
        with pytest.raises(ValueError, match="CONFLICTING-MEMBERSHIP-REVISION"):
            PointInTimeUniverse(rows).snapshot(as_of_time=B2_TIME)
    future = [
        pit_member("later", known=B2_TIME + timedelta(days=1)),
        pit_member("later", known=B2_TIME + timedelta(days=2)),
    ]
    assert PointInTimeUniverse([first, *future]).snapshot(as_of_time=B2_TIME).instrument_ids == (
        "asset-uid-1",
    )
    with pytest.raises(ValueError, match="CONFLICTING-MEMBERSHIP-REVISION"):
        PointInTimeUniverse(future).snapshot(as_of_time=B2_TIME + timedelta(days=3))


@pytest.mark.parametrize(
    "count,gaps,expected,reason",
    [
        (961, (), 961, None),
        (240, (), 240, "CONTIGUOUS_WARMUP_INCOMPLETE"),
        (961, (200,), 200, "CONTIGUOUS_WARMUP_INCOMPLETE"),
        (961, (4,), 4, "LIQUIDITY_WINDOW_GAP"),
    ],
)
def test_b2_contiguous_warmup_and_exact_thirty_day_window(
    count: int, gaps: tuple[int, ...], expected: int, reason: str | None
):
    result = pit_snapshot(liquidity=[pit_liquidity(count=count, gaps=gaps)])
    decision = result.decisions[0]
    assert decision.contiguous_4h_bars == expected and decision.required_history_bars == 961
    if reason:
        assert result.eligible_instrument_ids == () and reason in decision.reason_codes
    else:
        assert result.eligible_instrument_ids == ("asset-uid-1",)
        assert decision.liquidity_window_bars == 180 and decision.trailing_quote_volume == Decimal(
            "1800"
        )
    # Legacy count-only eligibility stays explicitly separate from the strict contract.
    if count == 240:
        assert eligible_universe_at(
            PointInTimeUniverse([pit_member()]),
            [pit_liquidity(count=count)],
            decision_time=B2_TIME,
            minimum_quote_volume=Decimal("1000"),
        )[1] == ("asset-uid-1",)


def test_b2_gap_recovery_and_resume_require_all_dependency_windows():
    assert pit_snapshot(
        liquidity=[pit_liquidity(count=962, gaps=(961,))]
    ).eligible_instrument_ids == ("asset-uid-1",)
    resumed = pit_member(
        kind="RESUMED", effective=B2_TIME - timedelta(days=2), known=B2_TIME - timedelta(days=2)
    )
    decision = pit_snapshot(members=[pit_member(), resumed]).decisions[0]
    assert decision.contiguous_4h_bars == 961 and decision.tradable_history_4h_bars == 12
    assert "CONTIGUOUS_WARMUP_INCOMPLETE" in decision.reason_codes


@pytest.mark.parametrize("case", ["zero", "missing", "proxy", "future", "stale", "no_detail"])
def test_b2_liquidity_unavailable_or_proxy_never_opens_new_risk(case: str):
    rows = (
        []
        if case == "missing"
        else [
            pit_liquidity(
                quote="0" if case == "zero" else "10",
                method="BASE_VOLUME_TIMES_CLOSE_PROXY" if case == "proxy" else "SYNTHETIC",
                known=B2_TIME + timedelta(hours=1) if case == "future" else None,
                end=B2_TIME - timedelta(hours=8) if case == "stale" else B2_TIME,
            )
        ]
    )
    if case == "no_detail":
        rows = [rows[0].model_copy(update={"evidence": None})]
    assert pit_snapshot(liquidity=rows).eligible_instrument_ids == ()


def test_b2_liquidity_hash_amount_window_and_history_corruptions_rejected():
    row = pit_liquidity()
    for update, error in (
        ({"trailing_quote_volume": Decimal("1801")}, "QUOTE-TURNOVER"),
        ({"window_start": row.window_start - timedelta(hours=4)}, "30-day"),
        ({"available_time": row.window_end - timedelta(seconds=1)}, "window ends"),
    ):
        with pytest.raises(ValueError, match=error):
            LiquidityObservation.model_validate({**dict(row), **update})
    with pytest.raises(ValueError, match="CONTIGUOUS-HISTORY-COUNT"):
        pit_snapshot(liquidity=[row.model_copy(update={"complete_history_4h_bars": 9999})])
    with pytest.raises(ValueError, match="CONFLICTING-LIQUIDITY-REVISION"):
        pit_snapshot(liquidity=[row, pit_liquidity(quote="11")])
    for value in ("-1", "NaN", "Infinity"):
        with pytest.raises(ValueError):
            pit_liquidity(quote=value)


@pytest.mark.parametrize("case", ["missing", "future", "expired", "proxy", "disabled"])
def test_b2_rule_provenance_is_required_for_new_risk(case: str):
    rows = (
        []
        if case == "missing"
        else [
            pit_rule(
                known=B2_TIME + timedelta(days=1)
                if case == "future"
                else B2_TIME - timedelta(days=501),
                end=B2_TIME if case == "expired" else None,
                kind="PROXY" if case == "proxy" else "SYNTHETIC",
                trading=case != "disabled",
            )
        ]
    )
    result = pit_snapshot(rules=rows, held_instrument_ids=("asset-uid-1", "unmapped-held-uid"))
    assert result.eligible_instrument_ids == ()
    assert result.held_instrument_ids == ("asset-uid-1", "unmapped-held-uid")
    assert result.scope == "NEW_RISK_ONLY_NO_POSITION_MUTATION"


def test_b2_synthetic_sources_never_become_historical_evidence_by_default():
    result = pit_snapshot(allow_synthetic=False)
    assert result.eligible_instrument_ids == ()
    assert "MEMBERSHIP_EVIDENCE_UNVERIFIED" in result.decisions[0].reason_codes
    assert "RULES_UNVERIFIED" in result.decisions[0].reason_codes
    with pytest.raises(ValueError, match="UNREGISTERED-ELIGIBILITY-LIMITS"):
        pit_snapshot(warmup_requirements={})
    with pytest.raises(ValueError, match="UNREGISTERED-ELIGIBILITY-LIMITS"):
        pit_snapshot(minimum_quote_volume=Decimal(0))


def test_b2_rule_conflict_and_simultaneous_symbol_reuse_are_rejected():
    with pytest.raises(ValueError, match="CONFLICTING-RULE-REVISION"):
        pit_snapshot(rules=[pit_rule(), pit_rule(trading=False)])
    with pytest.raises(ValueError, match="OVERLAPPING-SYMBOL-INCARNATIONS"):
        pit_snapshot(members=[pit_member(), pit_member("asset-uid-2")])


def test_b2_bound_inputs_reject_changed_and_deleted_exited_asset_bytes(tmp_path: Path):
    from aegisquant.research.validation.evidence_contract import EvidenceReader
    from aegisquant.research.validation.pit_contract import read_bound_input

    source = tmp_path / "data/research/pit/universe_events.json"
    source.parent.mkdir(parents=True)
    original = {
        "records": [
            pit_member().model_dump(mode="json"),
            pit_member("old-uid", symbol="OLDUSDT", kind="DELISTED").model_dump(mode="json"),
        ]
    }
    source.write_text(json.dumps(original), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    reader = EvidenceReader(tmp_path)
    assert (
        read_bound_input(
            reader, "data/research/pit", "data/research/pit/universe_events.json", digest
        )
        == source
    )
    original["records"].pop()
    source.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ValueError, match="INPUT-HASH-CONFLICT"):
        read_bound_input(
            reader, "data/research/pit", "data/research/pit/universe_events.json", digest
        )


@pytest.mark.parametrize("kind", ["holdout", "symlink", "junction", "credential", "outside"])
def test_b2_pit_path_guard_rejects_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
):
    from aegisquant.research.validation.evidence_contract import EvidenceReader
    from aegisquant.research.validation.pit_contract import read_bound_input

    relative = {
        "holdout": "data/research/pit/holdout/secret.json",
        "credential": "data/research/pit/.env",
        "outside": "elsewhere/metadata.json",
    }.get(kind, "data/research/pit/linked.json")

    def is_fixture_link(path: Path) -> bool:
        return path.name == "linked.json"

    if kind in {"symlink", "junction"}:
        monkeypatch.setattr(
            Path,
            "is_symlink" if kind == "symlink" else "is_junction",
            is_fixture_link,
        )
    opened: list[Path] = []

    def forbidden_open(path: Path, *args: object, **kwargs: object):
        opened.append(path)
        raise AssertionError("PIT guard reached a forbidden input")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises((PermissionError, ValueError)):
        read_bound_input(EvidenceReader(tmp_path), "data/research/pit", relative, "a" * 64)
    assert not opened


def pit_job_fixture(tmp_path: Path, project_root: Path):
    """All saved evidence/receipts here are synthetic; never copied into real reports."""
    import yaml

    from aegisquant.data.hashing import sha256_file
    from aegisquant.research.validation import pit_contract as contract

    root, stage = tmp_path / "synthetic-repo", tmp_path / "synthetic-stage"
    root.mkdir()
    stage.mkdir()
    config = yaml.safe_load(
        (project_root / "configs/research/alpha_v5_pit_contract.yaml").read_text(encoding="utf-8")
    )

    def save(relative: str, content: str):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    for name in contract.B2_FILES:
        save(name, "SYNTHETIC TASK FILE ONLY\n")
    safety = {"production_policy": "CASH", **dict.fromkeys(contract.LOCKS, False)}
    config["r5_manifest_sha256"] = sha256_file(
        save(config["r5_frozen_root"] + "/audit_manifest.json", json.dumps({"config": safety}))
    )
    config["b0_manifest_sha256"] = sha256_file(
        save(
            config["b0_frozen_root"] + "/OUTPUT_MANIFEST.json", json.dumps({"SYNTHETIC_ONLY": True})
        )
    )
    save("configs/research/aegis_alpha_v5.yaml", yaml.safe_dump(safety))
    save(
        "src/aegisquant/bootstrap/live_lock.py",
        "LIVE_TRADING: bool = False\nORDER_SUBMISSION_ENABLED: bool = False\nLIVE_ADAPTERS: tuple = ()\n",
    )
    save("configs/research/alpha_v5_pit_contract.yaml", yaml.safe_dump(config))
    files = {
        path.relative_to(root).as_posix(): {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in root.rglob("*")
        if path.is_file()
    }
    baseline = {
        "head": contract.BASE,
        "branch": "main",
        "root": str(root),
        "allowed_modifications": list(contract.MODIFIED_FILES),
        "files": files,
    }
    (stage / "baseline_workspace.json").write_text(json.dumps(baseline), encoding="utf-8")
    for name in contract.MODIFIED_FILES:
        target = stage / "before" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / name).read_bytes())
    for name in ("workspace_before.patch", "version_graph.txt", "test_commands_and_results.txt"):
        (stage / name).write_text("SYNTHETIC FIXTURE NOT AN ACTUAL RUN\n", encoding="utf-8")
    hashes = {name: sha256_file(root / name) for name in contract.B2_FILES}
    receipts = [
        {
            "check": check,
            "command": ["SYNTHETIC_FIXTURE_ONLY"],
            "exit_code": 0,
            "source_sha256": hashes,
        }
        for check in ("pytest", "ruff", "format", "pyright")
    ]
    (stage / "validation_records.json").write_text(json.dumps(receipts), encoding="utf-8")
    (stage / "pytest_results.xml").write_text(
        '<testsuite name="SYNTHETIC_RECEIPT_ONLY">'
        + "".join(f'<testcase name="test_b2_future_fixture_{number}"/>' for number in range(9))
        + "</testsuite>",
        encoding="utf-8",
    )
    return root, stage, config


def test_b2_actual_cli_missing_data_fails_closed_without_old_pipeline(
    tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
):
    import sys
    from unittest.mock import Mock

    from aegisquant.research.validation.evidence_contract import load_evidence_manifest
    from aegisquant.research.validation.pit_contract import run_pit_quality_job
    from scripts import run_alpha_v5_research as runner

    root, stage, config = pit_job_fixture(tmp_path, project_root)
    poison = Mock(side_effect=AssertionError("B2 invoked the old market/replay pipeline"))
    for name in (
        "inputs",
        "load_completed_bars",
        "replay_cat",
        "reproduce",
        "run",
        "run_one",
        "preregister",
    ):
        monkeypatch.setattr(runner, name, poison)
    monkeypatch.setattr(runner, "ROOT", root)

    def synthetic_git(_root: Path, *args: str) -> str:
        return "main" if args[0] == "branch" else "d8c6d4013097f6323ab8b7a424c860ba0ccbd62b"

    monkeypatch.setattr(runner, "git", synthetic_git)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit",
            "pit-audit",
            "--config",
            "configs/research/alpha_v5_pit_contract.yaml",
            "--preflight-dir",
            str(stage),
        ],
    )
    with pytest.raises(SystemExit) as ended:
        runner.main()
    assert ended.value.code == 2
    poison.assert_not_called()
    output = root / config["output"]
    assert load_evidence_manifest(output, "OUTPUT_MANIFEST.json")["status"] == "VERIFIED"
    assert json.loads((output / "universe_events.json").read_text())["records"] is None
    status = json.loads((output / "safety_and_budget_audit.json").read_text())
    assert status["strict_data_quality"] == "FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE"
    assert all(value == 0 for key, value in status["actual"].items() if key != "data_quality_jobs")
    assert status["actual"]["data_quality_jobs"] == 1
    assert (
        ExperimentEventJournal(output / "experiment_events.jsonl").entries()[-1].event.event_type
        == ExperimentEventType.ERROR
    )
    with pytest.raises(FileExistsError):
        run_pit_quality_job(root, config, stage, {"branch": "main", "head": config["source_head"]})


@pytest.mark.parametrize("mutation", ["fit", "live", "synthetic", "warmup", "scope"])
def test_b2_config_rejects_scope_or_evidence_downgrade(project_root: Path, mutation: str):
    import yaml

    from aegisquant.research.validation.pit_contract import validate_pit_config

    config = yaml.safe_load(
        (project_root / "configs/research/alpha_v5_pit_contract.yaml").read_text(encoding="utf-8")
    )
    if mutation == "fit":
        config["budgets"]["real_return_model_fits"] = 1
    elif mutation == "live":
        config["live_trading"] = True
    elif mutation == "synthetic":
        config["allow_synthetic_historical_evidence"] = True
    elif mutation == "warmup":
        config["warmup_requirements"]["trend_160d"] = 240
    else:
        config["mode"] = "REPLAY"
    with pytest.raises(ValueError, match="AQ-PIT-"):
        validate_pit_config(config)


def test_b2_complete_bound_table_fixture_and_deleted_asset_census_guard(
    tmp_path: Path, project_root: Path
):
    """The archive labels simulate a source contract, not real historical evidence."""
    import yaml

    from aegisquant.data.hashing import canonical_sha256, sha256_file
    from aegisquant.research.datasets.pit_universe import LiquidityEvidence
    from aegisquant.research.validation.evidence_contract import EvidenceReader
    from aegisquant.research.validation.pit_contract import validate_pit_tables

    config = yaml.safe_load(
        (project_root / "configs/research/alpha_v5_pit_contract.yaml").read_text(encoding="utf-8")
    )
    directory = tmp_path / "data/research/pit"
    directory.mkdir(parents=True)
    archive = directory / "synthetic_archive.txt"
    archive.write_text("SYNTHETIC ARCHIVE FIXTURE ONLY; NO REAL MARKET DATA", encoding="utf-8")
    source_hash = sha256_file(archive)
    members = [
        pit_member(availability_evidence_kind="ARCHIVED_PUBLICATION", source_sha256=source_hash),
        pit_member(
            "gone-uid",
            symbol="GONEUSDT",
            kind="DELISTED",
            effective=B2_TIME - timedelta(days=1),
            known=B2_TIME - timedelta(days=2),
            availability_evidence_kind="ARCHIVED_PUBLICATION",
            source_sha256=source_hash,
        ),
    ]
    liquidity = pit_liquidity(method="EXCHANGE_QUOTE_TURNOVER")
    assert liquidity.evidence is not None
    bars = tuple(
        bar.model_copy(update={"source_sha256": source_hash}) for bar in liquidity.evidence.bars
    )
    detail = LiquidityEvidence(
        quote_method="EXCHANGE_QUOTE_TURNOVER",
        bars=bars,
        detail_sha256=canonical_sha256([bar.model_dump(mode="json") for bar in bars]),
    )
    liquidity = liquidity.model_copy(update={"source_sha256": source_hash, "evidence": detail})
    rule = pit_rule(kind="ARCHIVED_EXCHANGE_RULE").model_copy(update={"source_sha256": source_hash})
    config["period_start"] = B2_TIME.isoformat()
    config["period_end_exclusive"] = (B2_TIME + timedelta(hours=4)).isoformat()
    config["minimum_trailing_30d_quote_volume"] = "1000"
    documents = {
        "universe_events": {"records": [row.model_dump(mode="json") for row in members]},
        "liquidity_windows": {"records": [liquidity.model_dump(mode="json")]},
        "rules_provenance": {"records": [rule.model_dump(mode="json")]},
        "coverage_manifest": {
            "schema_version": "pit-coverage-b2-v1",
            "classification": "PREVIOUSLY_USED_DEVELOPMENT_METADATA",
            "period_start": config["period_start"],
            "period_end_exclusive": config["period_end_exclusive"],
            "candidate_instrument_uids": ["asset-uid-1", "gone-uid"],
            "event_stream_complete": True,
            "includes_delisted_instruments": True,
            "source_files": {"data/research/pit/synthetic_archive.txt": source_hash},
        },
    }
    for name, document in documents.items():
        path = directory / (name + ".json")
        path.write_text(json.dumps(document), encoding="utf-8")
        config["inputs"][name] = {
            "path": path.relative_to(tmp_path).as_posix(),
            "sha256": sha256_file(path),
        }
    products, gaps = validate_pit_tables(EvidenceReader(tmp_path), config)
    assert not gaps
    assert products["historical_coverage"]["candidate_count"] == 2
    assert products["historical_coverage"]["delisted_count"] == 1
    assert products["historical_coverage"]["unknown_exclusion_fraction"] == "0"
    assert products["historical_snapshots"][0]["eligible_instrument_ids"] == ["asset-uid-1"]
    path = directory / "universe_events.json"
    path.write_text(json.dumps({"records": [members[0].model_dump(mode="json")]}), encoding="utf-8")
    config["inputs"]["universe_events"]["sha256"] = sha256_file(path)
    with pytest.raises(ValueError, match="CANDIDATE-COVERAGE-CONFLICT"):
        validate_pit_tables(EvidenceReader(tmp_path), config)
