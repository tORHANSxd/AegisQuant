"""Provider, schema, checkpoint, quality, and immutable-lake tests."""

from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pytest

from aegisquant.data.checkpoint import CheckpointStore, IngestCheckpoint
from aegisquant.data.models import ContentTimeSemantics, LakeLayer
from aegisquant.data.provider_registry import ProviderStatus
from aegisquant.data.schema_registry import ArrowSchemaRegistry
from aegisquant.domain.errors import DomainError
from aegisquant.domain.identifiers import ProviderId, SourcePolicyId
from aegisquant.domain.policy import PolicyBoundary
from tests.p02.helpers import (
    NOW,
    dataset_writer,
    lineage,
    load_registries,
    quality_report,
    synthetic_table,
)


def test_provider_registry_is_fail_closed(project_root: Path) -> None:
    providers, policies = load_registries(project_root)
    approved = providers.get(ProviderId("synthetic_fixture"))
    assert approved.status is ProviderStatus.APPROVED
    assert providers.content_hash() == providers.content_hash()

    denied = policies.get(SourcePolicyId("user_local_assets_deny_v1"))
    with pytest.raises(DomainError, match="AQ-PROVIDER-ACCESS-AWAITING_USER_APPROVAL"):
        providers.require_collection(denied.provider_id, denied)
    with pytest.raises(DomainError, match="AQ-PROVIDER-POLICY-NOT-REGISTERED"):
        policies.get(SourcePolicyId("unregistered-policy"))


def test_content_time_semantics_rejects_lookahead() -> None:
    valid = ContentTimeSemantics(
        event_time=NOW,
        published_time=NOW + timedelta(seconds=1),
        observed_time=NOW + timedelta(seconds=2),
        available_time=NOW + timedelta(seconds=3),
        ingest_time=NOW + timedelta(seconds=4),
    )
    assert valid.event_time < valid.available_time < valid.ingest_time

    with pytest.raises(ValueError, match="event_time <= available_time"):
        ContentTimeSemantics(
            event_time=NOW,
            available_time=NOW - timedelta(seconds=1),
            ingest_time=NOW + timedelta(seconds=1),
        )


def test_same_table_has_same_dataset_identity_and_single_catalog_row(
    tmp_path: Path, project_root: Path
) -> None:
    writer, policy = dataset_writer(root=tmp_path, project_root=project_root)
    table = synthetic_table()
    report = quality_report(table)

    first = writer.write_table(
        table=table,
        provider_id=policy.provider_id,
        policy=policy,
        dataset_name="synthetic_events",
        schema_version="1.0.0",
        requested_layer=LakeLayer.SILVER,
        available_time_policy="available_time <= decision_time",
        lineage=lineage(),
        quality_report=report,
        time_column="event_time",
    )
    second = writer.write_table(
        table=table,
        provider_id=policy.provider_id,
        policy=policy,
        dataset_name="synthetic_events",
        schema_version="1.0.0",
        requested_layer=LakeLayer.SILVER,
        available_time_policy="available_time <= decision_time",
        lineage=lineage(),
        quality_report=report,
        time_column="event_time",
    )

    assert first.manifest.dataset_id == second.manifest.dataset_id
    assert first.manifest.manifest_hash() == second.manifest.manifest_hash()
    assert first.manifest.row_count == table.num_rows
    assert len(writer.catalog.query(dataset_name="synthetic_events")) == 1
    assert writer.catalog.verify_manifest(first.manifest_path) == first.manifest


def test_raw_parquet_cannot_bypass_encrypted_revision_archive(
    tmp_path: Path, project_root: Path
) -> None:
    writer, policy = dataset_writer(root=tmp_path, project_root=project_root)
    table = synthetic_table()
    with pytest.raises(DomainError, match="AQ-DATA-USE-ENCRYPTED-REVISION-ARCHIVE"):
        writer.write_table(
            table=table,
            provider_id=policy.provider_id,
            policy=policy,
            dataset_name="synthetic_raw",
            schema_version="1.0.0",
            requested_layer=LakeLayer.RAW,
            available_time_policy="available_time <= decision_time",
            lineage=lineage(),
            quality_report=quality_report(table, dataset_name="synthetic_raw"),
        )


def test_quality_failures_quarantine_non_gold_and_block_gold(
    tmp_path: Path, project_root: Path
) -> None:
    writer, policy = dataset_writer(root=tmp_path, project_root=project_root)
    bad_table = pa.table({"event_id": ["duplicate", "duplicate"], "value": [1, 2]})
    failed = quality_report(bad_table, dataset_name="bad_events")
    assert failed.passed is False

    quarantined = writer.write_table(
        table=bad_table,
        provider_id=policy.provider_id,
        policy=policy,
        dataset_name="bad_events",
        schema_version="1.0.0",
        requested_layer=LakeLayer.SILVER,
        available_time_policy="available_time <= decision_time",
        lineage=lineage(),
        quality_report=failed,
    )
    assert quarantined.manifest.layer is LakeLayer.QUARANTINE

    with pytest.raises(DomainError, match="AQ-DATA-GOLD-QUALITY-FAILED"):
        writer.write_table(
            table=bad_table,
            provider_id=policy.provider_id,
            policy=policy,
            dataset_name="bad_gold",
            schema_version="1.0.0",
            requested_layer=LakeLayer.GOLD,
            available_time_policy="available_time <= decision_time",
            lineage=lineage(),
            quality_report=failed,
        )


def test_schema_registry_and_checkpoint_are_atomic_and_idempotent(tmp_path: Path) -> None:
    schema_registry = ArrowSchemaRegistry(tmp_path / "schemas.json")
    first_schema = pa.schema([("value", pa.int64())])
    entry = schema_registry.register(
        schema_name="ticks", schema_version="1.0.0", schema=first_schema
    )
    assert (
        schema_registry.register(schema_name="ticks", schema_version="1.0.0", schema=first_schema)
        == entry
    )
    with pytest.raises(ValueError, match="AQ-DATA-SCHEMA-CONFLICT"):
        schema_registry.register(
            schema_name="ticks",
            schema_version="1.0.0",
            schema=pa.schema([("value", pa.string())]),
        )

    checkpoint = IngestCheckpoint(
        provider_id=ProviderId("synthetic_fixture"),
        dataset_name="ticks",
        cursor="page-2",
        byte_offset=4096,
        source_request_hash="a" * 64,
        last_completed_content_hash="b" * 64,
        updated_at=NOW,
    )
    store = CheckpointStore(tmp_path / "checkpoints")
    path = store.save(checkpoint)
    assert "synthetic_fixture" not in path.as_posix()
    assert store.load(checkpoint.provider_id, checkpoint.dataset_name) == checkpoint
    assert not tuple(path.parent.glob("*.tmp"))


def test_approved_provider_allows_declared_collection_boundary(project_root: Path) -> None:
    providers, policies = load_registries(project_root)
    policy = policies.get(SourcePolicyId("synthetic_fixture_v1"))
    decision = providers.require(policy.provider_id, policy, PolicyBoundary.COLLECTION)
    assert decision.provider_id == policy.provider_id
