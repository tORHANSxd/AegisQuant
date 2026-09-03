"""Forecast capability, license, dependency, weight, and budget gate tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.research.budgets import ResourceRequest
from aegisquant.research.forecasting import (
    CandidateGateDecision,
    CapabilityMatrix,
    CapabilityStatus,
    CouncilHorizon,
    ForecastModelClass,
    LicenseStatus,
    MarketRegime,
    ModelCapability,
    PredictionMode,
    capability_matrix_sha256,
    default_capability_matrix,
    evaluate_candidate_gate,
)
from tests.v5_p07.helpers import budget, capability, gate, instant, request


def test_capability_matrix_covers_required_families_classes_horizons_and_regimes() -> None:
    matrix = default_capability_matrix(as_of_time=instant(20))
    assert len(matrix.candidates) == 24
    assert {
        item.family
        for item in matrix.candidates
        if item.model_class is ForecastModelClass.FOUNDATION
    } == {"TIMESFM_2_5", "CHRONOS_2", "MOIRAI_2", "TOTO_2_0"}
    assert {item.model_class for item in matrix.candidates} == set(ForecastModelClass)
    assert set(CouncilHorizon) <= set(capability("linear-baseline").supported_horizons)
    assert set(MarketRegime) <= set(capability("linear-baseline").supported_regimes)
    assert len(capability_matrix_sha256(matrix)) == 64


def test_catalog_membership_does_not_claim_installation_or_production_readiness() -> None:
    matrix = default_capability_matrix(as_of_time=instant(20))
    assert all(item.production_allowed is False for item in matrix.candidates)
    blocked = {
        item.family: item.status
        for item in matrix.candidates
        if item.model_class is ForecastModelClass.FOUNDATION
    }
    assert blocked == {
        "TIMESFM_2_5": CapabilityStatus.DEPENDENCY_BLOCKED,
        "CHRONOS_2": CapabilityStatus.ADAPTER_ONLY,
        "MOIRAI_2": CapabilityStatus.ADAPTER_ONLY,
        "TOTO_2_0": CapabilityStatus.DEPENDENCY_BLOCKED,
    }


def test_runnable_local_candidate_passes_finite_research_budget() -> None:
    decision = evaluate_candidate_gate(
        capability=capability("tcn-candidate"),
        budget=budget(),
        request=request(),
        dependency_available=True,
        weights_verified=True,
    )
    assert decision.allowed_to_evaluate is True
    assert decision.block_reasons == ()
    assert decision.alpha_promotion_eligible is False


def test_candidate_gate_blocks_budget_before_evaluation() -> None:
    decision = evaluate_candidate_gate(
        capability=capability("tcn-candidate"),
        budget=budget(),
        request=ResourceRequest(
            trials=5,
            train_seconds=Decimal("61"),
            inference_latency_ms=Decimal("101"),
            ram_mb=Decimal("2049"),
        ),
        dependency_available=True,
        weights_verified=True,
    )
    assert decision.allowed_to_evaluate is False
    assert set(decision.block_reasons) == {
        "AQ-BUDGET-TRIALS",
        "AQ-BUDGET-TRAIN-TIME",
        "AQ-BUDGET-INFERENCE-LATENCY",
        "AQ-BUDGET-RAM",
    }


def test_zero_shot_is_research_only_and_blocked_when_adapter_is_not_runnable() -> None:
    decision = evaluate_candidate_gate(
        capability=capability("chronos-2-candidate"),
        budget=budget(),
        request=request(),
        dependency_available=True,
        weights_verified=True,
    )
    assert decision.allowed_to_evaluate is False
    assert "AQ-FORECAST-CAPABILITY-ADAPTER_ONLY" in decision.block_reasons
    assert decision.restriction_codes == ("AQ-FORECAST-ZERO-SHOT-NO-PROMOTION",)
    assert decision.alpha_promotion_eligible is False


def test_unverified_license_dependency_and_weight_each_fail_closed() -> None:
    candidate = capability("timesfm-2.5-candidate")
    decision = evaluate_candidate_gate(
        capability=candidate,
        budget=budget(),
        request=request(),
        dependency_available=False,
        weights_verified=False,
    )
    assert decision.allowed_to_evaluate is False
    assert {
        "AQ-FORECAST-CAPABILITY-DEPENDENCY_BLOCKED",
        "AQ-FORECAST-LICENSE-NOT-APPROVED",
        "AQ-FORECAST-DEPENDENCY-UNAVAILABLE",
        "AQ-FORECAST-WEIGHTS-NOT-VERIFIED",
    } <= set(decision.block_reasons)


def test_capability_matrix_rejects_missing_family_and_duplicate_candidate() -> None:
    matrix = default_capability_matrix(as_of_time=instant(20))
    without_timesfm = tuple(item for item in matrix.candidates if item.family != "TIMESFM_2_5")
    with pytest.raises(ValidationError, match="missing a required foundation family"):
        CapabilityMatrix(as_of_time=matrix.as_of_time, candidates=without_timesfm)
    with pytest.raises(ValidationError, match="candidate ids must be unique"):
        CapabilityMatrix(
            as_of_time=matrix.as_of_time,
            candidates=(*matrix.candidates, matrix.candidates[0]),
        )


def test_runnable_capability_requires_complete_outputs_and_approved_license() -> None:
    candidate = capability("tcn-candidate")
    with pytest.raises(ValidationError, match="complete forecast contract"):
        ModelCapability.model_validate(
            {**candidate.model_dump(mode="python"), "supports_barrier_and_tail": False}
        )
    with pytest.raises(ValidationError, match="approved research license"):
        ModelCapability.model_validate(
            {**candidate.model_dump(mode="python"), "license_status": LicenseStatus.UNVERIFIED}
        )


def test_runnable_weighted_capability_requires_weight_hash() -> None:
    candidate = capability("chronos-2-candidate")
    payload = candidate.model_dump(mode="python")
    payload.update(
        {
            "status": CapabilityStatus.RUNNABLE_LOCAL,
            "weight_sha256": None,
            "license_status": LicenseStatus.VERIFIED_PERMISSIVE,
        }
    )
    with pytest.raises(ValidationError, match="verified weight hash"):
        ModelCapability.model_validate(payload)


def test_zero_shot_mode_cannot_be_attached_to_non_foundation_candidate() -> None:
    candidate = capability("tcn-candidate")
    with pytest.raises(ValidationError, match="reserved for foundation"):
        ModelCapability.model_validate(
            {**candidate.model_dump(mode="python"), "prediction_modes": (PredictionMode.ZERO_SHOT,)}
        )


def test_candidate_gate_decision_rejects_forged_boolean_or_duplicate_reasons() -> None:
    valid = gate("linear-baseline").model_dump(mode="python")
    with pytest.raises(ValidationError, match="disagree"):
        CandidateGateDecision.model_validate(
            {
                **valid,
                "candidate_id": "forged",
                "allowed_to_evaluate": True,
                "block_reasons": ("BLOCKED",),
            }
        )
    with pytest.raises(ValidationError, match="sorted and unique"):
        CandidateGateDecision.model_validate(
            {
                **valid,
                "candidate_id": "forged",
                "allowed_to_evaluate": False,
                "block_reasons": ("B", "A", "B"),
            }
        )


def test_candidate_gate_decision_binds_budget_and_request_payloads() -> None:
    decision = gate("linear-baseline")
    larger_budget = decision.budget.model_copy(
        update={"max_train_seconds": decision.budget.max_train_seconds + Decimal("1")}
    )
    forged = decision.model_copy(update={"budget": larger_budget})
    with pytest.raises(ValidationError, match="GATE-BUDGET-HASH-MISMATCH"):
        CandidateGateDecision.model_validate_json(forged.model_dump_json())
