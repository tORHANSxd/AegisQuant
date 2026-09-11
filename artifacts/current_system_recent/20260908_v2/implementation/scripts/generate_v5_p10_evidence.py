"""Generate deterministic V5-P10 net-edge and decision-integration evidence."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from aegisquant.data.hashing import canonical_sha256
from aegisquant.decision import (
    CostCalibrationState,
    DecisionOutcome,
    IntegratedDecisionReport,
    integrate_forecast_decision,
)
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.truth import TruthState
from tests.v5_p10.helpers import (
    DECISION_TIME,
    cost_distribution,
    cost_model,
    event_condition,
    forecast_distribution,
    governance,
    net_edge,
    overlay_policy,
    portfolio,
    risk_decision,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "v5" / "P10" / "DECISION_INTEGRATION_EVIDENCE.json"


def _rejected(operation: Callable[[], object], expected_code: str | None = None) -> bool:
    try:
        operation()
    except (TypeError, ValueError) as error:
        return expected_code is None or expected_code in str(error)
    return False


def _decision_has_no_execution_import() -> bool:
    source = (ROOT / "src/aegisquant/decision.py").read_text(encoding="utf-8")
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
    return not any(module.startswith("aegisquant.execution") for module in modules)


def _rumor_overlay_report() -> IntegratedDecisionReport:
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
    return integrate_forecast_decision(
        net_edge=net_edge(forecast=forecast),
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=risk_decision(proposal, major_event_clear=False),
        decision_time=DECISION_TIME,
    )


def build_payload() -> dict[str, object]:
    forecast = forecast_distribution()
    healthy_edge = net_edge(forecast=forecast)
    proposal = portfolio(forecast)
    risk = risk_decision(proposal)
    directional = integrate_forecast_decision(
        net_edge=healthy_edge,
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=risk,
        decision_time=DECISION_TIME,
    )
    high_cost = net_edge(
        forecast=forecast,
        costs=cost_distribution(component_cost=Decimal("0.002")),
    )
    cost_rejected = integrate_forecast_decision(
        net_edge=high_cost,
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=risk,
        decision_time=DECISION_TIME,
    )
    risk_rejected = integrate_forecast_decision(
        net_edge=healthy_edge,
        overlay_policy=overlay_policy(),
        portfolio=proposal,
        risk=None,
        decision_time=DECISION_TIME,
    )
    overlay = _rumor_overlay_report()
    miscalibrated_edge = net_edge(
        forecast=forecast,
        costs=cost_distribution(
            model=cost_model(
                confidence=Decimal("0.60"),
                state=CostCalibrationState.MISCALIBRATED,
            )
        ),
    )

    forged = risk_rejected.model_dump(mode="json")
    forged["outcome"] = DecisionOutcome.DIRECTIONAL_ALPHA.value
    forged["report_sha256"] = canonical_sha256(
        {key: value for key, value in forged.items() if key != "report_sha256"}
    )
    other_forecast = forecast_distribution(
        condition=event_condition(reflection_strength=Decimal("0.30"))
    )
    other_proposal = portfolio(other_forecast)
    negative_controls = {
        "high_expected_return_cannot_bypass_cost": (
            cost_rejected.outcome is DecisionOutcome.NO_TRADE
            and cost_rejected.directional_alpha is None
        ),
        "news_cannot_bypass_missing_risk": (
            risk_rejected.outcome is DecisionOutcome.NO_TRADE
            and "RISK_GATE_REJECTED" in risk_rejected.reason_codes
        ),
        "caller_trade_override_rejected": _rejected(
            lambda: IntegratedDecisionReport.model_validate_json(json.dumps(forged)),
            "INTEGRATED-DECISION-RECOMPUTATION",
        ),
        "risk_proposal_splice_rejected": _rejected(
            lambda: integrate_forecast_decision(
                net_edge=healthy_edge,
                overlay_policy=overlay_policy(),
                portfolio=proposal,
                risk=risk_decision(other_proposal),
                decision_time=DECISION_TIME,
            ),
            "RISK-PROPOSAL-SPLICE",
        ),
        "miscalibrated_cost_reduces_net_edge_confidence": (
            miscalibrated_edge.confidence_adjusted_probability_positive
            < miscalibrated_edge.raw_probability_positive
            and not miscalibrated_edge.probability_gate_passed
            and not miscalibrated_edge.cost_confidence_gate_passed
        ),
    }
    checks = {
        "pipeline_order_is_explicit_and_complete": directional.pipeline
        == (
            "FORECAST",
            "TRUTH_GATE",
            "PRICE_IN_GATE",
            "COST",
            "NET_EDGE",
            "PORTFOLIO",
            "RISK",
        ),
        "all_net_edge_gates_are_recomputed": (
            healthy_edge.allowed_before_portfolio_and_risk
            and all(
                (
                    healthy_edge.truth_gate_passed,
                    healthy_edge.price_in_gate_passed,
                    healthy_edge.uncertainty_gate_passed,
                    healthy_edge.ood_gate_passed,
                    healthy_edge.data_quality_gate_passed,
                    healthy_edge.event_increment_gate_passed,
                    healthy_edge.cost_confidence_gate_passed,
                    healthy_edge.expected_edge_gate_passed,
                    healthy_edge.probability_gate_passed,
                    healthy_edge.lower_bound_gate_passed,
                    healthy_edge.edge_cost_ratio_gate_passed,
                )
            )
        ),
        "directional_candidate_requires_portfolio_and_risk": (
            directional.outcome is DecisionOutcome.DIRECTIONAL_ALPHA
            and directional.portfolio_allows
            and directional.risk_allows
            and directional.directional_alpha is not None
        ),
        "no_trade_is_first_class_and_hashed": (
            risk_rejected.no_trade is not None
            and risk_rejected.no_trade.action == "NO_TRADE"
            and len(risk_rejected.no_trade.decision_sha256) == 64
        ),
        "risk_overlay_is_disjoint_from_directional_alpha": (
            overlay.outcome is DecisionOutcome.RISK_OVERLAY_ONLY
            and overlay.risk_overlay is not None
            and overlay.directional_alpha is None
            and not overlay.risk_overlay.directional_alpha_allowed
        ),
        "cost_model_covers_backtest_paper_live_and_all_components": (
            healthy_edge.costs.model.environments == ("BACKTEST", "PAPER", "LIVE")
            and len(healthy_edge.costs.model.components) == 11
        ),
        "decision_boundary_cannot_construct_orders": (
            _decision_has_no_execution_import()
            and not directional.order_submission_enabled
            and directional.live_trading_locked
        ),
        "development_evidence_cannot_promote_alpha": (
            not directional.alpha_promotion_eligible
            and not healthy_edge.alpha_promotion_eligible
            and not healthy_edge.policy.alpha_truth_claimed
            and not healthy_edge.policy.final_holdout_opened
        ),
    }
    return {
        "schema_version": "1.0.0",
        "phase": "V5-P10",
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "real_world_accuracy_claimed": False,
        "real_world_tca_claimed": False,
        "forward_evidence_present": False,
        "final_holdout_opened": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
        "checks": checks,
        "negative_controls": negative_controls,
        "directional_research_candidate": directional.model_dump(mode="json"),
        "cost_rejected_no_trade": cost_rejected.model_dump(mode="json"),
        "risk_rejected_no_trade": risk_rejected.model_dump(mode="json"),
        "risk_overlay_only": overlay.model_dump(mode="json"),
        "cost_miscalibration": miscalibrated_edge.model_dump(mode="json"),
        "acceptance_traceability": {
            "news_cannot_bypass_cost": [
                "tests/v5_p10/test_decision_integration.py::test_news_cannot_bypass_cost_gate",
            ],
            "news_cannot_bypass_risk": [
                "tests/v5_p10/test_decision_integration.py::test_news_cannot_bypass_independent_risk_gate",
                "tests/v5_p10/test_decision_integration.py::test_risk_decision_for_another_proposal_is_rejected_as_splice",
            ],
            "no_trade_first_class": [
                "tests/v5_p10/test_decision_integration.py::test_no_trade_is_a_hashed_first_class_exclusive_result",
            ],
            "risk_overlay_separate": [
                "tests/v5_p10/test_decision_integration.py::test_high_severity_medium_truth_is_risk_overlay_not_directional_alpha",
                "tests/v5_p10/test_decision_integration.py::test_overlay_without_protective_risk_decision_stays_no_trade",
            ],
            "unified_net_edge": [
                "tests/v5_p10/test_net_edge.py::test_healthy_net_edge_recomputes_all_economic_gates",
                "tests/v5_p10/test_net_edge.py::test_cost_miscalibration_haircut_can_fail_probability_gate",
            ],
            "execution_reality": [
                "tests/v5_p10/test_execution_cost_v2.py::test_cost_model_covers_every_required_component_and_environment",
                "tests/v5_p10/test_execution_cost_v2.py::test_replay_queue_requires_all_six_content_bindings",
            ],
        },
        "limitations": [
            "All forecasts, cost scenarios, portfolio proposals, and risk decisions are deterministic DEVELOPMENT fixtures.",
            "The directional result is a research candidate, not proven Alpha and not an executable order.",
            "No real public-data OOS, continuous forward, realized TCA, Paper, Shadow, Testnet, Final Holdout, or live evidence is present.",
            "Content hashes prove payload integrity and cross-binding, not external artifact authenticity.",
            "P10 revalidates RiskDecision structure and proposal binding but does not yet carry a cryptographic risk-service attestation receipt.",
            "The 0.60 probability threshold is a versioned bootstrap fixture; V5-P11/P12 must estimate thresholds per asset x horizon x sleeve from OOS evidence.",
        ],
        "result": "PASS_WITH_RECORDED_NEGATIVE_RESULTS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"V5-P10 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P10 decision integration evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P10 decision integration evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
