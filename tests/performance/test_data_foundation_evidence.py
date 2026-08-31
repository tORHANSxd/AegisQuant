"""P02 bounded-memory and scale-estimate evidence contracts."""

import hashlib
import json
from pathlib import Path
from typing import cast

import pyarrow.parquet as pq


def test_p02_benchmark_and_inventory_are_real_bounded_artifacts(project_root: Path) -> None:
    report_dir = project_root / "reports/data"
    evidence = cast(
        dict[str, object],
        json.loads((report_dir / "P02_DATA_EVIDENCE.json").read_text(encoding="utf-8")),
    )
    inventory = cast(dict[str, object], evidence["inventory"])
    benchmark = cast(dict[str, object], evidence["benchmark"])
    inventory_path = report_dir / "LOCAL_ASSET_INVENTORY.parquet"

    assert evidence["real_user_assets_scanned"] is False
    assert evidence["live_trading_locked"] is True
    assert int(cast(int, inventory["synthetic_file_count"])) >= 4096
    assert pq.ParquetFile(inventory_path).metadata.num_rows == inventory["synthetic_file_count"]
    assert hashlib.sha256(inventory_path.read_bytes()).hexdigest() == inventory["inventory_sha256"]
    assert int(cast(int, benchmark["row_count"])) >= 1_000_000
    assert int(cast(int, benchmark["row_group_count"])) >= 10
    assert benchmark["all_files_materialized_in_ram"] is False
    assert float(cast(float, benchmark["estimated_100_gib_scan_seconds"])) > 0
    assert float(cast(float, benchmark["estimated_200_gib_scan_seconds"])) > 0
    assert benchmark["benchmark_file_retained"] is False


def test_public_sample_is_pinned_metadata_only(project_root: Path) -> None:
    payload = json.loads(
        (project_root / "reports/data/PUBLIC_PARQUET_SAMPLE.json").read_text(encoding="utf-8")
    )
    assert payload["pinned_commit"] == "09f3cdbde45302f0f0c689c950e465e98a9df960"
    assert payload["sha256"] == "12a618d20a59ee0967fef45e7ec1ff6d451e724838edc1bbeac780ca15e8fcc4"
    assert payload["raw_bytes_retained"] is False
    assert payload["processing_mode"] == "in_memory_metadata_only"
    assert payload["credentials_used"] is False
