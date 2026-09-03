"""V5-P12 seven-hard-gate decision tests."""

from __future__ import annotations

from functools import lru_cache

from aegisquant.canary_readiness import (
    CanaryReadinessDecision,
    P12GateName,
    P12GateStatus,
    P12NextAction,
    create_p12_evidence_bundle,
    evaluate_p12_canary_readiness,
)
from tests.v5_p12.helpers import (
    ASSESSMENT_TIME,
    CompleteP12Fixture,
    make_complete_fixture,
    make_current_blocked_bundle,
    make_forward_proof,
    make_testnet_evidence,
)


@lru_cache(maxsize=1)
def complete_fixture() -> CompleteP12Fixture:
    return make_complete_fixture()


def test_exact_seven_hard_gates_are_required_for_canary_review() -> None:
    fixture = complete_fixture()
    assessment = evaluate_p12_canary_readiness(
        policy=fixture.policy,
        evidence_bundle=fixture.bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    assert tuple(item.gate for item in assessment.gates) == tuple(P12GateName)
    assert all(item.status is P12GateStatus.PASS for item in assessment.gates)
    assert assessment.gate_count == assessment.passed_gate_count == 7
    assert assessment.failed_gate_count == assessment.blocked_gate_count == 0
    assert assessment.decision is CanaryReadinessDecision.CANARY_REVIEW_READY
    assert assessment.next_action is P12NextAction.REQUEST_MANUAL_CANARY_REVIEW
    assert assessment.canary_review_ready is True


def test_canary_review_ready_never_unlocks_live_or_capital() -> None:
    fixture = complete_fixture()
    assessment = evaluate_p12_canary_readiness(
        policy=fixture.policy,
        evidence_bundle=fixture.bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    assert assessment.weighted_score_used is False
    assert assessment.canary_capital_authorized is False
    assert assessment.user_approval_received is False
    assert assessment.manual_live_unlock_received is False
    assert assessment.live_order_submission_enabled is False
    assert assessment.live_trading_locked is True
    assert assessment.final_holdout_opened is False


def test_current_development_evidence_blocks_all_gates_and_extends_paper() -> None:
    policy, bundle = make_current_blocked_bundle()
    assessment = evaluate_p12_canary_readiness(
        policy=policy,
        evidence_bundle=bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    assert assessment.decision is CanaryReadinessDecision.NO_PROMOTION
    assert assessment.passed_gate_count == assessment.failed_gate_count == 0
    assert assessment.blocked_gate_count == 7
    assert assessment.next_action is P12NextAction.EXTEND_PAPER
    assert "REAL_PAPER_FORWARD_EVIDENCE_ABSENT" in assessment.blocking_reason_codes
    assert "REAL_SHADOW_FORWARD_EVIDENCE_ABSENT" in assessment.blocking_reason_codes
    assert "REAL_BINANCE_TESTNET_EVIDENCE_ABSENT" in assessment.blocking_reason_codes
    assert "EXTERNAL_ALERT_DELIVERY_EVIDENCE_ABSENT" in assessment.blocking_reason_codes
    assert assessment.canary_review_ready is False


def test_simulator_cannot_satisfy_real_binance_testnet_gate() -> None:
    fixture = complete_fixture()
    simulator = make_testnet_evidence(real=False, forward_proof=fixture.forward_proof)
    bundle = create_p12_evidence_bundle(
        forward_proof=fixture.forward_proof,
        testnet=simulator,
        source_artifact_sha256={"reports/execution/P12_ADAPTER_EVIDENCE.json": "a" * 64},
    )
    assessment = evaluate_p12_canary_readiness(
        policy=fixture.policy,
        evidence_bundle=bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    testnet = next(item for item in assessment.gates if item.gate is P12GateName.TESTNET)
    assert testnet.status is P12GateStatus.BLOCKED_EXTERNAL_INPUT
    assert testnet.reason_codes == ("SIMULATOR_IS_NOT_REAL_BINANCE_TESTNET",)
    assert assessment.decision is CanaryReadinessDecision.NO_PROMOTION


def test_insufficient_testnet_orders_fail_instead_of_lowering_threshold() -> None:
    fixture = make_complete_fixture(accepted_order_count=2)
    assessment = evaluate_p12_canary_readiness(
        policy=fixture.policy,
        evidence_bundle=fixture.bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    testnet = next(item for item in assessment.gates if item.gate is P12GateName.TESTNET)
    assert testnet.status is P12GateStatus.FAIL
    assert "TESTNET_ACCEPTED_ORDER_COUNT_INSUFFICIENT" in testnet.reason_codes
    assert assessment.next_action is P12NextAction.REMEDIATE_AND_RETEST
    assert assessment.decision is CanaryReadinessDecision.NO_PROMOTION


def test_risk_failure_cannot_be_averaged_against_six_passes() -> None:
    fixture = make_complete_fixture(risk_checks_pass=False)
    assessment = evaluate_p12_canary_readiness(
        policy=fixture.policy,
        evidence_bundle=fixture.bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    risk = next(item for item in assessment.gates if item.gate is P12GateName.RISK)
    assert risk.status is P12GateStatus.FAIL
    assert assessment.passed_gate_count == 6
    assert assessment.decision is CanaryReadinessDecision.NO_PROMOTION
    assert assessment.weighted_score_used is False


def test_real_forward_contract_without_testnet_requests_external_evidence() -> None:
    fixture = complete_fixture()
    bundle = create_p12_evidence_bundle(
        forward_proof=make_forward_proof(real=True),
        source_artifact_sha256={"reports/v5/P11/FORWARD_PROOF_EVIDENCE.json": "b" * 64},
    )
    assessment = evaluate_p12_canary_readiness(
        policy=fixture.policy,
        evidence_bundle=bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    assert assessment.passed_gate_count == 5
    assert assessment.blocked_gate_count == 2
    assert assessment.next_action is P12NextAction.PROVIDE_EXTERNAL_EVIDENCE
    assert assessment.decision is CanaryReadinessDecision.NO_PROMOTION
