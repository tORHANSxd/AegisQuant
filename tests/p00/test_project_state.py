"""Phase state gate tests."""

from pathlib import Path

import yaml


def test_phase_state_never_advances_to_p01(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
    )

    assert payload["current_phase"] == "P00"
    assert payload["next_phase"] == "P01"
    assert payload["status"] in {"in_progress", "accepted"}
    assert payload["live_trading_locked"] is True


def test_acceptance_state_has_evidence_when_accepted(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
    )
    if payload["status"] == "accepted":
        assert payload["accepted_at_utc"]
        assert len(payload["commit_sha"]) == 40
        assert len(payload["artifact_manifest_sha256"]) == 64
