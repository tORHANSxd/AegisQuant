from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aegisquant.research.datasets import PointInTimeUniverse, UniverseMembership, membership_id

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)


def membership(
    instrument: str,
    *,
    eligible: bool,
    effective_from: datetime,
    available_time: datetime,
    revision: int = 1,
    revision_time: datetime | None = None,
    effective_to: datetime | None = None,
) -> UniverseMembership:
    identifier = membership_id(
        instrument_id=instrument,
        eligible=eligible,
        effective_from=effective_from,
        effective_to=effective_to,
        available_time=available_time,
        revision_time=revision_time,
        revision=revision,
        reason_codes=("volume-and-history",),
        source_dataset_id="universe-v1",
    )
    return UniverseMembership(
        membership_id=identifier,
        instrument_id=instrument,
        eligible=eligible,
        effective_from=effective_from,
        effective_to=effective_to,
        available_time=available_time,
        revision_time=revision_time,
        revision=revision,
        reason_codes=("volume-and-history",),
        source_dataset_id="universe-v1",
    )


def test_point_in_time_universe_prevents_listing_delisting_and_revision_backfill() -> None:
    btc_v1 = membership(
        "BTCUSDT", eligible=True, effective_from=NOW, available_time=NOW, revision=1
    )
    btc_delisted = membership(
        "BTCUSDT",
        eligible=False,
        effective_from=NOW,
        available_time=NOW,
        revision=2,
        revision_time=NOW + timedelta(days=2),
    )
    future_listing = membership(
        "NEWUSDT",
        eligible=True,
        effective_from=NOW + timedelta(days=1),
        available_time=NOW + timedelta(days=1, minutes=5),
    )
    expired = membership(
        "OLDUSDT",
        eligible=True,
        effective_from=NOW - timedelta(days=2),
        effective_to=NOW + timedelta(hours=2),
        available_time=NOW - timedelta(days=2),
    )
    universe = PointInTimeUniverse((btc_v1, btc_delisted, future_listing, expired))

    early = universe.snapshot(as_of_time=NOW + timedelta(hours=1))
    assert early.instrument_ids == ("BTCUSDT", "OLDUSDT")
    assert btc_delisted.membership_id not in early.membership_ids

    after_expiry = universe.snapshot(as_of_time=NOW + timedelta(hours=3))
    assert after_expiry.instrument_ids == ("BTCUSDT",)

    after_revision = universe.snapshot(as_of_time=NOW + timedelta(days=2))
    assert after_revision.instrument_ids == ("NEWUSDT",)


def test_universe_snapshot_is_content_addressed_and_reproducible() -> None:
    item = membership("BTCUSDT", eligible=True, effective_from=NOW, available_time=NOW)
    universe = PointInTimeUniverse((item,))
    assert universe.snapshot(as_of_time=NOW) == universe.snapshot(as_of_time=NOW)
    assert len(universe.snapshot(as_of_time=NOW).universe_snapshot_id) == 64
