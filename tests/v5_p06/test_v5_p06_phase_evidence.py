"""V5-P06 phase evidence, frozen-history, schemas, and promotion-boundary tests."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import cast

import yaml

from scripts.ci import stage_commands
from scripts.generate_artifact_manifest import check_frozen

REQUIRED_REPORTS = {
    "ACCEPTANCE.md",
    "ADR_REFERENCES.md",
    "ARTIFACT_MANIFEST.json",
    "CAUSAL_LAYER_EVIDENCE.json",
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
    "V5-P04": "7c7b8fd3acb199788bfb314b245c79cb66e5d5ebd17b50f1f5a672b5de830ece",  # pragma: allowlist secret
    "V5-P05": "8349c3502713c80375e0b8c13ff864a70215e11cf51f852e59f9f15dc8013cb7",  # pragma: allowlist secret
    "V5-P06": "0c4844ec87fe72ba4fb96d3a213e61b4b07d4c1773a8a8113966c5f9fa7db952",  # pragma: allowlist secret
}

P06_EVENT_SCHEMA_NAMES = {
    "aegisquant.causal-diagnostic-policy",
    "aegisquant.causal-diagnostics",
    "aegisquant.causal-effect-estimate",
    "aegisquant.causal-event-study-spec",
    "aegisquant.causal-matching-spec",
    "aegisquant.causal-point-estimate",
    "aegisquant.covariate-balance-report",
    "aegisquant.doubly-robust-spec",
    "aegisquant.matched-state-set",
    "aegisquant.placebo-test-result",
    "aegisquant.pre-treatment-fit-report",
    "aegisquant.pretrend-report",
    "aegisquant.propensity-overlap-report",
    "aegisquant.synthetic-control-result",
    "aegisquant.synthetic-control-spec",
}

P06_DATA_SCHEMA_NAMES = {
    "aegisquant.doubly-robust-observation",
    "aegisquant.event-response-dataset",
    "aegisquant.event-response-row",
    "aegisquant.historical-causal-state",
}


def load_mapping(path: Path) -> dict[str, object]:
    payload: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected mapping: {path}")
    return cast("dict[str, object]", payload)


def test_v5_p06_evidence_is_traceable_and_non_promotable(project_root: Path) -> None:
    evidence = json.loads(
        (project_root / "reports/v5/P06/CAUSAL_LAYER_EVIDENCE.json").read_text(encoding="utf-8")
    )
    assert evidence["phase"] == "V5-P06"
    assert evidence["result"] == "PASS"
    assert evidence["evidence_tier"] == "DEVELOPMENT"
    assert evidence["causal_claim_allowed"] is False
    assert evidence["alpha_promotion_eligible"] is False
    assert evidence["real_world_forecast_accuracy_claimed"] is False
    assert evidence["live_trading_locked"] is True
    assert evidence["order_submission_enabled"] is False
    assert all(evidence["checks"].values())

    for node_ids in evidence["acceptance_traceability"].values():
        assert node_ids
        for node_id in node_ids:
            test_path, separator, test_symbol = str(node_id).partition("::")
            assert separator == "::" and test_symbol.startswith("test_")
            source_path = project_root / test_path
            assert source_path.is_file()
            module = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            symbols = {
                node.name
                for node in ast.walk(module)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert test_symbol in symbols


def test_v5_p06_state_preserves_locks_and_frozen_history(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    forecast = load_mapping(project_root / "state/FORECAST_MODEL_STATE.yaml")
    assert state["current_phase"] in {
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
    assert forecast["promotion_decision"] == "NO_PROVEN_ALPHA"

    history = cast("list[dict[str, object]]", state["phase_history"])
    expected_history = (
        list(HISTORICAL_MANIFEST_SHA256)
        if state["current_phase"] in {"V5-P07", "V5-P08", "V5-P09", "V5-P10", "V5-P11", "V5-P12"}
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
        check_frozen(project_root, manifest_path, phase)


def test_v5_p06_schema_registries_expose_versioned_contracts(project_root: Path) -> None:
    event_registry = json.loads(
        (project_root / "schemas/events/registry.json").read_text(encoding="utf-8")
    )
    data_registry = json.loads(
        (project_root / "schemas/data/registry.json").read_text(encoding="utf-8")
    )
    event_contracts = {item["schema_name"]: item for item in event_registry["event_contracts"]}
    data_contracts = {item["schema_name"]: item for item in data_registry["data_contracts"]}
    assert set(event_contracts) >= P06_EVENT_SCHEMA_NAMES
    assert set(data_contracts) >= P06_DATA_SCHEMA_NAMES
    assert all(
        event_contracts[name]["schema_version"] == "1.0.0" for name in P06_EVENT_SCHEMA_NAMES
    )
    assert all(data_contracts[name]["schema_version"] == "1.0.0" for name in P06_DATA_SCHEMA_NAMES)


def test_v5_p06_ci_stage_checks_evidence_and_all_frozen_manifests(project_root: Path) -> None:
    names = [name for name, _ in stage_commands(project_root, "V5-P06")]
    assert "v5-p06-causal-layer-evidence" in names
    for phase in list(HISTORICAL_MANIFEST_SHA256)[:-1]:
        assert f"{phase.lower()}-frozen-manifest-self-consistency" in names


def test_accepted_v5_p06_is_bound_to_full_report_set(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    if (
        state["current_phase"] == "V5-P06"
        and state["status"] != "accepted_with_recorded_negative_result"
    ):
        assert state["next_phase_authorized"] is False
        return

    report_root = project_root / "reports/v5/P06"
    assert {path.name for path in report_root.iterdir() if path.is_file()} >= REQUIRED_REPORTS
    results = json.loads((report_root / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "V5-P06"
    assert results["status"] == "passed"
    assert results["failed_count"] == 0
    assert results["verification_scope"] == {
        "legacy_regression_through": "P18",
        "future_v5_phase_authorization": False,
        "meaning": "legacy regression coverage is not V5 phase acceptance",
    }
    manifest_path = report_root / "ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "V5-P06"
    assert manifest["implementation_commit_role"] == "SOURCE_REPOSITORY_BASELINE_ONLY"
    assert manifest["workspace_snapshot"]["kind"] == "CONTENT_ADDRESSED_WORKTREE"
    assert manifest["workspace_snapshot"]["commit_alone_reconstructs_snapshot"] is False
    expected_manifest_sha = (
        cast("dict[str, object]", state["artifact_manifest"])["sha256"]
        if state["current_phase"] == "V5-P06"
        else next(
            record["artifact_manifest_sha256"]
            for record in cast("list[dict[str, object]]", state["phase_history"])
            if record["phase"] == "V5-P06"
        )
    )
    assert expected_manifest_sha == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if state["current_phase"] == "V5-P06":
        assert state["next_phase"] == "V5-P07"
        assert state["next_phase_authorized"] is True
