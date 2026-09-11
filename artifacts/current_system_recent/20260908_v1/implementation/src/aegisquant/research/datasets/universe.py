"""Point-in-time instrument universe without listing or delisting survivorship bias."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime, assert_point_in_time


class UniverseMembership(DomainModel):
    membership_id: str
    instrument_id: str
    eligible: bool
    effective_from: UtcDateTime
    effective_to: UtcDateTime | None = None
    available_time: UtcDateTime
    revision_time: UtcDateTime | None = None
    revision: int
    reason_codes: tuple[str, ...]
    source_dataset_id: str

    @model_validator(mode="after")
    def validate_membership(self) -> UniverseMembership:
        if self.revision < 1:
            raise ValueError("universe membership revision starts at one")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("universe effective interval must be positive")
        if self.revision_time is not None and self.revision_time < self.available_time:
            raise ValueError("universe revision cannot predate initial availability")
        expected = canonical_sha256(
            {
                "instrument_id": self.instrument_id,
                "eligible": self.eligible,
                "effective_from": self.effective_from.isoformat(),
                "effective_to": self.effective_to.isoformat() if self.effective_to else None,
                "available_time": self.available_time.isoformat(),
                "revision_time": self.revision_time.isoformat() if self.revision_time else None,
                "revision": self.revision,
                "reason_codes": list(self.reason_codes),
                "source_dataset_id": self.source_dataset_id,
            }
        )
        if self.membership_id != expected:
            raise ValueError("membership_id must equal canonical membership hash")
        return self


class UniverseSnapshot(DomainModel):
    universe_snapshot_id: str
    as_of_time: UtcDateTime
    instrument_ids: tuple[str, ...]
    membership_ids: tuple[str, ...]
    source_dataset_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> UniverseSnapshot:
        if self.instrument_ids != tuple(sorted(self.instrument_ids)):
            raise ValueError("universe instruments must be sorted")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("universe instruments must be unique")
        expected = canonical_sha256(
            {
                "as_of_time": self.as_of_time.isoformat(),
                "instrument_ids": list(self.instrument_ids),
                "membership_ids": list(self.membership_ids),
                "source_dataset_ids": list(self.source_dataset_ids),
            }
        )
        if self.universe_snapshot_id != expected:
            raise ValueError("universe snapshot id must equal canonical content hash")
        return self


def membership_id(
    *,
    instrument_id: str,
    eligible: bool,
    effective_from: UtcDateTime,
    effective_to: UtcDateTime | None,
    available_time: UtcDateTime,
    revision_time: UtcDateTime | None,
    revision: int,
    reason_codes: tuple[str, ...],
    source_dataset_id: str,
) -> str:
    return canonical_sha256(
        {
            "instrument_id": instrument_id,
            "eligible": eligible,
            "effective_from": effective_from.isoformat(),
            "effective_to": effective_to.isoformat() if effective_to else None,
            "available_time": available_time.isoformat(),
            "revision_time": revision_time.isoformat() if revision_time else None,
            "revision": revision,
            "reason_codes": list(reason_codes),
            "source_dataset_id": source_dataset_id,
        }
    )


class PointInTimeUniverse:
    def __init__(self, memberships: Iterable[UniverseMembership]) -> None:
        values = tuple(memberships)
        if len({item.membership_id for item in values}) != len(values):
            raise ValueError("universe membership ids must be unique")
        self._memberships = values

    def snapshot(self, *, as_of_time: UtcDateTime) -> UniverseSnapshot:
        candidates: dict[str, list[UniverseMembership]] = {}
        for membership in self._memberships:
            if membership.available_time > as_of_time:
                continue
            if membership.revision_time is not None and membership.revision_time > as_of_time:
                continue
            if membership.effective_from > as_of_time:
                continue
            assert_point_in_time(available_time=membership.available_time, decision_time=as_of_time)
            candidates.setdefault(membership.instrument_id, []).append(membership)

        selected: list[UniverseMembership] = []
        for instrument_id in sorted(candidates):
            membership = max(
                candidates[instrument_id],
                key=lambda item: (
                    item.revision,
                    item.revision_time or item.available_time,
                    item.available_time,
                ),
            )
            if not membership.eligible:
                continue
            if membership.effective_to is not None and as_of_time >= membership.effective_to:
                continue
            selected.append(membership)

        payload = {
            "as_of_time": as_of_time.isoformat(),
            "instrument_ids": [item.instrument_id for item in selected],
            "membership_ids": sorted(item.membership_id for item in selected),
            "source_dataset_ids": sorted({item.source_dataset_id for item in selected}),
        }
        return UniverseSnapshot(
            universe_snapshot_id=canonical_sha256(payload),
            as_of_time=as_of_time,
            instrument_ids=tuple(payload["instrument_ids"]),
            membership_ids=tuple(payload["membership_ids"]),
            source_dataset_ids=tuple(payload["source_dataset_ids"]),
        )
