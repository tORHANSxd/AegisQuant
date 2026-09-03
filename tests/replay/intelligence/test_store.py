from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from aegisquant.data.provider_registry import SourcePolicyRegistry
from aegisquant.domain.identifiers import ArtifactId
from aegisquant.domain.intelligence import EngagementSnapshot, RightsState
from aegisquant.intelligence.collectors import content_contracts, parse_x
from aegisquant.intelligence.store import ContentProjectionStore, IntelligenceMetadataArchive

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def load_x(project_root: Path):  # type: ignore[no-untyped-def]
    payload = cast(
        dict[str, object],
        json.loads((project_root / "tests/fixtures/p04/event_sources.json").read_text())["x"],
    )
    return parse_x(payload, observed_time=NOW)[0]


def test_revision_and_deletion_propagate_to_cache_and_read_model(project_root: Path) -> None:
    policy = SourcePolicyRegistry.from_yaml(
        project_root / "data/catalogs/source_policy_registry.yaml"
    ).get("x_official_restricted_v1")
    item = load_x(project_root).model_copy(
        update={"revision": 1, "modified_time": None, "deleted_time": None}
    )
    identity, first, snapshot = content_contracts(
        item,
        available_time=NOW,
        ingest_time=NOW,
        source_policy_id=policy.source_policy_id,
        rights_state=RightsState.LIMITED,
    )
    store = ContentProjectionStore()
    store.apply_identity(identity)
    store.apply_revision(first, policy=policy)
    if snapshot is not None:
        store.record_engagement(snapshot)

    second_item = item.model_copy(
        update={
            "text": "Bitcoin ETF approval update corrected",
            "revision": 2,
            "modified_time": NOW + timedelta(minutes=1),
            "observed_time": NOW + timedelta(minutes=1),
        }
    )
    _, second, _ = content_contracts(
        second_item,
        available_time=NOW + timedelta(minutes=1),
        ingest_time=NOW + timedelta(minutes=1),
        source_policy_id=policy.source_policy_id,
        rights_state=RightsState.LIMITED,
    )
    store.apply_revision(second, policy=policy)
    deleted_item = second_item.model_copy(
        update={
            "text": "[deleted]",
            "revision": 3,
            "deleted_time": NOW + timedelta(minutes=2),
            "modified_time": NOW + timedelta(minutes=2),
            "observed_time": NOW + timedelta(minutes=2),
        }
    )
    _, deleted, _ = content_contracts(
        deleted_item,
        available_time=NOW + timedelta(minutes=2),
        ingest_time=NOW + timedelta(minutes=2),
        source_policy_id=policy.source_policy_id,
        rights_state=RightsState.LIMITED,
    )
    tombstone = store.apply_revision(deleted, policy=policy)
    assert tombstone is not None
    assert "SYNC_DELETION_AND_APPEND_TOMBSTONE" in tombstone.required_actions
    assert store.current(first.content_id) is None
    assert store.cached(first.content_id) is None
    assert store.tombstone(first.content_id) == tombstone
    assert len(store.revision_history(first.content_id)) == 3
    assert store.as_of(first.content_id, decision_time=NOW + timedelta(seconds=30)) == first
    assert store.as_of(first.content_id, decision_time=NOW + timedelta(minutes=3)) is None


def test_engagement_is_point_in_time_not_current_backfill(project_root: Path) -> None:
    item = load_x(project_root).model_copy(update={"revision": 1, "modified_time": None})
    policy = SourcePolicyRegistry.from_yaml(
        project_root / "data/catalogs/source_policy_registry.yaml"
    ).get("x_official_restricted_v1")
    _, envelope, snapshot = content_contracts(
        item,
        available_time=NOW,
        ingest_time=NOW,
        source_policy_id=policy.source_policy_id,
        rights_state=RightsState.LIMITED,
    )
    assert snapshot is not None
    later = EngagementSnapshot(
        engagement_snapshot_id=ArtifactId("later-engagement"),
        content_id=envelope.content_id,
        observed_time=NOW + timedelta(hours=1),
        available_time=NOW + timedelta(hours=1),
        metrics={"like_count": 1000},
    )
    store = ContentProjectionStore()
    store.record_engagement(snapshot)
    store.record_engagement(later)
    historical = store.engagement_as_of(
        envelope.content_id, decision_time=NOW + timedelta(minutes=30)
    )
    assert historical == snapshot
    assert historical is not None
    assert historical.metrics["like_count"] == 10


def test_source_identity_versions_are_append_only(project_root: Path) -> None:
    item = load_x(project_root)
    policy = SourcePolicyRegistry.from_yaml(
        project_root / "data/catalogs/source_policy_registry.yaml"
    ).get("x_official_restricted_v1")
    identity, _, _ = content_contracts(
        item,
        available_time=NOW,
        ingest_time=NOW,
        source_policy_id=policy.source_policy_id,
        rights_state=RightsState.LIMITED,
    )
    renamed = item.model_copy(
        update={
            "display_name": "Renamed Official Fixture",
            "verified_source": not identity.verified,
            "observed_time": NOW + timedelta(days=1),
        }
    )
    second, second_envelope, _ = content_contracts(
        renamed,
        available_time=NOW + timedelta(days=1),
        ingest_time=NOW + timedelta(days=1),
        source_policy_id=policy.source_policy_id,
        rights_state=RightsState.LIMITED,
        previous_identity=identity,
    )
    assert second.version == 2
    assert second.supersedes_source_identity_id == identity.source_identity_id
    assert second_envelope.source_identity_id == second.source_identity_id
    unchanged, _, _ = content_contracts(
        renamed.model_copy(update={"observed_time": NOW + timedelta(days=2)}),
        available_time=NOW + timedelta(days=2),
        ingest_time=NOW + timedelta(days=2),
        source_policy_id=policy.source_policy_id,
        rights_state=RightsState.LIMITED,
        previous_identity=second,
    )
    assert unchanged == second
    store = ContentProjectionStore()
    store.apply_identity(identity)
    store.apply_identity(second)
    store.apply_identity(second)
    assert store.identity_history(
        provider_id=identity.provider_id, provider_native_id=identity.provider_native_id
    ) == (identity, second)
    assert (
        store.identity_as_of(
            provider_id=identity.provider_id,
            provider_native_id=identity.provider_native_id,
            decision_time=NOW,
        )
        == identity
    )
    assert (
        store.identity_as_of(
            provider_id=identity.provider_id,
            provider_native_id=identity.provider_native_id,
            decision_time=NOW + timedelta(days=1),
        )
        == second
    )


def test_identity_and_engagement_metadata_are_persisted_append_only(
    project_root: Path, tmp_path: Path
) -> None:
    item = load_x(project_root).model_copy(update={"revision": 1, "modified_time": None})
    policy = SourcePolicyRegistry.from_yaml(
        project_root / "data/catalogs/source_policy_registry.yaml"
    ).get("x_official_restricted_v1")
    identity, envelope, snapshot = content_contracts(
        item,
        available_time=NOW,
        ingest_time=NOW,
        source_policy_id=policy.source_policy_id,
        rights_state=RightsState.LIMITED,
    )
    assert snapshot is not None
    archive = IntelligenceMetadataArchive(tmp_path / "metadata")
    identity_path = archive.append_identity(identity)
    engagement_path = archive.append_engagement(snapshot)
    assert identity_path.is_file()
    assert engagement_path.is_file()
    assert archive.append_identity(identity) == identity_path
    assert archive.append_engagement(snapshot) == engagement_path
    assert archive.engagement_history(envelope.content_id) == (snapshot,)
    assert archive.engagement_as_of(envelope.content_id, decision_time=NOW) == snapshot
    assert (
        archive.engagement_as_of(envelope.content_id, decision_time=NOW - timedelta(seconds=1))
        is None
    )
