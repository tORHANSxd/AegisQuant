"""Consolidated P00-P18 acceptance audit gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import yaml

from scripts.generate_system_acceptance import check


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_system_acceptance_outputs_are_reproducible(project_root: Path) -> None:
    check(project_root)


def test_all_deferred_acceptance_requirements_are_traced(project_root: Path) -> None:
    matrix = project_root / "reports/acceptance/REQUIREMENTS_TRACEABILITY.csv"
    with matrix.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 93
    assert len({row["requirement_id"] for row in rows}) == 93
    assert {row["phase"] for row in rows} == {f"P{number:02d}" for number in range(5, 19)}
    assert [
        row["requirement_id"] for row in rows if row["intrinsic_result"] == "BLOCKED_EXTERNAL_INPUT"
    ] == [
        "P12-A01",
        "P16-A03",
    ]
    assert [
        row["requirement_id"] for row in rows if row["intrinsic_result"] == "WAIVED_BY_OWNER"
    ] == ["P13-A01"]


def test_formal_acceptance_stops_at_real_testnet_without_fabrication(
    project_root: Path,
) -> None:
    audit = _json(project_root / "reports/acceptance/SYSTEM_ACCEPTANCE.json")
    testnet = _json(project_root / "reports/execution/P12_TESTNET_CAPABILITY.json")
    assert audit["decision"] == "BLOCKED_EXTERNAL_INPUT"
    assert audit["first_blocking_phase"] == "P12"
    assert audit["phase_acceptance_reports_issued"] is False
    assert testnet["real_testnet_acceptance"] == "blocked_external_input"
    assert testnet["credential_reference_received"] is False
    for number in range(5, 19):
        assert not (project_root / f"reports/phases/P{number:02d}/ACCEPTANCE.md").exists()


def test_non_live_boundary_and_no_go_remain_authoritative(project_root: Path) -> None:
    audit = _json(project_root / "reports/acceptance/SYSTEM_ACCEPTANCE.json")
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    readiness = _json(project_root / "reports/live_readiness/READINESS_EVIDENCE.json")
    review = cast("dict[str, object]", readiness["review"])
    safety = cast("dict[str, object]", audit["safety"])
    assert state["live_trading_locked"] is True
    assert audit["canary_readiness"] == "NO_GO"
    assert review["decision"] == "NO_GO"
    assert review["real_order_capability"] is False
    assert safety["real_account_connections"] == 0
    assert safety["real_order_requests"] == 0
    assert safety["plaintext_secret_requested_or_written"] is False


def test_state_records_the_blocked_acceptance_attempt_when_published(
    project_root: Path,
) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    record = cast("dict[str, object]", state["formal_acceptance_audit"])
    assert record["decision"] == "blocked_external_input"
    assert record["first_blocking_phase"] == "P12"
    assert record["phase_acceptance_reports_issued"] is False
    assert record["live_trading_locked"] is True
