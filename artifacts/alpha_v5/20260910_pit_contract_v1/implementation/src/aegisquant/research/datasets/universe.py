"""Point-in-time instrument universe without listing or delisting survivorship bias."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime, assert_point_in_time


class MembershipEvidence(DomainModel):
    """A business event identity is stable across revisions; a symbol is not a UID."""

    event_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    venue: str = Field(min_length=1)
    event_kind: Literal[
        "LISTED",
        "TRADING_STARTED",
        "SUSPENDED",
        "RESUMED",
        "DELISTED",
        "MIGRATED",
        "RELISTED",
        "SYMBOL_CHANGED",
        "QUOTE_CHANGED",
    ]
    source_published_at: UtcDateTime | None
    first_observed_at: UtcDateTime
    availability_evidence_kind: Literal[
        "ARCHIVED_PUBLICATION", "OBSERVED_AT_RECEIPT", "UNKNOWN", "SYNTHETIC"
    ]
    source_sha256: str

    @model_validator(mode="after")
    def validate_evidence(self) -> MembershipEvidence:
        ensure_sha256(self.source_sha256, field_name="universe event source")
        if (
            self.source_published_at is not None
            and self.first_observed_at < self.source_published_at
        ):
            raise ValueError("PIT observation cannot predate source publication")
        if (
            self.availability_evidence_kind == "ARCHIVED_PUBLICATION"
            and self.source_published_at is None
        ):
            raise ValueError("archived availability requires publication evidence")
        return self


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
    evidence: MembershipEvidence | None = None

    @model_validator(mode="after")
    def validate_membership(self) -> UniverseMembership:
        if self.revision < 1:
            raise ValueError("universe membership revision starts at one")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("universe effective interval must be positive")
        if self.revision_time is not None and self.revision_time < self.available_time:
            raise ValueError("universe revision cannot predate initial availability")
        if (proof := self.evidence) is not None:
            known = self.revision_time or self.available_time
            if proof.source_published_at is not None and known < proof.source_published_at:
                raise ValueError("PIT availability cannot predate source publication")
            if (
                proof.availability_evidence_kind == "OBSERVED_AT_RECEIPT"
                and known < proof.first_observed_at
            ):
                raise ValueError("receipt evidence cannot backdate availability")
            if (
                proof.event_kind in {"LISTED", "SUSPENDED", "DELISTED", "MIGRATED"}
                and self.eligible
            ):
                raise ValueError("non-trading universe event cannot open new risk")
            if proof.event_kind in {"TRADING_STARTED", "RESUMED", "RELISTED"} and not self.eligible:
                raise ValueError("trading-start event must explicitly enable trading")
        expected = membership_id(
            instrument_id=self.instrument_id,
            eligible=self.eligible,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            available_time=self.available_time,
            revision_time=self.revision_time,
            revision=self.revision,
            reason_codes=self.reason_codes,
            source_dataset_id=self.source_dataset_id,
            evidence=self.evidence,
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
    evidence: MembershipEvidence | None = None,
) -> str:
    # Preserve every legacy v1 identity. Evidence changes only explicitly versioned rows.
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
            **({"evidence": evidence.model_dump(mode="json")} if evidence is not None else {}),
        }
    )


class PointInTimeUniverse:
    def __init__(self, memberships: Iterable[UniverseMembership]) -> None:
        values = tuple(memberships)
        if len({item.membership_id for item in values}) != len(values):
            raise ValueError("universe membership ids must be unique")
        self._memberships = values

    def known_events(self, *, as_of_time: UtcDateTime) -> tuple[UniverseMembership, ...]:
        """Resolve known revisions before effective-time selection."""
        revisions: dict[tuple[str, str, int], UniverseMembership] = {}
        for membership in self._memberships:
            if membership.available_time > as_of_time:
                continue
            if membership.revision_time is not None and membership.revision_time > as_of_time:
                continue
            assert_point_in_time(available_time=membership.available_time, decision_time=as_of_time)
            event = (
                membership.evidence.event_id if membership.evidence else "LEGACY_GLOBAL_REVISION"
            )
            key = membership.instrument_id, event, membership.revision
            if key in revisions and revisions[key] != membership:
                raise ValueError("AQ-PIT-CONFLICTING-MEMBERSHIP-REVISION")
            revisions[key] = membership
        latest: dict[tuple[str, str], UniverseMembership] = {}
        legacy: list[UniverseMembership] = []
        for membership in revisions.values():
            if membership.evidence is None:
                legacy.append(membership)
                continue
            key = membership.instrument_id, membership.evidence.event_id
            if key not in latest or membership.revision > latest[key].revision:
                latest[key] = membership
        return tuple(
            sorted(
                [*legacy, *latest.values()], key=lambda row: (row.instrument_id, row.membership_id)
            )
        )

    def current_memberships(self, *, as_of_time: UtcDateTime) -> tuple[UniverseMembership, ...]:
        candidates: dict[str, list[UniverseMembership]] = {}
        for membership in self.known_events(as_of_time=as_of_time):
            if membership.effective_from <= as_of_time:
                candidates.setdefault(membership.instrument_id, []).append(membership)
        selected: list[UniverseMembership] = []
        for instrument_id in sorted(candidates):
            rows = candidates[instrument_id]
            if any(row.evidence is not None for row in rows):
                if any(row.evidence is None for row in rows):
                    raise ValueError("AQ-PIT-MIXED-LEGACY-EVENT-IDENTITY")
                newest = max(row.effective_from for row in rows)
                active = [row for row in rows if row.effective_from == newest]
                if len(active) != 1:
                    raise ValueError("AQ-PIT-CONFLICTING-EFFECTIVE-EVENTS")
                membership = active[0]
            else:
                membership = max(
                    rows,
                    key=lambda item: (
                        item.revision,
                        item.revision_time or item.available_time,
                        item.available_time,
                    ),
                )
            selected.append(membership)
        return tuple(selected)

    def snapshot(self, *, as_of_time: UtcDateTime) -> UniverseSnapshot:
        selected = [
            row
            for row in self.current_memberships(as_of_time=as_of_time)
            if row.eligible and (row.effective_to is None or as_of_time < row.effective_to)
        ]
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
