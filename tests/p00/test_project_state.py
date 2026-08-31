"""Phase state gate tests."""

from pathlib import Path

import yaml


def test_phase_state_advances_one_accepted_phase_at_a_time(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
    )

    current_number = int(payload["current_phase"][1:])
    next_number = int(payload["next_phase"][1:])
    previous_number = int(payload["previous_phase"]["phase"][1:])

    assert current_number >= 1
    assert next_number == current_number + 1
    assert previous_number == current_number - 1
    assert payload["status"] in {"in_progress", "accepted"}
    assert payload["live_trading_locked"] is True
    assert payload["previous_phase"]["status"] == "accepted"


def test_acceptance_state_has_evidence_when_accepted(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
    )
    if payload["status"] == "accepted":
        assert payload["accepted_at_utc"]
        assert len(payload["commit_sha"]) == 40
        assert len(payload["artifact_manifest_sha256"]) == 64
