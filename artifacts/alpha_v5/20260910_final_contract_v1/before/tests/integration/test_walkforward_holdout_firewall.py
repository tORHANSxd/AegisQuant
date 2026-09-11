from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegisquant.research.validation.holdout import create_freeze_manifest
from aegisquant.research.validation.persistent_holdout import open_persistent_holdout


def test_durable_firewall_denies_unfrozen_used_and_second_access(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    frozen = create_freeze_manifest(
        dataset_sha256="1" * 64,
        feature_set_sha256="2" * 64,
        label_set_sha256="3" * 64,
        universe_sha256="4" * 64,
        split_sha256="5" * 64,
        cost_policy_sha256="6" * 64,
        model_spec_sha256="7" * 64,
        parameters_sha256="8" * 64,
        code_sha256="9" * 64,
        frozen_at=now,
    )
    loaded: list[bool] = []

    def loader() -> str:
        loaded.append(True)
        return "sealed data"

    def attempt(*, frozen_ok: bool = True, used_year: int = 2023) -> str:
        return open_persistent_holdout(
            directory=tmp_path,
            manifest=frozen if frozen_ok else None,
            expected_dataset_sha256="1" * 64,
            holdout_start=datetime(2025, 1, 1, tzinfo=UTC),
            holdout_end=now,
            previously_used_through=datetime(used_year, 6, 1, tzinfo=UTC),
            loader=loader,
            accessed_at=now,
        )

    with pytest.raises(PermissionError, match="NOT-FROZEN"):
        attempt(frozen_ok=False)
    with pytest.raises(PermissionError, match="UNUSED"):
        attempt(used_year=2025)
    assert not loaded
    assert attempt() == "sealed data"
    with pytest.raises(PermissionError, match="ALREADY-CLAIMED"):
        attempt()
    assert loaded == [True]
