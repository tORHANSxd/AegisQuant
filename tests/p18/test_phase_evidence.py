"""P18 Canary readiness, evidence, and deferred-acceptance gates."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

import yaml

from aegisquant.operations.live_readiness import SignedManifestEnvelope, verify_manifest
from scripts.ci import stage_commands


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p18_state_is_final_non_live_and_acceptance_remains_deferred(
    project_root: Path,
) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    previous = cast("dict[str, object]", state["previous_phase"])
    p17 = next(item for item in deferred if item["phase"] == "P17")
    assert state["current_phase"] == "P18"
    assert state["status"] == "in_progress"
    assert state["next_phase"] is None
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    assert previous["phase"] == "P17"
    assert previous["implementation_commit_sha"] == p17["implementation_commit_sha"]
    if (project_root / "reports/phases/P18/SUMMARY.md").is_file():
        assert state["implementation_status"] == "implementation_verified_acceptance_deferred"
        assert len(cast("str", state["implementation_commit_sha"])) == 40
    else:
        assert state["implementation_status"] == "planned"
    assert not (project_root / "reports/phases/P18/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p18_ci_has_readiness_evidence_and_mutation_gates(project_root: Path) -> None:
    commands = dict(stage_commands(project_root, "P18"))
    assert {"p18-live-readiness-evidence", "p18-mutation"} <= set(commands)


def test_p18_traceability_has_verified_tasks_and_deferred_acceptance(
    project_root: Path,
) -> None:
    matrix = project_root / "reports/phases/P18/REQUIREMENTS_TRACEABILITY.csv"
    with matrix.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(rows) == 21 and len({row["requirement_id"] for row in rows}) == 21
    assert len(tasks) == 14 and {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 7 and {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        for test in row["test"].split("; "):
            assert (project_root / test).exists(), row["requirement_id"]
        for evidence in row["evidence"].split("; "):
            assert (project_root / evidence).exists(), row["requirement_id"]


def test_p18_hard_gates_default_to_no_go_without_weighting(project_root: Path) -> None:
    evidence = _json(project_root / "reports/live_readiness/READINESS_EVIDENCE.json")
    review = cast("dict[str, object]", evidence["review"])
    gates = cast("list[dict[str, object]]", review["gates"])
    statuses = [item["status"] for item in gates]
    assert len(gates) == 14
    assert statuses.count("PASSED") == 7
    assert statuses.count("FAILED") == 1
    assert statuses.count("BLOCKED_EXTERNAL_INPUT") == 6
    assert review["decision"] == "NO_GO"
    assert review["weighted_score_used"] is False
    assert review["real_order_capability"] is False
    assert review["live_trading_locked"] is True
    assert review["manual_unlock_received"] is False
    assert cast("list[str]", review["blocking_reason_codes"])
    assert evidence["p00_p17_requirement_count"] == evidence["p00_p17_traceable_count"]
    assert evidence["p00_p17_incomplete_requirement_ids"] == []
    assert evidence["formal_acceptance_performed"] is False
    assert evidence["wall_clock_12h_or_24h_executed"] is False


def test_p18_account_and_preproduction_evidence_are_honest(project_root: Path) -> None:
    account = _json(project_root / "reports/live_readiness/ACCOUNT_CAPABILITY_EVIDENCE.json")
    preproduction = _json(project_root / "reports/live_readiness/PREPRODUCTION_EVIDENCE.json")
    assert account["state"] == "AWAITING_GO_PREREQUISITES_AND_USER_CONFIGURATION"
    assert account["credential_reference_present"] is False
    assert account["credential_values_accessed"] is False
    assert account["plaintext_credentials_requested_or_written"] is False
    assert account["real_account_connections"] == 0
    assert account["real_order_requests"] == 0
    assert account["research_or_ci_live_secret_access"] is False
    assert account["live_trading_locked"] is True
    assert preproduction["historical_paper_shadow_semantics_equal"] is True
    assert preproduction["startup_reconciliation_status"] == "CLEAR"
    assert preproduction["injected_reconciliation_difference_posture"] == "HALTED"
    assert preproduction["unexplained_reconciliation_difference_count"] == 0
    assert preproduction["tampered_ciphertext_rejected"] is True
    assert preproduction["shadow_write_capability"] is False
    assert preproduction["real_account_access_performed"] is False
    assert preproduction["real_canary_preproduction_run_performed"] is False


def test_p18_manifest_signature_is_integrity_only_and_artifacts_are_frozen(
    project_root: Path,
) -> None:
    payload = _json(project_root / "reports/live_readiness/CANARY_RELEASE_MANIFEST.json")
    envelope_keys = {
        "manifest",
        "manifest_sha256",
        "public_key_base64",
        "signature_base64",
        "signature_verified",
        "signature_purpose",
        "private_key_persisted",
        "authorization_capability",
    }
    envelope = SignedManifestEnvelope.model_validate_json(
        json.dumps({key: payload[key] for key in envelope_keys})
    )
    manifest = envelope.manifest
    assert verify_manifest(envelope) is True
    assert manifest.decision.value == "NO_GO"
    assert manifest.scope.selection_status.value == "NONE_NO_GO"
    assert manifest.scope.instrument_ids == ()
    assert manifest.live_trading_locked is True
    assert manifest.user_approval_received is False
    assert manifest.manual_unlock_received is False
    assert manifest.releaseable is False
    assert envelope.signature_purpose == "EVIDENCE_INTEGRITY_ONLY"
    assert envelope.private_key_persisted is False
    assert envelope.authorization_capability is False
    assert payload["key_trust"] == "UNTRUSTED_TEST_EVIDENCE_KEY"
    assert payload["live_authorization_issued"] is False
    assert (manifest.expires_at_utc - manifest.created_at_utc).total_seconds() <= 86_400
    for relative, expected in manifest.frozen_artifact_sha256.items():
        actual = hashlib.sha256((project_root / relative).read_bytes()).hexdigest()
        assert actual == expected


def test_p18_capital_stops_and_operating_cadence_are_fail_closed(
    project_root: Path,
) -> None:
    capital = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "reports/live_readiness/CAPITAL_LADDER.yaml").read_text("utf-8")
        ),
    )
    stops = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "reports/live_readiness/STOP_CONDITIONS.yaml").read_text("utf-8")
        ),
    )
    cadence = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "reports/live_readiness/CONTINUOUS_OPERATIONS.yaml").read_text("utf-8")
        ),
    )
    tiers = cast("list[dict[str, object]]", capital["tiers"])
    conditions = cast("list[dict[str, object]]", stops["conditions"])
    cadence_rows = cast("list[dict[str, object]]", cadence["cadence"])
    assert capital["decision"] == "NO_GO"
    assert capital["active_level"] == "LOCKED"
    assert capital["active_effective_capital_usd"] == "0"
    assert [item["activated"] for item in tiers] == [True, False, False]
    assert all(item["effective_capital_usd"] == "0" for item in tiers)
    assert all(item["max_gross_notional_usd"] == "0" for item in tiers)
    assert len(conditions) >= 6
    assert all(item["automatic"] is True for item in conditions)
    assert all(item["manual_resume_required"] is True for item in conditions)
    assert [item["frequency"] for item in cadence_rows] == [
        "DAILY",
        "WEEKLY",
        "MONTHLY",
        "QUARTERLY",
    ]
    assert cadence["active_live_schedule"] is False


def test_p18_required_readiness_reports_exist_without_acceptance(project_root: Path) -> None:
    report_dir = project_root / "reports/live_readiness"
    required = (
        "CANARY_RELEASE_MANIFEST.json",
        "GO_NO_GO.md",
        "OPEN_RISKS.md",
        "USER_APPROVAL_CHECKLIST.md",
        "CAPITAL_LADDER.yaml",
        "STOP_CONDITIONS.yaml",
        "ROLLBACK_PLAN.md",
    )
    assert all((report_dir / name).is_file() for name in required)
    checklist = (report_dir / "USER_APPROVAL_CHECKLIST.md").read_text(encoding="utf-8")
    assert "不要提供任何密码、Cookie、验证码、API Secret" in checklist
    assert "NO_GO" in (report_dir / "GO_NO_GO.md").read_text(encoding="utf-8")
    assert not (project_root / "reports/phases/P18/ACCEPTANCE.md").exists()


def test_p18_final_reports_are_consistent_when_published(project_root: Path) -> None:
    phase_dir = project_root / "reports/phases/P18"
    if not (phase_dir / "SUMMARY.md").is_file():
        return
    required = (
        "PLAN.md",
        "SUMMARY.md",
        "TEST_RESULTS.json",
        "RISKS.md",
        "NEXT_ACTIONS.md",
        "ADR_REFERENCES.md",
        "ARTIFACT_MANIFEST.json",
        "CI_RESULTS.json",
        "PYTHON_314_CONTRACT.json",
        "REQUIREMENTS_TRACEABILITY.csv",
    )
    assert all((phase_dir / name).is_file() for name in required)
    assert not (phase_dir / "ACCEPTANCE.md").exists()

    results = _json(phase_dir / "TEST_RESULTS.json")
    ci = _json(phase_dir / "CI_RESULTS.json")
    candidate = _json(phase_dir / "PYTHON_314_CONTRACT.json")
    mutation = _json(project_root / "reports/testing/P18_MUTATION_RESULTS.json")
    manifest = _json(phase_dir / "ARTIFACT_MANIFEST.json")
    assert results["status"] == "passed_implementation_acceptance_deferred"
    assert results["readiness_decision"] == "NO_GO"
    assert results["formal_acceptance"] == "deferred"
    assert ci["status"] == "passed" and ci["passed_count"] == ci["stage_count"]
    if os.environ.get("AEGISQUANT_CANDIDATE_ACTIVE") == "1":
        assert sys.version_info[:2] == (3, 14)
    else:
        assert candidate["status"] == "passed"
    assert mutation["status"] == "passed" and mutation["survived"] == 0
    assert manifest["phase"] == "P18"
    assert manifest["implementation_commit"] == results["implementation_commit"]
    assert cast("int", manifest["artifact_count"]) > 1000
    assert datetime.fromisoformat(cast("str", results["generated_at_utc"]).replace("Z", "+00:00"))
