from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aegisquant.research.validation import (
    FinalHoldoutVault,
    HoldoutState,
    ResearchFreezeManifest,
    create_freeze_manifest,
)

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)
HASH = "a" * 64


def freeze_manifest() -> ResearchFreezeManifest:
    return create_freeze_manifest(
        dataset_sha256=HASH,
        feature_set_sha256="b" * 64,
        label_set_sha256="c" * 64,
        universe_sha256="d" * 64,
        split_sha256="e" * 64,
        cost_policy_sha256="f" * 64,
        model_spec_sha256="1" * 64,
        parameters_sha256="2" * 64,
        code_sha256="3" * 64,
        frozen_at=NOW,
    )


def test_final_holdout_loader_runs_only_once_after_complete_freeze() -> None:
    invocations = 0

    def load() -> tuple[str, ...]:
        nonlocal invocations
        invocations += 1
        return ("sealed-final-row",)

    vault = FinalHoldoutVault(
        holdout_id="final-2026",
        expected_dataset_sha256=HASH,
        loader=load,
    )
    with pytest.raises(PermissionError, match="AQ-HOLDOUT-LOCKED"):
        vault.open_once(freeze_id="wrong", occurred_at=NOW)
    assert invocations == 0
    assert vault.state is HoldoutState.LOCKED

    manifest = freeze_manifest()
    vault.freeze(manifest, occurred_at=NOW + timedelta(seconds=1))
    result = vault.open_once(
        freeze_id=manifest.freeze_id,
        occurred_at=NOW + timedelta(seconds=2),
    )
    assert result == ("sealed-final-row",)
    assert invocations == 1
    assert vault.state is HoldoutState.OPENED

    with pytest.raises(PermissionError, match="AQ-HOLDOUT-LOCKED"):
        vault.open_once(
            freeze_id=manifest.freeze_id,
            occurred_at=NOW + timedelta(seconds=3),
        )
    assert invocations == 1
    audit = vault.audit_log()
    assert [item.event for item in audit] == ["OPEN_DENIED", "FROZEN", "OPENED_ONCE", "OPEN_DENIED"]
    assert all(audit[index].previous_hash == audit[index - 1].entry_hash for index in range(1, 4))
