"""Meta-Reasoner and independent Skeptic boundary tests."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

from aegisquant.research.forecasting import (
    ForecastGovernanceReport,
    MetaReasonerRecommendation,
    ReasoningInputKind,
    SkepticSeverity,
    build_forecast_governance_report,
)
from tests.v5_p09.helpers import (
    conformal_report,
    digest,
    disagreement_report,
    governance_report,
    meta_recommendation,
    reasoning_context,
    route_decision,
    skeptic_assessment,
)


def test_meta_reasoner_is_structured_advice_and_cannot_order() -> None:
    report = governance_report()
    assert report.meta_reasoner.action == "RESEARCH_RECOMMENDATION_ONLY"
    assert report.meta_reasoner.order_submission_enabled is False
    assert report.llm_can_order is False
    assert report.order_submission_enabled is False

    payload = report.meta_reasoner.model_dump(mode="json")
    payload["action"] = "PLACE_ORDER"
    with pytest.raises(ValidationError):
        MetaReasonerRecommendation.model_validate_json(json.dumps(payload))


def test_boundary_revalidates_a_model_construct_order_capability_forgery() -> None:
    disagreement = disagreement_report()
    route = route_decision()
    calibration = conformal_report()
    context = reasoning_context(disagreement=disagreement, route=route, calibration=calibration)
    meta = meta_recommendation(context)
    forged = MetaReasonerRecommendation.model_construct(
        **cast("dict[str, Any]", {**meta.__dict__, "order_submission_enabled": True})
    )
    with pytest.raises(ValidationError):
        build_forecast_governance_report(
            context=context,
            meta_reasoner=forged,
            skeptic=skeptic_assessment(context),
            disagreement=disagreement,
            regime_route=route,
            calibration=calibration,
        )


def test_reasoning_context_requires_distinct_reviewer_prompt_and_model_paths() -> None:
    shared_prompt = digest("shared-prompt")
    with pytest.raises(ValueError, match="SKEPTIC-NOT-INDEPENDENT"):
        reasoning_context(
            meta_reasoner_prompt_sha256=shared_prompt,
            skeptic_prompt_sha256=shared_prompt,
        )

    shared_model = digest("shared-model")
    with pytest.raises(ValueError, match="SKEPTIC-NOT-INDEPENDENT"):
        reasoning_context(
            meta_reasoner_model_revision_sha256=shared_model,
            skeptic_model_revision_sha256=shared_model,
        )


def test_reasoning_context_binds_exact_reviewer_prompt_and_model_revisions() -> None:
    disagreement = disagreement_report()
    route = route_decision()
    calibration = conformal_report()
    context = reasoning_context(disagreement=disagreement, route=route, calibration=calibration)
    skeptic = skeptic_assessment(
        context,
        model_revision_sha256=digest("unapproved-skeptic-model"),
    )
    with pytest.raises(ValueError, match="REVIEWER-BINDING-MISMATCH"):
        build_forecast_governance_report(
            context=context,
            meta_reasoner=meta_recommendation(context),
            skeptic=skeptic,
            disagreement=disagreement,
            regime_route=route,
            calibration=calibration,
        )


def test_severe_skeptic_findings_must_block_and_propagate_to_abstain() -> None:
    with pytest.raises(ValueError, match="MUST-BLOCK"):
        governance_report(skeptic_blocks=False, skeptic_severity=SkepticSeverity.HIGH)

    report = governance_report(skeptic_blocks=True, skeptic_severity=SkepticSeverity.HIGH)
    assert report.should_abstain is True
    assert "SKEPTIC_BETA_CONFOUNDING_CHECKED" in report.reason_codes


def test_reasoning_hash_and_governance_hash_tampering_are_rejected() -> None:
    report = governance_report()
    payload = report.model_dump(mode="json")
    payload["should_abstain"] = True
    with pytest.raises(ValueError, match="RECOMPUTATION-MISMATCH"):
        ForecastGovernanceReport.model_validate_json(json.dumps(payload))

    context_payload = report.context.model_dump(mode="json")
    risk_binding = next(
        binding for binding in context_payload["input_artifacts"] if binding["kind"] == "RISK_STATE"
    )
    risk_binding["artifact_sha256"] = digest("forged-risk")
    with pytest.raises(ValueError, match="CONTEXT-HASH-MISMATCH"):
        type(report.context).model_validate_json(json.dumps(context_payload))


def test_reasoning_bindings_are_immutable_and_boundary_revalidates_model_copy_forgery() -> None:
    report = governance_report()
    binding = next(
        item
        for item in report.context.input_artifacts
        if item.kind is ReasoningInputKind.RISK_STATE
    )
    hash_attribute = "artifact_sha256"
    with pytest.raises(ValidationError):
        setattr(binding, hash_attribute, digest("mutated-nested-input"))

    forged_binding = binding.model_copy(update={"artifact_sha256": digest("model-copy-forgery")})
    forged_context = report.context.model_copy(
        update={
            "input_artifacts": tuple(
                forged_binding if item.kind is ReasoningInputKind.RISK_STATE else item
                for item in report.context.input_artifacts
            )
        }
    )
    with pytest.raises(ValueError, match="CONTEXT-HASH-MISMATCH"):
        build_forecast_governance_report(
            context=forged_context,
            meta_reasoner=report.meta_reasoner,
            skeptic=report.skeptic,
            disagreement=report.disagreement,
            regime_route=report.regime_route,
            calibration=report.calibration,
        )
