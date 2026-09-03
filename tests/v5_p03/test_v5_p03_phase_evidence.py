"""V5-P03 phase evidence, immutable history, and promotion-boundary tests."""

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
    "EVIDENCE_RETRIEVAL_INDEPENDENCE.json",
    "NEGATIVE_RESULTS.md",
    "NEXT_ACTIONS.md",
    "PLAN.md",
    "RISKS.md",
    "SUMMARY.md",
    "TEST_RESULTS.json",
}

HISTORICAL_MANIFEST_SHA256 = {
    "V5-P00": "2deb28f491cb90bde6e113bad5bd615eeeb015b20d783c8943021775d35f0a61",  # pragma: allowlist secret
    "V5-P01": "7d09e5c03137b36bdb7d8edf3a5cedc5f53dabf012853af83e0b56703c92be3a",  # pragma: allowlist secret
    "V5-P02": "c23a6d9971dc351d64efec1c07bb0014eccd6872d1606692c8e88ad1ed891b16",  # pragma: allowlist secret
    "V5-P03": "bced70bc7acfb9cddc3a8a45c3673e969800b90b037c85a2b9ce8cca31ac40ea",  # pragma: allowlist secret
}


def load_mapping(path: Path) -> dict[str, object]:
    payload: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected mapping: {path}")
    return cast("dict[str, object]", payload)


def test_v5_p03_evidence_is_complete_and_traceable(project_root: Path) -> None:
    evidence = json.loads(
        (project_root / "reports/v5/P03/EVIDENCE_RETRIEVAL_INDEPENDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["phase"] == "V5-P03"
    assert evidence["result"] == "PASS"
    assert evidence["evidence_tier"] == "DEVELOPMENT"
    assert evidence["alpha_promotion_eligible"] is False
    assert evidence["calibrated_truth_model_present"] is False
    assert evidence["live_trading_locked"] is True
    assert evidence["search_plan"]["query_lane_count"] == 6
    assert evidence["search_plan"]["probability_aggregation"] == ("CALIBRATED_MODEL_NOT_AGENT_VOTE")
    assert evidence["independence"]["article_count"] == 10
    assert evidence["independence"]["independent_evidence_count"] == 1
    assert evidence["independence"]["evidence_dependency_score"] == "0.9"
    assert all(evidence["checks"].values())
    assert set(evidence["acceptance_traceability"]) == set(evidence["checks"])
    for node_id in evidence["acceptance_traceability"].values():
        test_path = str(node_id).split("::", maxsplit=1)[0]
        assert (project_root / test_path).is_file()


def test_v5_p03_state_preserves_locks_and_historical_manifest_hashes(
    project_root: Path,
) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    truth = load_mapping(project_root / "state/TRUTH_MODEL_STATE.yaml")
    source = load_mapping(project_root / "state/SOURCE_RELIABILITY_STATE.yaml")
    forecast = load_mapping(project_root / "state/FORECAST_MODEL_STATE.yaml")

    assert state["current_phase"] in {
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
    assert truth["state"] in {
        "EVIDENCE_RETRIEVAL_AND_INDEPENDENCE_IMPLEMENTED_UNCALIBRATED",
        "TRUTH_COUNCIL_CALIBRATED_DEVELOPMENT_ONLY",
    }
    assert truth["promotion_decision"] == "NO_PROMOTION"
    assert source["promotion_decision"] == "NO_PROMOTION"
    assert forecast["promotion_decision"] == "NO_PROVEN_ALPHA"

    history = cast("list[dict[str, object]]", state["phase_history"])
    expected_history = (
        list(HISTORICAL_MANIFEST_SHA256)
        if state["current_phase"]
        in {
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
        else list(HISTORICAL_MANIFEST_SHA256)[:-1]
    )
    relevant_history = [
        record for record in history if record["phase"] in HISTORICAL_MANIFEST_SHA256
    ]
    assert [record["phase"] for record in relevant_history] == expected_history
    for record in relevant_history:
        phase = str(record["phase"])
        expected = HISTORICAL_MANIFEST_SHA256[phase]
        assert record["status"] == "accepted_with_recorded_negative_result"
        assert str(record["acceptance_decision"]).startswith("PASS_WITH_RECORDED_NEGATIVE_RESULT")
        assert str(record["accepted_at_utc"]).endswith("Z")
        assert record["artifact_manifest_sha256"] == expected
        manifest_path = project_root / str(record["artifact_manifest_path"])
        assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == expected


def test_accepted_v5_p03_is_bound_to_full_report_set(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    if (
        state["current_phase"] == "V5-P03"
        and state["status"] != "accepted_with_recorded_negative_result"
    ):
        assert state["next_phase_authorized"] is False
        return

    report_root = project_root / "reports/v5/P03"
    assert {path.name for path in report_root.iterdir() if path.is_file()} >= REQUIRED_REPORTS
    results = json.loads((report_root / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "V5-P03"
    assert results["status"] == "passed"
    assert results["failed_count"] == 0
    assert results["verification_scope"] == {
        "legacy_regression_through": "P18",
        "future_v5_phase_authorization": False,
        "meaning": "legacy regression coverage is not V5 phase acceptance",
    }
    manifest_path = report_root / "ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "V5-P03"
    assert manifest["implementation_commit_role"] == "SOURCE_REPOSITORY_BASELINE_ONLY"
    assert manifest["workspace_snapshot"]["kind"] == "CONTENT_ADDRESSED_WORKTREE"
    assert manifest["workspace_snapshot"]["commit_alone_reconstructs_snapshot"] is False
    expected_sha = (
        cast("dict[str, object]", state["artifact_manifest"])["sha256"]
        if state["current_phase"] == "V5-P03"
        else next(
            record["artifact_manifest_sha256"]
            for record in cast("list[dict[str, object]]", state["phase_history"])
            if record["phase"] == "V5-P03"
        )
    )
    assert expected_sha == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if state["current_phase"] == "V5-P03":
        assert state["next_phase"] == "V5-P04"
        assert state["next_phase_authorized"] is True
