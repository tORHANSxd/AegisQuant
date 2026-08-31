"""Failure-injection contracts for atomic P02 dataset publication."""

from pathlib import Path

import pytest

from aegisquant.data.models import LakeLayer
from tests.p02.helpers import dataset_writer, lineage, quality_report, synthetic_table


def test_interrupted_write_never_registers_incomplete_dataset(
    tmp_path: Path, project_root: Path
) -> None:
    writer, policy = dataset_writer(root=tmp_path, project_root=project_root)
    table = synthetic_table()

    def fail_before_publish(point: str) -> None:
        if point == "before_atomic_publish":
            raise RuntimeError("injected interruption")

    with pytest.raises(RuntimeError, match="injected interruption"):
        writer.write_table(
            table=table,
            provider_id=policy.provider_id,
            policy=policy,
            dataset_name="interrupted_events",
            schema_version="1.0.0",
            requested_layer=LakeLayer.SILVER,
            available_time_policy="available_time <= decision_time",
            lineage=lineage(),
            quality_report=quality_report(table, dataset_name="interrupted_events"),
            fault_hook=fail_before_publish,
        )

    assert writer.catalog.query(dataset_name="interrupted_events") == ()
    assert not tuple((writer.lake_root / ".staging").glob("dataset-*"))
    assert not (writer.lake_root / LakeLayer.SILVER.value).exists()
