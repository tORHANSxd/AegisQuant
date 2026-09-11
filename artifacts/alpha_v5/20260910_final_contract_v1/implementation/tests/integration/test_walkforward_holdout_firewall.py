from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aegisquant.research.validation.persistent_holdout import open_persistent_holdout
from tests.alpha_v5.test_holdout_contract import prepare_synthetic_holdout


def test_durable_firewall_denies_unfrozen_used_and_second_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs, _, _ = prepare_synthetic_holdout(tmp_path, monkeypatch)
    loaded: list[bool] = []

    def loader(data: bytes) -> str:
        assert data.startswith(b"SYNTHETIC ONLY")
        loaded.append(True)
        return "sealed data"

    def attempt(
        *, frozen_ok: bool = True, already_used: bool = False, authorized: bool = True
    ) -> str:
        options: dict[str, Any] = {
            **kwargs,
            "manifest": kwargs["manifest"] if frozen_ok else None,
            "previously_used_through": datetime(2025, 6, 1, tzinfo=UTC)
            if already_used
            else kwargs["previously_used_through"],
            "loader": loader,
            "authorization": kwargs["authorization"] if authorized else None,
        }
        return open_persistent_holdout(**options)

    with pytest.raises(PermissionError, match="NOT-FROZEN"):
        attempt(frozen_ok=False)
    with pytest.raises(PermissionError, match="UNUSED"):
        attempt(already_used=True)
    with pytest.raises(PermissionError, match="AUTHORIZATION-REQUIRED"):
        attempt(authorized=False)
    assert not loaded
    assert attempt() == "sealed data"
    with pytest.raises(PermissionError, match="ALREADY-CLAIMED"):
        attempt()
    assert loaded == [True]
