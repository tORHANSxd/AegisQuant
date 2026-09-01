from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisquant.data.hashing import sha256_file
from aegisquant.research.datasets import (
    ExternalBaselineManifest,
    register_external_baseline,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def manifest(source_hash: str) -> ExternalBaselineManifest:
    return ExternalBaselineManifest(
        baseline_id="user-baseline-v1",
        source_sha256=source_hash,
        data_scope="BTCUSDT public historical results",
        cost_scope="fee, spread, slippage documented by user",
        rights_status="personal_research_only",
        imported_at=NOW,
        immutable=True,
    )


def test_external_baseline_is_hash_verified_and_content_addressed(tmp_path: Path) -> None:
    source = tmp_path / "baseline.csv"
    source.write_text("time,net_return\n2026-01-01,0.01\n", encoding="utf-8")
    source_hash = sha256_file(source)
    record = register_external_baseline(
        source=source,
        manifest=manifest(source_hash),
        registry_directory=tmp_path / "registry",
    )
    destination = tmp_path / "registry" / record.stored_path
    assert destination.name == f"{source_hash}.csv"
    assert sha256_file(destination) == source_hash
    assert (
        register_external_baseline(
            source=source,
            manifest=manifest(source_hash),
            registry_directory=tmp_path / "registry",
        )
        == record
    )

    with pytest.raises(ValueError, match="HASH-MISMATCH"):
        register_external_baseline(
            source=source,
            manifest=manifest("0" * 64),
            registry_directory=tmp_path / "other",
        )


def test_external_baseline_rejects_unknown_rights_status() -> None:
    payload = manifest("a" * 64).model_dump()
    payload["rights_status"] = "unknown"
    with pytest.raises(ValidationError, match="rights_status"):
        ExternalBaselineManifest.model_validate(payload)
