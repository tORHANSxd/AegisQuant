"""Phase state gate tests."""

from pathlib import Path

import yaml

CLOSED_STATUSES = {"accepted", "accepted_with_waiver"}


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
    assert payload["status"] in {"in_progress", *CLOSED_STATUSES}
    assert payload["live_trading_locked"] is True
    assert payload["previous_phase"]["status"] in CLOSED_STATUSES


def test_acceptance_state_has_evidence_when_closed(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
    )
    if payload["status"] in CLOSED_STATUSES:
        assert payload["accepted_at_utc"]
        assert len(payload["commit_sha"]) == 40
        assert len(payload["artifact_manifest_sha256"]) == 64
    if payload["status"] == "accepted_with_waiver":
        waivers = payload["waivers"]
        assert len(waivers) == 1
        assert waivers[0]["waiver_id"] == "P03-WAIVER-001"
        assert waivers[0]["requirement_id"] == "P03-A01"
        assert waivers[0]["decision"] == "owner_approved"
