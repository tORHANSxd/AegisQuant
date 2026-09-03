"""V5-P02 phase evidence, governance, and fail-closed promotion tests."""

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
    "SOURCE_PROVENANCE_EVIDENCE.json",
    "SUMMARY.md",
    "TEST_RESULTS.json",
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


def test_v5_p02_source_provenance_evidence_is_complete(project_root: Path) -> None:
    evidence = json.loads(
        (project_root / "reports/v5/P02/SOURCE_PROVENANCE_EVIDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["phase"] == "V5-P02"
    assert evidence["result"] == "PASS"
    assert evidence["evidence_tier"] == "DEVELOPMENT"
    assert evidence["alpha_promotion_eligible"] is False
    assert evidence["calibrated_truth_model_present"] is False
    assert evidence["live_trading_locked"] is True
    assert evidence["source_registry"]["entry_count"] == 4
    assert evidence["c2pa_runtime"]["package_version"] == "0.37.8"
    assert evidence["c2pa_runtime"]["remote_manifest_fetch_enabled"] is False
    assert evidence["c2pa_runtime"]["ocsp_fetch_enabled"] is False
    assert all(evidence["checks"].values())
    assert set(evidence["acceptance_traceability"]) == set(evidence["checks"])
    for node_id in evidence["acceptance_traceability"].values():
        test_path = str(node_id).split("::", maxsplit=1)[0]
        assert (project_root / test_path).is_file()


def test_v5_p02_state_preserves_truth_alpha_and_live_locks(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    source = load_mapping(project_root / "state/SOURCE_RELIABILITY_STATE.yaml")
    truth = load_mapping(project_root / "state/TRUTH_MODEL_STATE.yaml")
    forecast = load_mapping(project_root / "state/FORECAST_MODEL_STATE.yaml")

    assert state["current_phase"] in {
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
    assert state["status"] in {"in_progress", "accepted_with_recorded_negative_result"}
    assert state["alpha_promotion_eligible"] is False
    assert state["live_trading_locked"] is True
    assert state["order_submission_enabled"] is False
    assert state["real_account_connected"] is False
    assert source["state"] in {
        "SOURCE_REGISTRY_IDENTITY_AND_COMPROMISE_IMPLEMENTED_UNCALIBRATED",
        "RELIABILITY_DECAY_IMPLEMENTED_DEVELOPMENT_ONLY",
    }
    assert source["promotion_decision"] == "NO_PROMOTION"
    assert truth["state"] in {
        "SOURCE_PROVENANCE_INPUTS_IMPLEMENTED_UNCALIBRATED",
        "EVIDENCE_RETRIEVAL_AND_INDEPENDENCE_IMPLEMENTED_UNCALIBRATED",
        "TRUTH_COUNCIL_CALIBRATED_DEVELOPMENT_ONLY",
    }
    assert truth["promotion_decision"] == "NO_PROMOTION"
    assert forecast["promotion_decision"] == "NO_PROVEN_ALPHA"


def test_accepted_v5_p02_is_bound_to_full_report_set(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    if (
        state["current_phase"] == "V5-P02"
        and state["status"] != "accepted_with_recorded_negative_result"
    ):
        assert state["next_phase_authorized"] is False
        return

    report_root = project_root / "reports/v5/P02"
    assert {path.name for path in report_root.iterdir() if path.is_file()} >= REQUIRED_REPORTS
    results = json.loads((report_root / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "V5-P02"
    assert results["status"] == "passed"
    assert results["failed_count"] == 0
    assert results["verification_scope"] == {
        "legacy_regression_through": "P18",
        "future_v5_phase_authorization": False,
        "meaning": "legacy regression coverage is not V5 phase acceptance",
    }
    manifest_path = report_root / "ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "V5-P02"
    assert manifest["implementation_commit_role"] == "SOURCE_REPOSITORY_BASELINE_ONLY"
    assert manifest["workspace_snapshot"]["kind"] == "CONTENT_ADDRESSED_WORKTREE"
    assert manifest["workspace_snapshot"]["commit_alone_reconstructs_snapshot"] is False
    assert (
        phase_manifest_sha(state, "V5-P02")
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    if state["current_phase"] == "V5-P02":
        assert state["next_phase"] == "V5-P03"
        assert state["next_phase_authorized"] is True
