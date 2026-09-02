"""P16 operations, security, evidence, and deferred-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml

from scripts.ci import stage_commands


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p16_state_is_non_live_and_acceptance_remains_deferred(project_root: Path) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    current = cast("str", state["current_phase"])
    assert current in {"P16", "P17", "P18"}
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    if current == "P16":
        previous = cast("dict[str, object]", state["previous_phase"])
        p15 = next(item for item in deferred if item["phase"] == "P15")
        assert state["status"] == "in_progress"
        assert state["next_phase"] == "P17"
        assert previous["phase"] == "P15"
        assert previous["evidence_commit_sha"] == p15["evidence_commit_sha"]
        if (project_root / "reports/phases/P16/SUMMARY.md").is_file():
            assert state["implementation_status"] == ("implementation_verified_acceptance_deferred")
            assert len(cast("str", state["implementation_commit_sha"])) == 40
        else:
            assert state["implementation_status"] == "planned"
    else:
        p16 = next(item for item in deferred if item["phase"] == "P16")
        assert p16["status"] == "implementation_verified_acceptance_deferred"
        assert len(cast("str", p16["implementation_commit_sha"])) == 40
        assert len(cast("str", p16["evidence_commit_sha"])) == 40
    assert not (project_root / "reports/phases/P16/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p16_ci_has_operational_evidence_gates(project_root: Path) -> None:
    commands = dict(stage_commands(project_root, "P16"))
    assert {
        "p16-image-lock",
        "p16-dashboards",
        "p16-operational-evidence",
        "p16-restore-evidence",
        "p16-mutation",
    } <= set(commands)


def test_p16_traceability_has_verified_tasks_and_deferred_acceptance(
    project_root: Path,
) -> None:
    matrix = project_root / "reports/phases/P16/REQUIREMENTS_TRACEABILITY.csv"
    with matrix.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(rows) == 19 and len({row["requirement_id"] for row in rows}) == 19
    assert len(tasks) == 12 and {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 7 and {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        for implementation in row["implementation"].split("; "):
            assert (project_root / implementation).exists(), row["requirement_id"]
        for test in row["test"].split("; "):
            assert (project_root / test).exists(), row["requirement_id"]
        for evidence in row["evidence"].split("; "):
            assert (project_root / evidence).exists(), row["requirement_id"]


def test_p16_observability_security_restore_and_release_are_evidenced(
    project_root: Path,
) -> None:
    telemetry = _json(project_root / "reports/observability/P16_TELEMETRY_EVIDENCE.json")
    dashboards = _json(project_root / "reports/observability/P16_DASHBOARD_EVIDENCE.json")
    alerts = _json(project_root / "reports/observability/P16_ALERT_EVIDENCE.json")
    security = _json(project_root / "reports/security/P16_SECURITY_EVIDENCE.json")
    restore = _json(project_root / "reports/operations/P16_RESTORE_DRILL.json")
    release = _json(project_root / "reports/deployment/P16_RELEASE_EVIDENCE.json")

    assert telemetry["log_correlation_matches"] is True
    assert telemetry["span_correlation_matches"] is True
    assert telemetry["metric_excludes_correlation_id"] is True
    assert telemetry["promtail_used"] is False
    assert dashboards["dashboard_count"] == 6
    assert alerts["sev0_delivery_outcome"] == "delivered"
    assert alerts["user_external_channel_delivery_verified"] is False
    assert security["live_secret_denied_for_all_roles"] is True
    assert security["real_account_connections"] == 0
    assert restore["status"] == "passed" and restore["verification_equal"] is True
    assert restore["tampered_ciphertext_rejected"] is True
    assert release["failed_posture"] == "HALTED"
    assert release["rollback_manual_resume_required"] is True


def test_p16_final_reports_are_consistent_when_published(project_root: Path) -> None:
    phase_dir = project_root / "reports/phases/P16"
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
    mutation = _json(project_root / "reports/testing/P16_MUTATION_RESULTS.json")
    manifest = _json(phase_dir / "ARTIFACT_MANIFEST.json")
    assert results["status"] == "passed_implementation_acceptance_deferred"
    assert results["formal_acceptance"] == "deferred"
    assert ci["status"] == "passed" and ci["passed_count"] == ci["stage_count"]
    assert candidate["status"] == "passed"
    assert mutation["status"] == "passed" and mutation["survived"] == 0
    assert manifest["phase"] == "P16"
    assert manifest["implementation_commit"] == results["implementation_commit"]
    assert cast("int", manifest["artifact_count"]) > 1000
