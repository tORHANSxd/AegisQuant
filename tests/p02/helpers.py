"""Deterministic P02 fixtures shared by data-foundation tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa

from aegisquant.data.catalog import DataCatalog
from aegisquant.data.lake import AtomicDatasetWriter
from aegisquant.data.lineage import TransformationLineage
from aegisquant.data.models import QualityReport
from aegisquant.data.provider_registry import ProviderRegistry, SourcePolicyRegistry
from aegisquant.data.quality import (
    AvailableBeforeIngestRule,
    NonNullRule,
    QualityEngine,
    RequiredColumnsRule,
    UniqueKeyRule,
)
from aegisquant.data.schema_registry import ArrowSchemaRegistry
from aegisquant.domain.identifiers import SourcePolicyId
from aegisquant.domain.policy import SourceProcessingPolicy
from aegisquant.domain.time import FixedClock

NOW = datetime(2026, 8, 31, 11, tzinfo=UTC)


def load_registries(project_root: Path) -> tuple[ProviderRegistry, SourcePolicyRegistry]:
    provider_registry = ProviderRegistry.from_yaml(
        project_root / "data/catalogs/provider_registry.yaml"
    )
    policy_registry = SourcePolicyRegistry.from_yaml(
        project_root / "data/catalogs/source_policy_registry.yaml"
    )
    return provider_registry, policy_registry


def synthetic_policy(policy_registry: SourcePolicyRegistry) -> SourceProcessingPolicy:
    return policy_registry.get(SourcePolicyId("synthetic_fixture_v1"))


def synthetic_table(*, rows: int = 4) -> pa.Table:
    event_times = [NOW + timedelta(minutes=index) for index in range(rows)]
    available_times = [value + timedelta(seconds=10) for value in event_times]
    ingest_times = [value + timedelta(seconds=5) for value in available_times]
    return pa.table(
        {
            "event_id": [f"event-{index}" for index in range(rows)],
            "event_time": event_times,
            "available_time": available_times,
            "ingest_time": ingest_times,
            "value": [index * 10 for index in range(rows)],
        }
    )


def quality_report(table: pa.Table, *, dataset_name: str = "synthetic_events") -> QualityReport:
    engine = QualityEngine(
        rules=(
            RequiredColumnsRule(("event_id", "event_time", "available_time", "ingest_time")),
            NonNullRule(("event_id", "available_time", "ingest_time")),
            UniqueKeyRule(("event_id",)),
            AvailableBeforeIngestRule(),
        )
    )
    return engine.evaluate(table=table, dataset_name=dataset_name, evaluated_at=NOW)


def lineage() -> TransformationLineage:
    return TransformationLineage(
        transform_name="synthetic_fixture_to_silver",
        transform_version="1.0.0",
        input_manifest_hashes=("1" * 64,),
        code_commit="2" * 40,
        config_hash="3" * 64,
        source_request_hash="4" * 64,
    )


def dataset_writer(
    *, root: Path, project_root: Path
) -> tuple[AtomicDatasetWriter, SourceProcessingPolicy]:
    provider_registry, policy_registry = load_registries(project_root)
    lake_root = root / "lake"
    catalog = DataCatalog(lake_root=lake_root, index_path=root / "catalog" / "datasets.jsonl")
    writer = AtomicDatasetWriter(
        lake_root=lake_root,
        catalog=catalog,
        schema_registry=ArrowSchemaRegistry(root / "catalog" / "arrow_schemas.json"),
        provider_registry=provider_registry,
        clock=FixedClock(NOW),
        row_group_size=2,
    )
    return writer, synthetic_policy(policy_registry)
