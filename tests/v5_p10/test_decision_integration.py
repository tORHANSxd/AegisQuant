"""End-to-end P10 pipeline and bypass-resistance tests."""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisquant.data.hashing import canonical_sha256
from aegisquant.decision import (
    DECISION_PIPELINE,
    DecisionOutcome,
    IntegratedDecisionReport,
    integrate_forecast_decision,
)
from aegisquant.domain.identifiers import StrategyId
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.truth import TruthState
from tests.v5_p10.helpers import (
    DECISION_TIME,
    event_condition,
    forecast_distribution,
    governance,
    net_edge,
    overlay_policy,
    portfolio,
    risk_decision,
)


def integrated_directional_report() -> IntegratedDecisionReport:
    forecast = forecast_distribution()
    edge = net_edge(forecast=forecast)
    proposal = portfolio(forecast)
    risk = risk_decision(proposal)
    return integrate_forecast_decision(
        net_edge=edge,
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=risk,
        decision_time=DECISION_TIME,
    )


def test_full_pipeline_produces_research_only_directional_alpha() -> None:
    report = integrated_directional_report()
    assert report.pipeline == DECISION_PIPELINE
    assert report.outcome is DecisionOutcome.DIRECTIONAL_ALPHA
    assert report.portfolio_allows is True
    assert report.risk_allows is True
    assert report.directional_alpha is not None
    assert report.risk_overlay is None
    assert report.no_trade is None
    assert report.directional_alpha.order_submission_enabled is False
    assert report.alpha_promotion_eligible is False
    assert report.live_trading_locked is True


def test_news_cannot_bypass_cost_gate() -> None:
    forecast = forecast_distribution()
    from tests.v5_p10.helpers import cost_distribution

    rejected_edge = net_edge(
        forecast=forecast,
        costs=cost_distribution(component_cost=Decimal("0.002")),
    )
    proposal = portfolio(forecast)
    report = integrate_forecast_decision(
        net_edge=rejected_edge,
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=risk_decision(proposal),
        decision_time=DECISION_TIME,
    )
    assert report.outcome is DecisionOutcome.NO_TRADE
    assert report.no_trade is not None
    assert "EXPECTED_NET_EDGE_NONPOSITIVE" in report.no_trade.reason_codes


def test_news_cannot_bypass_independent_risk_gate() -> None:
    forecast = forecast_distribution()
    report = integrate_forecast_decision(
        net_edge=net_edge(forecast=forecast),
        overlay_policy=overlay_policy(),
        portfolio=portfolio(forecast),
        risk=None,
        decision_time=DECISION_TIME,
    )
    assert report.outcome is DecisionOutcome.NO_TRADE
    assert report.no_trade is not None
    assert "RISK_GATE_REJECTED" in report.reason_codes


def test_unbound_portfolio_signal_cannot_authorize_directional_alpha() -> None:
    original = forecast_distribution()
    different = forecast_distribution(
        condition=event_condition(reflection_strength=Decimal("0.30"))
    )
    proposal = portfolio(original)
    report = integrate_forecast_decision(
        net_edge=net_edge(forecast=different),
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=risk_decision(proposal),
        decision_time=DECISION_TIME,
    )
    assert report.outcome is DecisionOutcome.NO_TRADE
    assert "PORTFOLIO_GATE_REJECTED" in report.reason_codes


def test_risk_decision_for_another_proposal_is_rejected_as_splice() -> None:
    forecast = forecast_distribution()
    expected_proposal = portfolio(forecast)
    other_forecast = forecast_distribution(
        condition=event_condition(reflection_strength=Decimal("0.30"))
    )
    other_proposal = portfolio(other_forecast)
    with pytest.raises(ValueError, match="RISK-PROPOSAL-SPLICE"):
        integrate_forecast_decision(
            net_edge=net_edge(forecast=forecast),
            overlay_policy=overlay_policy(),
            portfolio=expected_proposal,
            risk=risk_decision(other_proposal),
            decision_time=DECISION_TIME,
        )


def test_risk_target_must_match_the_bound_portfolio_strategy_and_account() -> None:
    forecast = forecast_distribution()
    proposal = portfolio(forecast)
    risk = risk_decision(proposal)
    wrong_target = risk.approved_targets[0].model_copy(
        update={"strategy_id": StrategyId("another-strategy")}
    )
    wrong_risk = risk.model_copy(update={"approved_targets": (wrong_target,)})
    report = integrate_forecast_decision(
        net_edge=net_edge(forecast=forecast),
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=wrong_risk,
        decision_time=DECISION_TIME,
    )
    assert report.outcome is DecisionOutcome.NO_TRADE
    assert "RISK_GATE_REJECTED" in report.reason_codes


def test_model_construct_risk_forgery_is_revalidated_at_boundary() -> None:
    forecast = forecast_distribution()
    proposal = portfolio(forecast)
    risk = risk_decision(proposal)
    forged_payload = {field: getattr(risk, field) for field in type(risk).model_fields}
    forged_payload["new_risk_allowed"] = False
    forged = type(risk).model_construct(**forged_payload)
    with pytest.raises(ValidationError, match="approved decision requires"):
        integrate_forecast_decision(
            net_edge=net_edge(forecast=forecast),
            overlay_policy=overlay_policy(),
            portfolio=proposal,
            risk=forged,
            decision_time=DECISION_TIME,
        )


def test_high_severity_medium_truth_is_risk_overlay_not_directional_alpha() -> None:
    condition = event_condition(
        status=EventClusterStatus.RUMOR,
        truth_state=TruthState.RUMOR,
        truth_probability=Decimal("0.70"),
        severity=Decimal("0.95"),
    )
    forecast = forecast_distribution(
        condition=condition,
        governed=governance(truth_state=TruthState.RUMOR),
        event_should_abstain=True,
    )
    proposal = portfolio(
        forecast,
        current_weight=Decimal("0.20"),
        raw_score=Decimal("0.02"),
    )
    report = integrate_forecast_decision(
        net_edge=net_edge(forecast=forecast),
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=risk_decision(proposal, major_event_clear=False),
        decision_time=DECISION_TIME,
    )
    assert report.outcome is DecisionOutcome.RISK_OVERLAY_ONLY
    assert report.directional_alpha is None
    assert report.no_trade is None
    assert report.risk_overlay is not None
    assert report.risk_overlay.directional_alpha_allowed is False
    assert report.risk_overlay.target_exposure_scale == Decimal("0.50")


def test_overlay_without_protective_risk_decision_stays_no_trade() -> None:
    condition = event_condition(
        status=EventClusterStatus.RUMOR,
        truth_state=TruthState.RUMOR,
        truth_probability=Decimal("0.70"),
        severity=Decimal("0.95"),
    )
    forecast = forecast_distribution(
        condition=condition,
        governed=governance(truth_state=TruthState.RUMOR),
        event_should_abstain=True,
    )
    proposal = portfolio(forecast)
    report = integrate_forecast_decision(
        net_edge=net_edge(forecast=forecast),
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=risk_decision(proposal, major_event_clear=True),
        decision_time=DECISION_TIME,
    )
    assert report.outcome is DecisionOutcome.NO_TRADE
    assert "RISK_OVERLAY_NOT_AUTHORIZED_BY_RISK" in report.reason_codes


def test_no_trade_is_a_hashed_first_class_exclusive_result() -> None:
    forecast = forecast_distribution()
    report = integrate_forecast_decision(
        net_edge=net_edge(forecast=forecast),
        overlay_policy=overlay_policy(),
        portfolio=None,
        risk=None,
        decision_time=DECISION_TIME,
    )
    assert report.outcome is DecisionOutcome.NO_TRADE
    assert report.no_trade is not None
    assert report.no_trade.action == "NO_TRADE"
    assert report.directional_alpha is None
    assert report.risk_overlay is None
    assert len(report.no_trade.decision_sha256) == 64


def test_recomputed_report_hash_cannot_forge_a_trade_outcome() -> None:
    report = integrate_forecast_decision(
        net_edge=net_edge(),
        overlay_policy=overlay_policy(),
        portfolio=None,
        risk=None,
        decision_time=DECISION_TIME,
    )
    payload = report.model_dump(mode="json")
    payload["outcome"] = "DIRECTIONAL_ALPHA"
    payload["report_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "report_sha256"}
    )
    with pytest.raises(ValidationError, match="INTEGRATED-DECISION-RECOMPUTATION"):
        IntegratedDecisionReport.model_validate_json(json.dumps(payload))


def test_decision_module_has_no_execution_or_order_constructor_import(project_root: Path) -> None:
    source = (project_root / "src/aegisquant/decision.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(module.startswith("aegisquant.execution") for module in modules)
    assert "OrderIntent" not in source
    assert "SubmitOrderCommand" not in source
