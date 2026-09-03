"""V5-P12 evidence, Schema, frozen-history, ADR, and CI wiring tests."""

from __future__ import annotations

import ast
import hashlib
import json
import os
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
    "CANARY_READINESS_EVIDENCE.json",
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
    "V5-P09": "a7d259e885ea3a793b34ed99c12f754a1ab4dfc2c1dac0f310549f89a231f785",  # pragma: allowlist secret
    "V5-P10": "fee3a63ca5b6c4268a025e5cbe6d4f3cc59d0ad3403b2f78d055e9ba1ab495b0",  # pragma: allowlist secret
    "V5-P11": "da72fc4b7be181f800a7edec2f76a0edb0ab96fa654fe4edeab55052b03960b0",  # pragma: allowlist secret
}

P12_EVENT_SCHEMA_NAMES = {
    "aegisquant.v5-binance-testnet-run-evidence",
    "aegisquant.v5-external-alert-delivery-receipt",
    "aegisquant.v5-testnet-risk-authorization-receipt",
    "aegisquant.v5-p12-evidence-bundle",
    "aegisquant.v5-p12-canary-readiness-assessment",
}

P12_DATA_SCHEMA_NAMES = {
    "aegisquant.v5-protected-timestamp-receipt",
    "aegisquant.v5-testnet-reconciliation-receipt",
    "aegisquant.v5-p12-evidence-attestation",
    "aegisquant.v5-p12-gate-result",
}

P12_CONFIG_SCHEMA_NAMES = {"aegisquant.v5-p12-readiness-policy"}


def load_mapping(path: Path) -> dict[str, object]:
    payload: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected mapping: {path}")
    return cast("dict[str, object]", payload)


def test_v5_p12_evidence_records_real_external_absence_and_no_promotion(
    project_root: Path,
) -> None:
    evidence = json.loads(
        (project_root / "reports/v5/P12/CANARY_READINESS_EVIDENCE.json").read_text(encoding="utf-8")
    )
    assert evidence["phase"] == "V5-P12"
    assert evidence["result"] == "PASS_WITH_RECORDED_NEGATIVE_RESULTS"
    assert evidence["promotion_decision"] == "NO_PROMOTION"
    assert evidence["required_next_action"] == "EXTEND_PAPER"
    assert evidence["evidence_tier"] == "DEVELOPMENT"
    assert evidence["real_paper_calendar_days_observed"] == 0
    assert evidence["real_shadow_calendar_days_observed"] == 0
    assert evidence["real_binance_testnet_evidence_present"] is False
    assert evidence["testnet_credential_reference_present"] is False
    assert evidence["testnet_network_requests_performed"] == 0
    assert evidence["external_alert_delivery_evidence_present"] is False
    assert evidence["canary_review_ready"] is False
    assert evidence["live_order_submission_enabled"] is False
    assert evidence["live_trading_locked"] is True
    assert evidence["global_promotion_gate_evaluated"] is False
    assert evidence["global_promotion_decision"] == "NO_PROMOTION"
    assert all(evidence["checks"].values())

    for artifact in evidence["source_artifact_sha256"]:
        artifact_path = project_root / artifact["path"]
        assert artifact_path.is_file()
        assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact["sha256"]

    assessment = evidence["current_assessment"]
    assert assessment["gate_count"] == 7
    assert assessment["passed_gate_count"] == assessment["failed_gate_count"] == 0
    assert assessment["blocked_gate_count"] == 7
    assert assessment["decision"] == "NO_PROMOTION"
    assert assessment["weighted_score_used"] is False

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


def test_v5_p12_state_preserves_locks_and_p00_p11_history(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    forecast = load_mapping(project_root / "state/FORECAST_MODEL_STATE.yaml")
    assert state["current_phase"] == "V5-P12"
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


def test_v5_p12_schema_registries_expose_all_new_contracts(project_root: Path) -> None:
    event_registry = json.loads(
        (project_root / "schemas/events/registry.json").read_text(encoding="utf-8")
    )
    data_registry = json.loads(
        (project_root / "schemas/data/registry.json").read_text(encoding="utf-8")
    )
    event_contracts = {item["schema_name"]: item for item in event_registry["event_contracts"]}
    data_contracts = {item["schema_name"]: item for item in data_registry["data_contracts"]}
    config_contracts = {contract.schema_name: contract for contract in CONFIG_CONTRACTS}
    assert set(event_contracts) >= P12_EVENT_SCHEMA_NAMES
    assert set(data_contracts) >= P12_DATA_SCHEMA_NAMES
    assert set(config_contracts) >= P12_CONFIG_SCHEMA_NAMES
    assert all(
        event_contracts[name]["schema_version"] == "1.0.0"
        and event_contracts[name]["compatibility"] == "NONE"
        for name in P12_EVENT_SCHEMA_NAMES
    )
    assert all(
        data_contracts[name]["schema_version"] == "1.0.0"
        and data_contracts[name]["compatibility"] == "NONE"
        for name in P12_DATA_SCHEMA_NAMES
    )
    assert all(
        config_contracts[name].version == "1.0.0" and config_contracts[name].compatibility == "NONE"
        for name in P12_CONFIG_SCHEMA_NAMES
    )


def test_v5_p12_ci_checks_evidence_and_all_historical_manifests(project_root: Path) -> None:
    names = [name for name, _ in stage_commands(project_root, "V5-P12")]
    assert "v5-p12-canary-readiness-evidence" in names
    for phase in HISTORICAL_MANIFEST_SHA256:
        assert f"{phase.lower()}-frozen-manifest-self-consistency" in names


def test_p12_adr_accepts_only_manual_review_readiness(project_root: Path) -> None:
    text = (project_root / "docs/adr/ADR-0035-v5-p12-testnet-canary-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "状态：Accepted" in text
    assert "七项必须全部 PASS" in text
    assert "不得自动解锁 Live" in text
    assert "0 PASS / 0 FAIL / 7 BLOCKED_EXTERNAL_INPUT" in text


def test_legacy_simulator_and_no_go_reports_are_not_promoted(project_root: Path) -> None:
    capability = json.loads(
        (project_root / "reports/execution/P12_TESTNET_CAPABILITY.json").read_text(encoding="utf-8")
    )
    legacy = json.loads(
        (project_root / "reports/live_readiness/READINESS_DECISION.json").read_text(
            encoding="utf-8"
        )
    )
    assert capability["capability"]["network_requests_performed"] == 0
    assert capability["capability"]["real_account_access_performed"] is False
    assert capability["real_testnet_acceptance"] == "blocked_external_input"
    assert legacy["decision"] == "NO_GO"
    assert legacy["real_order_capability"] is False


def test_accepted_v5_p12_is_bound_to_complete_report_set(project_root: Path) -> None:
    state = load_mapping(project_root / "state/V5_PROJECT_STATE.yaml")
    if state["status"] != "accepted_with_recorded_negative_result":
        assert state["next_phase_authorized"] is False
        return

    report_root = project_root / "reports/v5/P12"
    assert {path.name for path in report_root.iterdir() if path.is_file()} >= REQUIRED_REPORTS
    results = json.loads((report_root / "TEST_RESULTS.json").read_text(encoding="utf-8"))
    assert results["phase"] == "V5-P12"
    # TEST_RESULTS is the output of the active CI run, so its previous value cannot also be
    # a prerequisite of that same run. The final file is checked normally after CI exits.
    if os.environ.get("AEGISQUANT_CI_BUILDING_TEST_RESULTS") != "V5-P12":
        assert results["status"] == "passed"
        assert results["failed_count"] == 0
    manifest_path = report_root / "ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "V5-P12"
    assert manifest["implementation_commit_role"] == "SOURCE_REPOSITORY_BASELINE_ONLY"
    assert manifest["workspace_snapshot"]["kind"] == "CONTENT_ADDRESSED_WORKTREE"
    assert manifest["workspace_snapshot"]["commit_alone_reconstructs_snapshot"] is False
