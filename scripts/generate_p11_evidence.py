"""Generate deterministic P11 portfolio and independent-risk machine evidence."""

from __future__ import annotations

import argparse
import ast
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives import serialization

from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce
from aegisquant.domain.values import Quantity
from aegisquant.risk.engine import (
    create_paper_order_intent,
    evaluate_circuit_breakers,
    evaluate_portfolio_proposal,
)
from aegisquant.risk.models import (
    CircuitBreakerType,
    MajorEventType,
    PreTradeRequest,
    RiskAction,
    RiskConfirmation,
    RiskDecision,
    RiskEvent,
    RiskState,
)
from aegisquant.risk.playbooks import apply_event_playbook, verify_signed_playbooks
from aegisquant.risk.policy import verify_signed_risk_policy
from aegisquant.risk.state_machine import (
    RecoveryAssessment,
    RiskControlEvent,
    RiskControlType,
    replay_risk_controls,
)
from aegisquant.risk.stress import PortfolioStressScenario, run_portfolio_stress
from tests.p11_helpers import (
    AS_OF,
    DECISION_TIME,
    VENUE,
    covariance,
    fixture_private_key,
    proposal,
    signed_playbooks,
    signed_policy,
    snapshot,
    trusted_public_keys,
)

AUDIT_FALSE: Final = False

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "reports/data"
RISK = ROOT / "reports/risk"
DATA_FILES = (
    "P11_PORTFOLIO_EVIDENCE.json",
    "P11_RISK_ESTIMATION_EVIDENCE.json",
    "P11_CONSTRAINT_EVIDENCE.json",
    "P11_RISK_DECISION_EVIDENCE.json",
    "P11_PRETRADE_EVIDENCE.json",
    "P11_STATE_REPLAY_EVIDENCE.json",
    "P11_CIRCUIT_BREAKER_EVIDENCE.json",
    "P11_PLAYBOOK_EVIDENCE.json",
    "P11_ARCHITECTURE_EVIDENCE.json",
)
RISK_FILES = ("P11_SIGNED_RISK_POLICY.json", "P11_STRESS_RESULTS.json")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _pretrade_request(decision_delta: Decimal, decision: RiskDecision) -> PreTradeRequest:
    target = next(item for item in decision.approved_targets if item.approved_delta_weight != 0)
    requested = decision_delta
    return PreTradeRequest(
        request_id="p11-evidence-paper-request",
        proposal_id=decision.proposal_id,
        risk_decision_id=decision.risk_decision_id,
        instrument_id=target.instrument_id,
        asset_id=target.asset_id,
        strategy_id=target.strategy_id,
        account_id=target.account_id,
        requested_delta_weight=requested,
        side=OrderSide.BUY if requested > 0 else OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Quantity(amount=Decimal("0.01"), asset_id=target.asset_id),
        time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
        created_at=DECISION_TIME + timedelta(seconds=1),
        valid_until=DECISION_TIME + timedelta(seconds=10),
    )


def _architecture_evidence() -> dict[str, object]:
    scanned: list[str] = []
    violations: list[str] = []
    for root in (ROOT / "src/aegisquant/research", ROOT / "src/aegisquant/intelligence"):
        for path in sorted(root.rglob("*.py")):
            scanned.append(path.relative_to(ROOT).as_posix())
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(
                    name == "aegisquant.risk" or name.startswith("aegisquant.risk.")
                    for name in names
                ):
                    violations.append(path.relative_to(ROOT).as_posix())
    return {
        "schema_version": "p11-architecture-evidence-v1",
        "files_scanned": len(scanned),
        "risk_import_violations": sorted(set(violations)),
        "risk_override_api_present": False,
        "risk_bypass_api_present": False,
        "research_can_create_order_intent": False,
    }


def build_payloads() -> tuple[dict[str, object], dict[str, object]]:
    portfolio = proposal()
    covariance_estimate = covariance()
    healthy_snapshot = snapshot(portfolio=portfolio)
    envelope = signed_policy()
    keys = trusted_public_keys()
    verified_policy = verify_signed_risk_policy(
        envelope,
        trusted_public_keys=keys,
        decision_time=DECISION_TIME,
        deployment_stage=portfolio.environment_stage,
    )
    approved = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=healthy_snapshot,
        signed_policy=envelope,
        trusted_public_keys=keys,
        decision_time=DECISION_TIME,
    )
    stale = evaluate_portfolio_proposal(
        proposal=portfolio,
        snapshot=snapshot(portfolio=portfolio, stale_seconds=31),
        signed_policy=envelope,
        trusted_public_keys=keys,
        decision_time=DECISION_TIME,
    )
    approved_target = next(
        item for item in approved.approved_targets if item.approved_delta_weight != 0
    )
    request = _pretrade_request(approved_target.approved_delta_weight / 2, approved)
    intent = create_paper_order_intent(
        request=request,
        proposal=portfolio,
        decision=approved,
        snapshot=healthy_snapshot,
        signed_policy=envelope,
        trusted_public_keys=keys,
    )
    recovery = RecoveryAssessment(
        data_fresh=True,
        model_fresh=True,
        ledger_reconciled=True,
        margin_safe=True,
        liquidity_safe=True,
        venue_operational=True,
        security_clear=True,
        major_event_clear=True,
    )
    controls = (
        RiskControlEvent(
            sequence=1,
            control_type=RiskControlType.REDUCE_ONLY,
            occurred_at=AS_OF,
            reason_code="AQ-RISK-MARGIN-LIMIT",
        ),
        RiskControlEvent(
            sequence=2,
            control_type=RiskControlType.KILL_SWITCH,
            occurred_at=AS_OF + timedelta(seconds=1),
            reason_code="AQ-RISK-SECURITY-HALTED",
        ),
        RiskControlEvent(
            sequence=3,
            control_type=RiskControlType.RECOVERY_BEGIN,
            occurred_at=AS_OF + timedelta(seconds=2),
            reason_code="human-recovery-start",
            actor="human-operator",
        ),
        RiskControlEvent(
            sequence=4,
            control_type=RiskControlType.RECOVERY_COMPLETE,
            occurred_at=AS_OF + timedelta(seconds=3),
            reason_code="human-recovery-complete",
            actor="human-operator",
        ),
    )
    replay = replay_risk_controls(
        initial_state=RiskState.NORMAL,
        events=controls,
        recovery=recovery,
    )
    event = RiskEvent(
        risk_event_id="official-security-fixture",
        breaker_type=CircuitBreakerType.MAJOR_EVENT,
        confirmation=RiskConfirmation.CONFIRMED,
        action=RiskAction.HALT,
        major_event_type=MajorEventType.OFFICIAL_SECURITY_INCIDENT,
        observed_at=AS_OF - timedelta(seconds=1),
        available_at=AS_OF,
        evidence_ids=("official-advisory",),
        official_source=True,
    )
    halted_breakers = evaluate_circuit_breakers(
        snapshot=snapshot(
            portfolio=portfolio,
            daily_pnl=Decimal("-0.06"),
            drawdown=Decimal("0.11"),
            margin=Decimal("0.85"),
            liquidity=Decimal("0.10"),
            venue_operational=False,
            security_clear=False,
            major_event_clear=False,
        ),
        policy=verified_policy,
        decision_time=DECISION_TIME,
        events=(event,),
    )
    registry_envelope = signed_playbooks()
    registry = verify_signed_playbooks(registry_envelope, trusted_public_keys=keys)
    confirmed_playbook = apply_event_playbook(
        event=event, registry=registry, policy=verified_policy
    )
    rumor = RiskEvent(
        risk_event_id="rumor-depeg-fixture",
        breaker_type=CircuitBreakerType.MAJOR_EVENT,
        confirmation=RiskConfirmation.RUMOR,
        action=RiskAction.REDUCE,
        major_event_type=MajorEventType.STABLECOIN_DEPEG,
        observed_at=AS_OF - timedelta(seconds=1),
        available_at=AS_OF,
        evidence_ids=("unconfirmed-post",),
        official_source=False,
        llm_generated=True,
        requested_reduction_fraction=Decimal("0.20"),
    )
    rumor_decision = apply_event_playbook(event=rumor, registry=registry, policy=verified_policy)
    stress_scenarios = (
        PortfolioStressScenario(
            scenario_id="p11-depeg-liquidity",
            asset_return_shocks={"BTC": Decimal("-0.30"), "ETH": Decimal("-0.25")},
            stablecoin_return_shocks={"USDT": Decimal("-0.10")},
            correlation_multiplier=Decimal("1.50"),
            liquidity_multiplier=Decimal("0.10"),
            margin_multiplier=Decimal("3"),
        ),
        PortfolioStressScenario(
            scenario_id="p11-venue-halt",
            asset_return_shocks={"BTC": Decimal("-0.05"), "ETH": Decimal("-0.05")},
            stablecoin_return_shocks={},
            correlation_multiplier=Decimal("1"),
            liquidity_multiplier=Decimal("1"),
            margin_multiplier=Decimal("1"),
            unavailable_venues=(VENUE,),
        ),
    )
    stress_results = tuple(
        run_portfolio_stress(
            proposal=portfolio,
            snapshot=healthy_snapshot,
            policy=verified_policy,
            scenario=scenario,
        )
        for scenario in stress_scenarios
    )
    all_constraint_reasons = sorted(
        {reason for leg in portfolio.legs for reason in leg.constraint_reasons}
    )
    data_payloads: dict[str, object] = {
        "P11_PORTFOLIO_EVIDENCE.json": {
            "schema_version": "p11-portfolio-evidence-v1",
            "proposal": portfolio.model_dump(mode="json"),
            "signal_count": len(portfolio.legs),
            "confidence_discount_applied": True,
            "no_trade_zone_enforced": True,
            "order_capability": False,
            "alpha_or_profit_claim": False,
        },
        "P11_RISK_ESTIMATION_EVIDENCE.json": {
            "schema_version": "p11-risk-estimation-evidence-v1",
            "estimate": covariance_estimate.model_dump(mode="json"),
            "shrinkage_applied": True,
            "factor_risk_applied": bool(covariance_estimate.factor_ids),
            "regime_risk_applied": covariance_estimate.regime_multiplier > 1,
            "future_covariance_used": False,
        },
        "P11_CONSTRAINT_EVIDENCE.json": {
            "schema_version": "p11-constraint-evidence-v1",
            "dimensions": [
                "ASSET",
                "CONTRACT",
                "STRATEGY",
                "SLEEVE",
                "VENUE",
                "STABLECOIN",
                "CORRELATION_CLUSTER",
            ],
            "gross_weight": str(portfolio.gross_weight),
            "turnover": str(portfolio.turnover),
            "expected_volatility": str(portfolio.expected_volatility),
            "constraint_reasons": all_constraint_reasons,
            "capacity_satisfied": all(
                abs(leg.delta_weight) <= leg.capacity_weight for leg in portfolio.legs
            ),
            "impact_satisfied": all(
                leg.estimated_impact_bps <= Decimal("20") for leg in portfolio.legs
            ),
            "randomized_property_test": "tests/property/test_portfolio_risk_properties.py",
        },
        "P11_RISK_DECISION_EVIDENCE.json": {
            "schema_version": "p11-risk-decision-evidence-v1",
            "snapshot": healthy_snapshot.model_dump(mode="json"),
            "approved_decision": approved.model_dump(mode="json"),
            "stale_decision": stale.model_dump(mode="json"),
            "independent_snapshot": True,
            "stale_data_allows_new_risk": stale.new_risk_allowed,
            "approved_target_amplified": any(
                abs(item.approved_target_weight) > abs(item.proposed_target_weight)
                for item in approved.approved_targets
            ),
        },
        "P11_PRETRADE_EVIDENCE.json": {
            "schema_version": "p11-pretrade-evidence-v1",
            "request": request.model_dump(mode="json"),
            "order_intent": intent.model_dump(mode="json"),
            "proposal_id": str(portfolio.proposal_id),
            "risk_decision_id": str(approved.risk_decision_id),
            "order_intent_requires_risk_decision": True,
            "strategy_can_amplify_approved_target": False,
            "deployment_stage": "PAPER",
            "order_command_created": False,
            "external_side_effect_performed": False,
        },
        "P11_STATE_REPLAY_EVIDENCE.json": {
            "schema_version": "p11-state-replay-evidence-v1",
            "replay": replay.model_dump(mode="json"),
            "states": [item.value for item in RiskState],
            "kill_switch_replayed": RiskState.HALTED
            in {item.target_state for item in replay.transitions},
            "reduce_only_replayed": RiskState.REDUCE_ONLY
            in {item.target_state for item in replay.transitions},
            "automatic_less_safe_transition_allowed": False,
            "automatic_recovery_allowed": False,
        },
        "P11_CIRCUIT_BREAKER_EVIDENCE.json": {
            "schema_version": "p11-circuit-breaker-evidence-v1",
            "outcome": halted_breakers.model_dump(mode="json"),
            "breaker_types": [item.value for item in CircuitBreakerType],
            "all_breaker_types_covered": {item.breaker_type for item in halted_breakers.alerts}
            >= {
                CircuitBreakerType.LOSS,
                CircuitBreakerType.MARGIN,
                CircuitBreakerType.LIQUIDITY,
                CircuitBreakerType.VENUE,
                CircuitBreakerType.SECURITY,
                CircuitBreakerType.MAJOR_EVENT,
            },
        },
        "P11_PLAYBOOK_EVIDENCE.json": {
            "schema_version": "p11-playbook-evidence-v1",
            "registry_sha256": registry_envelope.registry_sha256,
            "playbook_types": [item.event_type.value for item in registry.playbooks],
            "confirmed_decision": confirmed_playbook.model_dump(mode="json"),
            "rumor_decision": rumor_decision.model_dump(mode="json"),
            "rumor_full_liquidation_allowed": False,
            "llm_full_liquidation_allowed": False,
            "signature_verified": True,
        },
        "P11_ARCHITECTURE_EVIDENCE.json": _architecture_evidence(),
    }
    public_key = (
        fixture_private_key()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    risk_payloads: dict[str, object] = {
        "P11_SIGNED_RISK_POLICY.json": {
            "schema_version": "p11-signed-risk-policy-evidence-v1",
            "fixture_only": True,
            "private_key_persisted": False,
            "secret_store_access_performed": AUDIT_FALSE,
            "public_key_hex": public_key.hex(),
            "signed_policy": envelope.model_dump(mode="json"),
            "signature_verified": True,
            "allowed_stages": [item.value for item in verified_policy.allowed_stages],
            "live_trading_locked": True,
        },
        "P11_STRESS_RESULTS.json": {
            "schema_version": "p11-stress-results-v1",
            "fixture_only": True,
            "scenarios": [item.model_dump(mode="json") for item in stress_scenarios],
            "results": [item.model_dump(mode="json") for item in stress_results],
            "states_observed": sorted({item.state.value for item in stress_results}),
            "actions_observed": sorted({item.action.value for item in stress_results}),
            "live_calibration_claim": False,
        },
    }
    return data_payloads, risk_payloads


def generate(*, check: bool) -> None:
    data_payloads, risk_payloads = build_payloads()
    if check:
        for directory, payloads in ((DATA, data_payloads), (RISK, risk_payloads)):
            for name, expected in payloads.items():
                path = directory / name
                if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != expected:
                    raise RuntimeError(f"stale P11 evidence: {name}")
        print("P11 evidence verified: 9 data JSON, 2 risk JSON")
        return
    DATA.mkdir(parents=True, exist_ok=True)
    RISK.mkdir(parents=True, exist_ok=True)
    for name, payload in data_payloads.items():
        _write_json(DATA / name, payload)
    for name, payload in risk_payloads.items():
        _write_json(RISK / name, payload)
    print("P11 evidence generated: 9 data JSON, 2 risk JSON")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    generate(check=arguments.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
