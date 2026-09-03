from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import cast

from scripts.generate_v5_p06_evidence import OUTPUT, build_payload


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _sequence(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast("list[object]", value)


def test_checked_in_p06_evidence_matches_recomputed_payload() -> None:
    checked_in: object = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert checked_in == build_payload()


def test_p06_evidence_proves_estimators_diagnostics_and_fail_closed_gate() -> None:
    payload = build_payload()
    checks = _mapping(payload["checks"])
    assert checks and all(checks.values())
    assert payload["phase"] == "V5-P06"
    assert payload["evidence_tier"] == "DEVELOPMENT"
    assert payload["causal_claim_allowed"] is False
    assert payload["alpha_promotion_eligible"] is False
    assert payload["live_trading_locked"] is True
    assert payload["order_submission_enabled"] is False

    diagnostics = _mapping(payload["diagnostics"])
    assert diagnostics["passed"] is True
    placebo_kinds = {_mapping(item)["kind"] for item in _sequence(diagnostics["placebo_tests"])}
    assert placebo_kinds == {"EVENT_TIMESTAMP", "ASSET", "TREATMENT_PERMUTATION"}

    negative = _mapping(payload["negative_control"])
    failed_diagnostics = _mapping(negative["diagnostics"])
    failed_gate = _mapping(negative["effect_gate"])
    assert failed_diagnostics["passed"] is False
    assert "PRE_TREND_FAILED" in _sequence(failed_diagnostics["reason_codes"])
    assert failed_gate["causal_claim_allowed"] is False


def test_p06_claim_boundaries_do_not_conflate_correlation_prediction_and_causality() -> None:
    boundaries = _mapping(build_payload()["claim_boundaries"])
    assert boundaries == {
        "correlation": "DESCRIPTIVE_ONLY_NOT_CAUSAL",
        "predictive_increment": "NOT_EVALUATED_IN_P06",
        "causal_effect": "DEVELOPMENT_ONLY_NO_REAL_WORLD_CLAIM",
    }


def test_p06_acceptance_traceability_points_to_real_test_symbols(project_root: Path) -> None:
    traceability = _mapping(build_payload()["acceptance_traceability"])
    for raw_node_ids in traceability.values():
        for raw_node_id in _sequence(raw_node_ids):
            test_path, separator, test_symbol = str(raw_node_id).partition("::")
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
