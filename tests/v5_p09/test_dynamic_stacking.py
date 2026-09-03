"""Dynamic stacking, regime routing, and disagreement tests."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.truth import TruthState
from aegisquant.research.forecasting import (
    MarketRegime,
    RegimeRoutingSnapshot,
    StatisticalWeightProposal,
    WeightEvidenceSource,
    route_dynamic_stacking,
)
from tests.v5_p09.helpers import (
    NOW,
    digest,
    disagreement_report,
    route_decision,
    routing_snapshot,
    signal_snapshot,
    stacking_policy,
    weight_proposal,
)


def test_dynamic_stacking_smooths_statistical_weights_with_a_cap() -> None:
    decision = route_decision()
    assert decision.should_abstain is False
    assert decision.selected_weights is not None
    assert decision.selected_weights.weights == {
        "baseline": Decimal("0.45"),
        "supervised": Decimal("0.55"),
    }
    assert max(decision.selected_weights.weights.values()) <= Decimal("0.70")


def test_weight_evidence_whitelist_requires_validation_and_calibration() -> None:
    with pytest.raises(ValueError, match="EVIDENCE-INCOMPLETE"):
        weight_proposal(evidence={WeightEvidenceSource.VALIDATION: digest("validation-only")})

    proposal = weight_proposal()
    assert {binding.source for binding in proposal.evidence_bindings} == {
        WeightEvidenceSource.VALIDATION,
        WeightEvidenceSource.CALIBRATION,
    }
    proposal_with_forward = weight_proposal(
        evidence={
            WeightEvidenceSource.VALIDATION: digest("validation"),
            WeightEvidenceSource.CALIBRATION: digest("calibration"),
            WeightEvidenceSource.FORWARD: digest("forward-window"),
        }
    )
    assert WeightEvidenceSource.FORWARD in {
        binding.source for binding in proposal_with_forward.evidence_bindings
    }

    payload = proposal.model_dump(mode="json")
    payload["final_holdout_used"] = True
    with pytest.raises(ValidationError):
        StatisticalWeightProposal.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (routing_snapshot(ood_score=Decimal("2")), "OUT_OF_DISTRIBUTION"),
        (routing_snapshot(data_quality=Decimal("0.2")), "DATA_QUALITY_BELOW_POLICY"),
        (routing_snapshot(truth_state=TruthState.RUMOR), "TRUTH_UNCERTAIN"),
        (
            routing_snapshot(
                reliability={"baseline": Decimal("0.9"), "supervised": Decimal("0.1")}
            ),
            "MODEL_RELIABILITY_DEGRADED",
        ),
    ],
)
def test_regime_router_abstains_on_unsafe_context(
    snapshot: RegimeRoutingSnapshot,
    reason: str,
) -> None:
    decision = route_dynamic_stacking(
        snapshot=snapshot,
        proposal=weight_proposal(),
        policy=stacking_policy(),
    )
    assert decision.should_abstain is True
    assert decision.selected_weights is None
    assert reason in decision.reason_codes


def test_unknown_regime_and_future_weight_proposals_fail_closed() -> None:
    unknown = route_dynamic_stacking(
        snapshot=routing_snapshot(regime=MarketRegime.UNKNOWN),
        proposal=weight_proposal(regime=MarketRegime.UNKNOWN),
        policy=stacking_policy(),
    )
    assert unknown.should_abstain is True
    assert "UNKNOWN_REGIME" in unknown.reason_codes

    with pytest.raises(ValueError, match="LOOKAHEAD"):
        route_dynamic_stacking(
            snapshot=routing_snapshot(),
            proposal=weight_proposal(available_at=NOW + timedelta(seconds=1)),
            policy=stacking_policy(),
        )


def test_weight_cap_feasibility_and_ood_threshold_boundary_are_explicit() -> None:
    infeasible = route_dynamic_stacking(
        snapshot=routing_snapshot(),
        proposal=weight_proposal(),
        policy=stacking_policy(maximum_single_model_weight=Decimal("0.49")),
    )
    assert infeasible.should_abstain is True
    assert "DYNAMIC_WEIGHT_CAP_INFEASIBLE" in infeasible.reason_codes

    at_boundary = route_dynamic_stacking(
        snapshot=routing_snapshot(ood_score=Decimal("1")),
        proposal=weight_proposal(),
        policy=stacking_policy(),
    )
    assert at_boundary.should_abstain is False


def test_weight_evidence_is_immutable_and_route_revalidates_model_copy_forgery() -> None:
    proposal = weight_proposal()
    hash_attribute = "artifact_sha256"
    with pytest.raises(ValidationError):
        setattr(proposal.evidence_bindings[0], hash_attribute, digest("mutated"))

    forged = proposal.model_copy(update={"evidence_bindings": proposal.evidence_bindings[:1]})
    with pytest.raises(ValueError, match="EVIDENCE-INCOMPLETE"):
        route_dynamic_stacking(
            snapshot=routing_snapshot(),
            proposal=forged,
            policy=stacking_policy(),
        )


def test_regime_cell_and_reliability_model_splices_are_rejected() -> None:
    with pytest.raises(ValueError, match="CELL-MISMATCH"):
        route_dynamic_stacking(
            snapshot=routing_snapshot(regime=MarketRegime.NEWS_SHOCK),
            proposal=weight_proposal(regime=MarketRegime.TREND),
            policy=stacking_policy(),
        )
    with pytest.raises(ValueError, match="MODEL-SET-MISMATCH"):
        route_dynamic_stacking(
            snapshot=routing_snapshot(reliability={"baseline": Decimal("0.9")}),
            proposal=weight_proposal(),
            policy=stacking_policy(),
        )


def test_disagreement_is_recomputed_and_direction_conflict_abstains() -> None:
    report = disagreement_report(
        snapshot=signal_snapshot(returns=(Decimal("-0.05"), Decimal("0.05"))),
        maximum_range=Decimal("0.02"),
    )
    assert report.expected_return_range == Decimal("0.10")
    assert report.direction_conflict is True
    assert report.should_abstain is True
    assert set(report.reason_codes) == {
        "MODEL_DIRECTION_CONFLICT",
        "MODEL_DISAGREEMENT_RANGE_EXCEEDED",
    }


def test_forged_disagreement_decision_is_rejected_after_hash_recalculation() -> None:
    report = disagreement_report()
    payload = report.model_dump(mode="json")
    payload["should_abstain"] = True
    payload["reason_codes"] = ["CALLER_SAYS_SO"]
    payload["report_sha256"] = digest("attacker-recomputed-a-hash")
    with pytest.raises(ValueError, match="RECOMPUTATION-MISMATCH"):
        type(report).model_validate_json(json.dumps(payload))
