"""PIT source-compromise state remains independent from official identity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aegisquant.domain.identifiers import ArtifactId, SourceId, SourceIdentityId
from aegisquant.truth.contracts import (
    IdentityFactor,
    OfficialIdentityAssessment,
    OfficialIdentityState,
    SourceCompromiseEvent,
    SourceCompromiseStatus,
)
from aegisquant.truth.manipulation import SourceCompromiseStore

NOW = datetime(2026, 9, 2, 18, tzinfo=UTC)
SOURCE_ID = SourceId("official-account")


def _event(
    *,
    version: int,
    status: SourceCompromiseStatus,
    at: datetime,
    previous: ArtifactId | None = None,
) -> SourceCompromiseEvent:
    return SourceCompromiseEvent(
        event_id=ArtifactId(f"compromise-event:{version}"),
        source_id=SOURCE_ID,
        version=version,
        previous_event_id=previous,
        status=status,
        reason_codes=(f"SOURCE_{status.value}",),
        effective_at=at,
        observed_at=at,
        available_at=at,
    )


def test_compromise_timeline_is_append_only_and_excludes_future_recovery() -> None:
    normal = _event(version=1, status=SourceCompromiseStatus.NORMAL, at=NOW)
    compromised = _event(
        version=2,
        status=SourceCompromiseStatus.COMPROMISED,
        at=NOW + timedelta(minutes=10),
        previous=normal.event_id,
    )
    recovered = _event(
        version=3,
        status=SourceCompromiseStatus.RECOVERED,
        at=NOW + timedelta(hours=1),
        previous=compromised.event_id,
    )
    store = SourceCompromiseStore()
    store.apply(normal)
    store.apply(compromised)
    store.apply(recovered)
    assert store.as_of(SOURCE_ID, decision_time=NOW) == normal
    assert store.as_of(SOURCE_ID, decision_time=NOW + timedelta(minutes=30)) == compromised
    assert store.as_of(SOURCE_ID, decision_time=NOW + timedelta(hours=1)) == recovered


def test_authentic_identity_can_be_compromised_without_becoming_spoofed() -> None:
    authentic = OfficialIdentityAssessment(
        assessment_id=ArtifactId("official-identity-assessment"),
        source_id=SOURCE_ID,
        source_identity_id=SourceIdentityId("official-source-identity"),
        registry_entry_id=ArtifactId("official-source-registry-entry"),
        state=OfficialIdentityState.AUTHENTIC,
        matched_factors=(IdentityFactor.SOCIAL_ACCOUNT,),
        reason_codes=("OFFICIAL_PLATFORM_ACCOUNT_ID_MATCH",),
        observed_at=NOW,
        available_at=NOW,
    )
    compromised = _event(
        version=1,
        status=SourceCompromiseStatus.COMPROMISED,
        at=NOW,
    )
    store = SourceCompromiseStore()
    store.apply(compromised)
    compromise_as_of = store.as_of(SOURCE_ID, decision_time=NOW)
    assert authentic.state is OfficialIdentityState.AUTHENTIC
    assert compromise_as_of is not None
    assert compromise_as_of.status is SourceCompromiseStatus.COMPROMISED


def test_recovery_requires_prior_compromise_and_chain_is_fail_closed() -> None:
    store = SourceCompromiseStore()
    with pytest.raises(ValueError, match="RECOVERY-WITHOUT-COMPROMISE"):
        store.apply(_event(version=1, status=SourceCompromiseStatus.RECOVERED, at=NOW))

    first = _event(version=1, status=SourceCompromiseStatus.NORMAL, at=NOW)
    store.apply(first)
    with pytest.raises(ValueError, match="VERSION-GAP"):
        store.apply(
            _event(
                version=3,
                status=SourceCompromiseStatus.COMPROMISED,
                at=NOW + timedelta(minutes=1),
                previous=first.event_id,
            )
        )
