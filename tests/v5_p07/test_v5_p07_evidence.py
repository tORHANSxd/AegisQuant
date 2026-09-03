from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import cast

from scripts.generate_v5_p07_evidence import OUTPUT, build_payload


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _sequence(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast("list[object]", value)


def test_checked_in_p07_evidence_matches_recomputed_payload() -> None:
    checked_in: object = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert checked_in == build_payload()


def test_p07_evidence_is_development_only_and_fail_closed() -> None:
    payload = build_payload()
    checks = _mapping(payload["checks"])
    assert checks and all(checks.values())
    assert payload["phase"] == "V5-P07"
    assert payload["result"] == "PASS"
    assert payload["evidence_tier"] == "DEVELOPMENT"
    assert payload["alpha_promotion_eligible"] is False
    assert payload["real_world_forecast_accuracy_claimed"] is False
    assert payload["zero_shot_is_promotion"] is False
    assert payload["external_model_weights_downloaded"] is False
    assert payload["final_holdout_opened"] is False
    assert payload["live_trading_locked"] is True
    assert payload["order_submission_enabled"] is False
    assert all(_mapping(payload["negative_controls"]).values())


def test_p07_capability_forecast_and_arena_lineage_are_explicit() -> None:
    payload = build_payload()
    matrix = _mapping(payload["capability_matrix"])
    candidates = [_mapping(item) for item in _sequence(matrix["candidates"])]
    assert len(candidates) == 24
    assert all(item["production_allowed"] is False for item in candidates)
    assert {item["family"] for item in candidates if item["model_class"] == "FOUNDATION"} == {
        "TIMESFM_2_5",
        "CHRONOS_2",
        "MOIRAI_2",
        "TOTO_2_0",
    }

    tensor = _mapping(payload["market_state_tensor"])
    calibration = _mapping(_sequence(payload["calibration_artifacts"])[0])
    forecast = _mapping(_sequence(payload["forecast_envelopes"])[0])
    assert forecast["market_state_tensor_sha256"] == tensor["tensor_sha256"]
    assert forecast["dataset_manifest_sha256"] == tensor["dataset_manifest_sha256"]
    calibration_hashes = _mapping(forecast["calibration_artifact_sha256_by_horizon"])
    assert calibration_hashes["30m"] == calibration["artifact_sha256"]

    arena = _mapping(payload["model_arena"])
    assert arena["fair_comparison"] is True
    assert arena["no_single_universal_model_assumption"] is True
    assert arena["zero_shot_is_promotion"] is False
    assert arena["failures_preserved"] is True
    cells = [_mapping(item) for item in _sequence(arena["cells"])]
    assert all(cell["equal_oos_folds"] is True for cell in cells)
    assert {cell["research_champion_candidate_id"] for cell in cells} == {
        "linear-baseline",
        "tcn-candidate",
    }


def test_p07_vision_without_material_oos_increment_is_eliminated() -> None:
    ablation = _mapping(_sequence(build_payload()["vision_ablations"])[0])
    assert ablation["retain_vision"] is False
    assert ablation["selected_modality"] == "NUMERIC_ONLY"
    assert ablation["reason_code"] == "VISION_NO_OOS_INCREMENT"


def test_p07_acceptance_traceability_points_to_real_test_symbols(project_root: Path) -> None:
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
