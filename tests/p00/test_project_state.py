"""Phase state gate tests."""

from pathlib import Path

import yaml

CLOSED_STATUSES = {"accepted", "accepted_with_waiver"}


def test_phase_state_advances_one_accepted_phase_at_a_time(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
    )

    current_number = int(payload["current_phase"][1:])
    previous_number = int(payload["previous_phase"]["phase"][1:])

    assert current_number >= 1
    if current_number == 18:
        assert payload["next_phase"] is None
    else:
        assert int(payload["next_phase"][1:]) == current_number + 1
    assert previous_number == current_number - 1
    assert payload["status"] in {"in_progress", *CLOSED_STATUSES}
    assert payload["live_trading_locked"] is True
    previous_status = payload["previous_phase"]["status"]
    if previous_status not in CLOSED_STATUSES:
        deferred = payload.get("deferred_acceptance_queue", [])
        assert payload["status"] == "in_progress"
        assert any(
            item["phase"] == payload["previous_phase"]["phase"]
            and item["status"] == "implementation_verified_acceptance_deferred"
            for item in deferred
        )


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
