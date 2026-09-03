"""V5-P09 phase evidence, schema, frozen-history, and CI wiring tests."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import cast

import yaml

from scripts.ci import stage_commands
from scripts.generate_artifact_manifest import check_frozen
from scripts.generate_schemas import CONFIG_CONTRACTS

REQUIRED_REPORTS = {
    "ACCEPTANCE.md",
    "ADR_REFERENCES.md",
    "ARTIFACT_MANIFEST.json",
    "FORECAST_GOVERNANCE_EVIDENCE.json",
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
    "V5-P07": "f85bff1ab3b498b5e4dde4d11b4e7f38de5a7f551bfd14c2f80e7f516b75810e",  # pragma: allowlist secret
    "V5-P08": "10a6316a524df685dbec90d5c580ceb53c5720f149e686f651420a90d73cf194",  # pragma: allowlist secret
}

P09_EVENT_SCHEMA_NAMES = {
    "aegisquant.v5-adaptive-conformal-report",
    "aegisquant.v5-forecast-governance-report",
    "aegisquant.v5-independent-skeptic-assessment",
    "aegisquant.v5-meta-reasoner-recommendation",
    "aegisquant.v5-regime-routing-decision",
}

P09_DATA_SCHEMA_NAMES = {
    "aegisquant.v5-interval-coverage-window",
    "aegisquant.v5-reasoning-context",
    "aegisquant.v5-statistical-weight-proposal",
}

P09_CONFIG_SCHEMA_NAMES = {
    "aegisquant.v5-adaptive-conformal-policy",
    "aegisquant.v5-dynamic-stacking-policy",
}


def load_mapping(path: Path) -> dict[str, object]:
    payload: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected mapping: {path}")
    return cast("dict[str, object]", payload)


def test_v5_p09_evidence_is_traceable_fail_closed_and_non_promotable(
    project_root: Path,
) -> None:
    evidence = json.loads(
        (project_root / "reports/v5/P09/FORECAST_GOVERNANCE_EVIDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["phase"] == "V5-P09"
    assert evidence["result"] == "PASS_WITH_RECORDED_NEGATIVE_RESULTS"
    assert evidence["evidence_tier"] == "DEVELOPMENT"
    assert evidence["alpha_promotion_eligible"] is False
    assert evidence["real_world_forecast_accuracy_claimed"] is False
    assert evidence["real_world_interval_coverage_claimed"] is False
    assert evidence["forward_evidence_present"] is False
    assert evidence["final_holdout_opened"] is False
    assert evidence["order_submission_enabled"] is False
    assert evidence["live_trading_locked"] is True
    assert all(evidence["checks"].values())
    assert all(evidence["negative_controls"].values())

    for node_ids in evidence["acceptance_traceability"].values():
        assert node_ids
        for node_id in node_ids:
            test_path, separator, test_symbol = str(node_id).partition("::")
            assert separator == "::" and test_symbol.startswith("test_")
            source_path = project_root / test_path
            module = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            symbols = {
                node.name
                for node in ast.walk(module)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert test_symbol in symbols


def test_v5_p09_state_preserves_locks_and_p00_p08_history(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    forecast = load_mapping(project_root / "state/FORECAST_MODEL_STATE.yaml")
    assert state["current_phase"] in {"V5-P09", "V5-P10", "V5-P11", "V5-P12"}
    assert state["alpha_promotion_eligible"] is False
    assert state["live_trading_locked"] is True
    assert state["order_submission_enabled"] is False
    assert state["real_account_connected"] is False
    assert forecast["promotion_decision"] == "NO_PROVEN_ALPHA"
    assert forecast["live_trading_locked"] is True

    history = cast("list[dict[str, object]]", state["phase_history"])
    historical = [item for item in history if item["phase"] in HISTORICAL_MANIFEST_SHA256]
    assert [item["phase"] for item in historical] == list(HISTORICAL_MANIFEST_SHA256)
    for record in historical:
        phase = str(record["phase"])
        manifest_path = project_root / str(record["artifact_manifest_path"])
        expected = HISTORICAL_MANIFEST_SHA256[phase]
        assert record["artifact_manifest_sha256"] == expected
        assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == expected
        check_frozen(project_root, manifest_path, phase)


def test_v5_p09_schema_registries_expose_all_new_contracts(project_root: Path) -> None:
    event_registry = json.loads(
        (project_root / "schemas/events/registry.json").read_text(encoding="utf-8")
    )
    data_registry = json.loads(
        (project_root / "schemas/data/registry.json").read_text(encoding="utf-8")
    )
    config_contracts = {contract.schema_name: contract for contract in CONFIG_CONTRACTS}
    event_contracts = {item["schema_name"]: item for item in event_registry["event_contracts"]}
    data_contracts = {item["schema_name"]: item for item in data_registry["data_contracts"]}
    assert set(event_contracts) >= P09_EVENT_SCHEMA_NAMES
    assert set(data_contracts) >= P09_DATA_SCHEMA_NAMES
    assert set(config_contracts) >= P09_CONFIG_SCHEMA_NAMES
    assert all(
        event_contracts[name]["schema_version"] == "1.0.0"
        and event_contracts[name]["compatibility"] == "NONE"
        for name in P09_EVENT_SCHEMA_NAMES
    )
    assert all(
        data_contracts[name]["schema_version"] == "1.0.0"
        and data_contracts[name]["compatibility"] == "NONE"
        for name in P09_DATA_SCHEMA_NAMES
    )
    assert all(
        config_contracts[name].version == "1.0.0" and config_contracts[name].compatibility == "NONE"
        for name in P09_CONFIG_SCHEMA_NAMES
    )


def test_v5_p09_ci_stage_checks_evidence_and_frozen_manifests(project_root: Path) -> None:
    names = [name for name, _ in stage_commands(project_root, "V5-P09")]
    assert "v5-p09-forecast-governance-evidence" in names
    for phase in HISTORICAL_MANIFEST_SHA256:
        assert f"{phase.lower()}-frozen-manifest-self-consistency" in names


def test_accepted_v5_p09_is_bound_to_complete_report_set(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    if (
        state["current_phase"] == "V5-P09"
        and state["status"] != "accepted_with_recorded_negative_result"
    ):
        assert state["next_phase_authorized"] is False
        return

    report_root = project_root / "reports/v5/P09"
    assert {path.name for path in report_root.iterdir() if path.is_file()} >= REQUIRED_REPORTS
    results = json.loads((report_root / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "V5-P09"
    assert results["status"] == "passed"
    assert results["failed_count"] == 0
    assert results["verification_scope"] == {
        "legacy_regression_through": "P18",
        "future_v5_phase_authorization": False,
        "meaning": "legacy regression coverage is not V5 phase acceptance",
    }
    manifest_path = report_root / "ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "V5-P09"
    assert manifest["implementation_commit_role"] == "SOURCE_REPOSITORY_BASELINE_ONLY"
    assert manifest["workspace_snapshot"]["kind"] == "CONTENT_ADDRESSED_WORKTREE"
    assert manifest["workspace_snapshot"]["commit_alone_reconstructs_snapshot"] is False
