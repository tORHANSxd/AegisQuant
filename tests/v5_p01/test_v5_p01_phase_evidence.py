"""V5-P01 phase evidence and fail-closed promotion boundary tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import yaml

REQUIRED_REPORTS = {
    "ACCEPTANCE.md",
    "ADR_REFERENCES.md",
    "ARTIFACT_MANIFEST.json",
    "NEGATIVE_RESULTS.md",
    "NEXT_ACTIONS.md",
    "PLAN.md",
    "RISKS.md",
    "SUMMARY.md",
    "TEST_RESULTS.json",
    "TRUTH_CONTRACT_EVIDENCE.json",
}


def load_mapping(path: Path) -> dict[str, object]:
    payload: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected mapping: {path}")
    return cast("dict[str, object]", payload)


def phase_manifest_sha(state: dict[str, object], phase: str) -> object:
    if state["current_phase"] == phase:
        return cast("dict[str, object]", state["artifact_manifest"])["sha256"]
    history = cast("list[dict[str, object]]", state["phase_history"])
    return next(
        record["artifact_manifest_sha256"] for record in history if record["phase"] == phase
    )


def test_v5_p01_contract_evidence_is_complete(project_root: Path) -> None:
    evidence = json.loads(
        (project_root / "reports/v5/P01/TRUTH_CONTRACT_EVIDENCE.json").read_text(encoding="utf-8")
    )
    assert evidence["phase"] == "V5-P01"
    assert evidence["result"] == "PASS"
    assert evidence["evidence_tier"] == "DEVELOPMENT"
    assert evidence["alpha_promotion_eligible"] is False
    assert evidence["calibrated_truth_model_present"] is False
    assert evidence["live_trading_locked"] is True
    assert all(evidence["checks"].values())


def test_v5_p01_state_never_claims_calibration_or_alpha(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    truth = load_mapping(project_root / "state/TRUTH_MODEL_STATE.yaml")
    forecast = load_mapping(project_root / "state/FORECAST_MODEL_STATE.yaml")

    assert state["current_phase"] in {
        "V5-P01",
        "V5-P02",
        "V5-P03",
        "V5-P04",
        "V5-P05",
        "V5-P06",
        "V5-P07",
        "V5-P08",
        "V5-P09",
        "V5-P10",
        "V5-P11",
        "V5-P12",
    }
    assert state["alpha_promotion_eligible"] is False
    assert state["live_trading_locked"] is True
    assert state["order_submission_enabled"] is False
    assert truth["state"] in {
        "CONTRACTS_IMPLEMENTED_UNCALIBRATED",
        "SOURCE_PROVENANCE_INPUTS_IMPLEMENTED_UNCALIBRATED",
        "EVIDENCE_RETRIEVAL_AND_INDEPENDENCE_IMPLEMENTED_UNCALIBRATED",
        "TRUTH_COUNCIL_CALIBRATED_DEVELOPMENT_ONLY",
    }
    assert truth["promotion_decision"] == "NO_PROMOTION"
    assert forecast["promotion_decision"] == "NO_PROVEN_ALPHA"


def test_accepted_v5_p01_is_bound_to_full_report_set(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    if state["current_phase"] == "V5-P01" and state["status"] not in {
        "accepted",
        "accepted_with_recorded_negative_result",
    }:
        return

    report_root = project_root / "reports/v5/P01"
    assert {path.name for path in report_root.iterdir() if path.is_file()} >= REQUIRED_REPORTS
    results = json.loads((report_root / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "V5-P01"
    assert results["status"] == "passed"
    assert results["failed_count"] == 0
    manifest_path = report_root / "ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "V5-P01"
    assert manifest["implementation_commit_role"] == "SOURCE_REPOSITORY_BASELINE_ONLY"
    assert manifest["workspace_snapshot"]["kind"] == "CONTENT_ADDRESSED_WORKTREE"
    assert manifest["workspace_snapshot"]["commit_alone_reconstructs_snapshot"] is False
    expected_sha256 = phase_manifest_sha(state, "V5-P01")
    assert expected_sha256 == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
