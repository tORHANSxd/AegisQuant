"""Unified ForecastDistribution + ExecutionCostDistribution gate tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.decision import (
    CostCalibrationState,
    ExecutionCostScenario,
    NetEdgeThresholdSource,
    create_execution_cost_distribution,
    create_net_edge_policy,
    evaluate_net_edge,
)
from aegisquant.domain.identifiers import AssetId
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.truth import TruthState
from aegisquant.research.forecasting import EventConditionSnapshot, ForecastGovernanceReport
from tests.v5_p10.helpers import (
    ASSET,
    HORIZON,
    SLEEVE,
    cost_distribution,
    cost_model,
    digest,
    event_condition,
    forecast_distribution,
    governance,
    net_edge,
    net_edge_policy,
)


def test_healthy_net_edge_recomputes_all_economic_gates() -> None:
    result = net_edge()
    assert result.expected_net_edge == Decimal("0.0040000")
    assert result.raw_probability_positive == Decimal("0.90")
    assert result.confidence_adjusted_probability_positive == Decimal("0.8550")
    assert result.lower_confidence_bound == Decimal("0.0020")
    assert result.expected_net_edge_cost_ratio == Decimal("2")
    assert result.scenarios[1].queue_probability == Decimal("0.40")
    assert result.scenarios[1].queue_adjusted_gross_edge == Decimal("0.0040")
    assert result.scenarios[1].net_edge == Decimal("0.0020")
    assert result.allowed_before_portfolio_and_risk is True
    assert result.reason_codes == ()


def test_high_cost_forces_no_net_edge_before_portfolio_or_risk() -> None:
    expensive = cost_distribution(component_cost=Decimal("0.002"))
    result = net_edge(costs=expensive)
    assert result.expected_net_edge < 0
    assert result.allowed_before_portfolio_and_risk is False
    assert "EXPECTED_NET_EDGE_NONPOSITIVE" in result.reason_codes
    assert "NET_EDGE_COST_RATIO_BELOW_POLICY" in result.reason_codes


def test_cost_miscalibration_haircut_can_fail_probability_gate() -> None:
    weak_model = cost_model(
        confidence=Decimal("0.60"),
        state=CostCalibrationState.MISCALIBRATED,
    )
    result = net_edge(costs=cost_distribution(model=weak_model))
    assert result.raw_probability_positive == Decimal("0.90")
    assert result.confidence_adjusted_probability_positive == Decimal("0.540")
    assert result.probability_gate_passed is False
    assert result.cost_confidence_gate_passed is False


@pytest.mark.parametrize(
    ("condition", "governed", "reason"),
    (
        (
            event_condition(truth_probability=Decimal("0.98")),
            governance(),
            "TRUTH_GATE_REJECTED",
        ),
        (
            event_condition(reflection_strength=Decimal("0.90")),
            governance(),
            "PRICE_IN_GATE_REJECTED",
        ),
        (
            event_condition(),
            governance(ood_score=Decimal("2")),
            "OOD_GATE_REJECTED",
        ),
        (
            event_condition(),
            governance(data_quality=Decimal("0.60")),
            "DATA_QUALITY_GATE_REJECTED",
        ),
    ),
)
def test_truth_price_in_ood_and_data_quality_are_independent_hard_gates(
    condition: EventConditionSnapshot,
    governed: ForecastGovernanceReport,
    reason: str,
) -> None:
    forecast = forecast_distribution(
        condition=condition,
        governed=governed,
        event_should_abstain=condition.risk_overlay_only,
    )
    result = net_edge(forecast=forecast)
    assert result.allowed_before_portfolio_and_risk is False
    assert reason in result.reason_codes


def test_forecast_and_cost_scenario_sets_cannot_be_spliced() -> None:
    forecast = forecast_distribution()
    costs = cost_distribution()
    payload = costs.model_dump(mode="python")
    altered = list(payload["scenarios"])
    altered[0] = {**altered[0], "scenario_id": "different-scenario"}
    spliced = create_execution_cost_distribution(
        model=costs.model,
        asset_id=costs.asset_id,
        instrument_id=costs.instrument_id,
        horizon=costs.horizon,
        sleeve_id=costs.sleeve_id,
        decision_time=costs.decision_time,
        available_at=costs.available_at,
        scenarios=tuple(ExecutionCostScenario.model_validate(item) for item in altered),
    )
    with pytest.raises(ValueError, match="FORECAST-COST-SCENARIO-SPLICE"):
        evaluate_net_edge(forecast=forecast, costs=spliced, policy=net_edge_policy())


def test_threshold_policy_is_versioned_per_asset_horizon_sleeve() -> None:
    with pytest.raises(ValueError, match="POLICY-CELL-SPLICE"):
        evaluate_net_edge(
            forecast=forecast_distribution(),
            costs=cost_distribution(),
            policy=net_edge_policy(asset_id=AssetId("ETH")),
        )


def test_oos_threshold_source_requires_content_addressed_evidence() -> None:
    with pytest.raises(ValidationError, match="OOS-THRESHOLD-EVIDENCE-MISMATCH"):
        net_edge_policy(threshold_source=NetEdgeThresholdSource.OOS)
    policy = net_edge_policy(
        version="p10-oos-fixture",
        threshold_source=NetEdgeThresholdSource.OOS,
        oos_evidence_sha256=digest("p10-oos-threshold-study"),
        minimum_probability_positive=Decimal("0.73"),
    )
    assert policy.minimum_probability_positive == Decimal("0.73")


def test_bootstrap_probability_is_not_a_hidden_global_default() -> None:
    policy = create_net_edge_policy(
        version="custom-bootstrap",
        asset_id=ASSET,
        horizon=HORIZON,
        sleeve_id=SLEEVE,
        threshold_source=NetEdgeThresholdSource.BOOTSTRAP,
        oos_evidence_sha256=None,
        minimum_probability_positive=Decimal("0.77"),
        confidence_level=Decimal("0.85"),
        economic_floor=Decimal("0.002"),
        minimum_net_edge_cost_ratio=Decimal("3"),
        minimum_truth_probability=Decimal("0.995"),
        maximum_contradiction_probability=Decimal("0.03"),
        maximum_manipulation_probability=Decimal("0.03"),
        minimum_novelty=Decimal("0.75"),
        maximum_market_reflection=Decimal("0.70"),
        maximum_forecast_range=Decimal("0.01"),
        maximum_ood_score=Decimal("0.50"),
        minimum_data_quality=Decimal("0.90"),
        minimum_event_increment_magnitude=Decimal("0.002"),
        minimum_cost_confidence=Decimal("0.90"),
    )
    assert policy.minimum_probability_positive == Decimal("0.77")
    assert policy.alpha_truth_claimed is False
    assert policy.final_holdout_opened is False


def test_rumor_can_never_pass_directional_truth_or_price_gate() -> None:
    condition = event_condition(
        status=EventClusterStatus.RUMOR,
        truth_state=TruthState.RUMOR,
        truth_probability=Decimal("0.70"),
    )
    forecast = forecast_distribution(
        condition=condition,
        governed=governance(truth_state=TruthState.RUMOR),
        event_should_abstain=True,
    )
    result = net_edge(forecast=forecast)
    assert result.truth_gate_passed is False
    assert result.price_in_gate_passed is False
    assert result.uncertainty_gate_passed is False
