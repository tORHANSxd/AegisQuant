from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import cast

from scripts.generate_v5_p05_evidence import OUTPUT, build_payload


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _sequence(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast("list[object]", value)


def test_v5_p05_evidence_artifact_is_deterministic() -> None:
    expected = build_payload()
    assert json.loads(OUTPUT.read_text(encoding="utf-8")) == expected


def test_v5_p05_evidence_recomputes_surprise_and_preserves_pit() -> None:
    payload = build_payload()
    surprise = _mapping(payload["event_surprise"])
    assert Decimal(str(surprise["surprise_value"])) == (
        Decimal(str(surprise["actual_value"])) - Decimal(str(surprise["expected_value"]))
    )
    pit = _mapping(payload["pipeline_pit"])
    observed = _mapping(pit["input_observed_times"])
    assert pit["visible_claim_count"] == 1
    assert str(observed["future_confirmation"]) > str(pit["decision_time"])
    cluster = _mapping(pit["cluster"])
    assert cluster["status"] == "RUMOR"
    assert cluster["official_confirmation_count"] == 0


def test_v5_p05_evidence_has_fail_closed_directional_gates() -> None:
    payload = build_payload()
    gates = _mapping(payload["directional_gates"])
    high = _mapping(gates["high"])
    rumor = _mapping(gates["rumor"])
    incomplete = _mapping(gates["incomplete"])
    low = _mapping(gates["low"])

    assert high["directional_candidate_allowed"] is False
    assert "EVENT_ALREADY_PRICED" in _sequence(high["reason_codes"])
    assert rumor["directional_candidate_allowed"] is False
    assert "EVENT_NOT_CONFIRMED" in _sequence(rumor["reason_codes"])
    assert incomplete["market_reflection_score"] is None
    assert incomplete["market_reflection_quality"] == "DEGRADED"
    assert incomplete["directional_candidate_allowed"] is False
    assert low["directional_candidate_allowed"] is True
    assert low["action"] == "RESEARCH_PROPOSAL_ONLY"
    assert low["order_submission_allowed"] is False


def test_v5_p05_evidence_makes_no_accuracy_or_promotion_claim() -> None:
    payload = build_payload()
    assert payload["evidence_tier"] == "DEVELOPMENT"
    assert payload["alpha_promotion_eligible"] is False
    assert payload["real_world_forecast_accuracy_claimed"] is False
    assert payload["live_trading_locked"] is True
    assert payload["order_submission_enabled"] is False
    assert set(_mapping(payload["checks"]).values()) == {True}
    assert Path(OUTPUT).as_posix().endswith("reports/v5/P05/EVENT_CANONICALIZATION_EVIDENCE.json")
