"""Pinned columnar-runtime and generated-schema contracts."""

import importlib.metadata
import json
from pathlib import Path

import polars as pl
import pyarrow as pa

from aegisquant.data.transforms import transform_arrow

EXPECTED_VERSIONS = {
    "cryptography": "50.0.1",
    "duckdb": "1.5.5",
    "polars": "1.44.1",
    "psutil": "7.2.2",
    "pyarrow": "25.0.1",
    "pyarrow-stubs": "20.0.0.20260819",
}


def test_columnar_dependencies_match_locked_contract() -> None:
    assert {
        package: importlib.metadata.version(package) for package in EXPECTED_VERSIONS
    } == EXPECTED_VERSIONS


def test_arrow_polars_lazy_transform_contract() -> None:
    table = pa.table({"value": [1, 2, 3]})
    result = transform_arrow(
        table,
        lambda frame: frame.with_columns((pl.col("value") * 2).alias("x")),
    )
    assert result.to_pylist() == [
        {"value": 1, "x": 2},
        {"value": 2, "x": 4},
        {"value": 3, "x": 6},
    ]


def test_p02_schema_registry_contains_data_contracts(project_root: Path) -> None:
    registry_path = project_root / "schemas/data/registry.json"
    assert registry_path.is_file()
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert len(registry["data_contracts"]) >= 11
    assert {entry["model"].rsplit(".", maxsplit=1)[-1] for entry in registry["data_contracts"]} >= {
        "DatasetManifest",
        "ProviderRegistryDocument",
        "ContentTimeSemantics",
        "InventoryRecord",
    }
