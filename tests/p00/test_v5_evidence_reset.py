"""V5-P00 SSOT, evidence reset, and fail-closed promotion tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
import yaml

from aegisquant.domain.evidence import EvidenceDisclosure, EvidenceTier

EXPECTED_SPEC_SHA256 = "aee366d5fa1a8ebd7449c597e6f822535546633efc335c1ab0053333d160a255"


def load_json(path: Path) -> dict[str, object]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return cast("dict[str, object]", payload)


def test_v5_spec_is_current_ssot_and_phase_never_regresses_before_p00(
    project_root: Path,
) -> None:
    spec = project_root / "AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md"
    state = yaml.safe_load((project_root / "state/V5_PROJECT_STATE.yaml").read_text())
    index = (project_root / "state/SPEC_INDEX.md").read_text(encoding="utf-8")

    assert hashlib.sha256(spec.read_bytes()).hexdigest() == EXPECTED_SPEC_SHA256
    assert EXPECTED_SPEC_SHA256 in index
    phase = state["current_phase"]
    expected_next = {
        "V5-P00": "V5-P01",
        "V5-P01": "V5-P02",
        "V5-P02": "V5-P03",
        "V5-P03": "V5-P04",
        "V5-P04": "V5-P05",
        "V5-P05": "V5-P06",
        "V5-P06": "V5-P07",
        "V5-P07": "V5-P08",
        "V5-P08": "V5-P09",
        "V5-P09": "V5-P10",
        "V5-P10": "V5-P11",
        "V5-P11": "V5-P12",
        "V5-P12": None,
    }
    assert phase in expected_next
    assert state["next_phase"] == expected_next[phase]
    if phase in {"V5-P00", "V5-P12"}:
        assert state["next_phase_authorized"] is False
    else:
        accepted = str(state["status"]).startswith("accepted")
        assert state["next_phase_authorized"] is accepted
    assert state["live_trading_locked"] is True
    assert state["order_submission_enabled"] is False


def test_non_real_tiers_fail_closed_for_alpha_promotion() -> None:
    assert {tier.value for tier in EvidenceTier} == {
        "FIXTURE",
        "SYNTHETIC",
        "DEVELOPMENT",
        "OOS_DEVELOPMENT",
        "FINAL_HOLDOUT",
        "PAPER_FORWARD",
        "SHADOW_FORWARD",
        "TESTNET_FORWARD",
        "CANARY_LIVE",
        "LIVE",
    }
    for tier in (EvidenceTier.FIXTURE, EvidenceTier.SYNTHETIC, EvidenceTier.DEVELOPMENT):
        with pytest.raises(ValueError, match="AQ-EVIDENCE-TIER-NOT-PROMOTABLE"):
            EvidenceDisclosure(
                evidence_tier=tier,
                alpha_promotion_eligible=True,
                source_artifacts=("reports/example.json",),
                reason_codes=("INVALID_PROMOTION_ATTEMPT",),
            )


def test_every_historical_report_has_one_hash_bound_non_promotable_tier(
    project_root: Path,
) -> None:
    migration = load_json(project_root / "reports/v5/P00/EVIDENCE_TIER_MIGRATION.json")
    artifact_objects = migration["artifacts"]
    assert isinstance(artifact_objects, list)
    artifacts = cast("list[dict[str, object]]", artifact_objects)
    historical_paths = sorted(
        path.relative_to(project_root).as_posix()
        for path in (project_root / "reports").rglob("*")
        if path.is_file() and (project_root / "reports/v5") not in path.parents
    )
    migrated_paths = [cast("str", item["path"]) for item in artifacts]

    assert migrated_paths == historical_paths
    assert (
        len(migrated_paths) == len(set(migrated_paths)) == cast("int", migration["artifact_count"])
    )
    assert migration["promotion_eligible_count"] == 0
    assert all(item["alpha_promotion_eligible"] is False for item in artifacts)
    for item in artifacts:
        path = project_root / cast("str", item["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == cast("str", item["sha256"])


def test_known_fixture_synthetic_and_placeholder_evidence_is_quarantined(
    project_root: Path,
) -> None:
    migration = load_json(project_root / "reports/v5/P00/EVIDENCE_TIER_MIGRATION.json")
    artifact_objects = migration["artifacts"]
    assert isinstance(artifact_objects, list)
    artifacts = {
        cast("str", item["path"]): item
        for item in cast("list[dict[str, object]]", artifact_objects)
    }
    audit = load_json(project_root / "reports/v5/P00/FIXTURE_AUDIT.json")

    assert artifacts["reports/backtests/p06-golden/run_manifest.json"]["evidence_tier"] == "FIXTURE"
    assert artifacts["reports/data/P09_TRANSLATION_EVIDENCE.json"]["evidence_tier"] == "SYNTHETIC"
    finding_objects = audit["placeholder_hash_findings"]
    assert isinstance(finding_objects, list)
    placeholder_paths = {
        cast("str", item["path"]) for item in cast("list[dict[str, object]]", finding_objects)
    }
    assert "reports/backtests/p06-golden/run_manifest.json" in placeholder_paths
    assert audit["short_window_findings"] == [
        {
            "path": "reports/backtests/p06-golden/run_manifest.json",
            "duration_seconds": 5.0,
            "disposition": "FIXTURE_ONLY_NO_ALPHA_PROMOTION",
        }
    ]
