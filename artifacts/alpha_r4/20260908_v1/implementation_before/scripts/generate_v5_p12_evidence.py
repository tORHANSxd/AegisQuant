"""Generate deterministic V5-P12 Testnet and Canary-readiness evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from aegisquant.canary_readiness import (
    CanaryReadinessDecision,
    P12CanaryReadinessAssessment,
    P12GateName,
    P12GateResult,
    P12GateStatus,
    create_p12_evidence_bundle,
    evaluate_p12_canary_readiness,
)
from aegisquant.data.hashing import sha256_file
from tests.v5_p12.helpers import (
    ASSESSMENT_TIME,
    make_complete_fixture,
    make_current_blocked_bundle,
    make_testnet_evidence,
    source_artifact_commitments,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "v5" / "P12" / "CANARY_READINESS_EVIDENCE.json"


def _rejected(operation: Callable[[], object], expected_code: str | None = None) -> bool:
    try:
        operation()
    except (TypeError, ValueError) as error:
        return expected_code is None or expected_code in str(error)
    return False


def _assessment_summary(assessment: P12CanaryReadinessAssessment) -> dict[str, object]:
    return {
        "policy_sha256": assessment.policy.policy_sha256,
        "evidence_bundle_sha256": assessment.evidence_bundle.bundle_sha256,
        "gates": [_gate_summary(item) for item in assessment.gates],
        "gate_count": assessment.gate_count,
        "passed_gate_count": assessment.passed_gate_count,
        "failed_gate_count": assessment.failed_gate_count,
        "blocked_gate_count": assessment.blocked_gate_count,
        "decision": assessment.decision,
        "next_action": assessment.next_action,
        "blocking_reason_codes": assessment.blocking_reason_codes,
        "weighted_score_used": assessment.weighted_score_used,
        "canary_review_ready": assessment.canary_review_ready,
        "canary_capital_authorized": assessment.canary_capital_authorized,
        "user_approval_received": assessment.user_approval_received,
        "manual_live_unlock_received": assessment.manual_live_unlock_received,
        "live_order_submission_enabled": assessment.live_order_submission_enabled,
        "live_trading_locked": assessment.live_trading_locked,
        "final_holdout_opened": assessment.final_holdout_opened,
        "assessment_sha256": assessment.assessment_sha256,
    }


def _gate_summary(gate: P12GateResult) -> dict[str, object]:
    payload = gate.model_dump(mode="json")
    payload["evidence_sha256"] = [{"sha256": digest} for digest in gate.evidence_sha256]
    return payload


def _artifact_hash_records(commitments: dict[str, str]) -> list[dict[str, str]]:
    return [{"path": path, "sha256": digest} for path, digest in sorted(commitments.items())]


def build_payload() -> dict[str, object]:
    policy, current_bundle = make_current_blocked_bundle()
    current = evaluate_p12_canary_readiness(
        policy=policy,
        evidence_bundle=current_bundle,
        assessed_at=ASSESSMENT_TIME,
    )

    complete_fixture = make_complete_fixture()
    contract_only = evaluate_p12_canary_readiness(
        policy=complete_fixture.policy,
        evidence_bundle=complete_fixture.bundle,
        assessed_at=ASSESSMENT_TIME,
    )
    simulated_bundle = create_p12_evidence_bundle(
        forward_proof=complete_fixture.forward_proof,
        testnet=make_testnet_evidence(
            real=False,
            forward_proof=complete_fixture.forward_proof,
        ),
        source_artifact_sha256={
            "reports/execution/P12_ADAPTER_EVIDENCE.json": sha256_file(
                ROOT / "reports/execution/P12_ADAPTER_EVIDENCE.json"
            )
        },
    )
    simulated = evaluate_p12_canary_readiness(
        policy=complete_fixture.policy,
        evidence_bundle=simulated_bundle,
        assessed_at=ASSESSMENT_TIME,
    )

    forged_current = current.model_copy(
        update={
            "decision": CanaryReadinessDecision.CANARY_REVIEW_READY,
            "canary_review_ready": True,
        }
    )
    testnet_simulator_gate = next(
        item for item in simulated.gates if item.gate is P12GateName.TESTNET
    )
    checks = {
        "exact_seven_hard_gates_are_recomputed": (
            tuple(item.gate for item in current.gates) == tuple(P12GateName)
            and current.gate_count == 7
        ),
        "current_evidence_blocks_all_seven_gates": (
            current.passed_gate_count == 0
            and current.failed_gate_count == 0
            and current.blocked_gate_count == 7
        ),
        "development_simulator_is_not_real_testnet": (
            testnet_simulator_gate.status is P12GateStatus.BLOCKED_EXTERNAL_INPUT
            and "SIMULATOR_IS_NOT_REAL_BINANCE_TESTNET" in testnet_simulator_gate.reason_codes
        ),
        "all_pass_contract_only_emits_manual_review_readiness": (
            contract_only.decision is CanaryReadinessDecision.CANARY_REVIEW_READY
            and contract_only.canary_review_ready
            and not contract_only.canary_capital_authorized
            and not contract_only.user_approval_received
            and not contract_only.manual_live_unlock_received
            and not contract_only.live_order_submission_enabled
            and contract_only.live_trading_locked
        ),
        "weighted_scores_cannot_offset_hard_gates": (
            not current.weighted_score_used
            and current.decision is CanaryReadinessDecision.NO_PROMOTION
        ),
        "forged_readiness_is_revalidated": _rejected(
            lambda: P12CanaryReadinessAssessment.model_validate_json(
                forged_current.model_dump_json()
            ),
            "CANARY-ASSESSMENT-RECOMPUTATION-MISMATCH",
        ),
    }
    return {
        "schema_version": "1.0.0",
        "phase": "V5-P12",
        "evidence_tier": "DEVELOPMENT",
        "real_paper_calendar_days_observed": 0,
        "real_shadow_calendar_days_observed": 0,
        "real_binance_testnet_evidence_present": False,
        "testnet_credential_reference_present": False,
        "testnet_network_requests_performed": 0,
        "real_testnet_orders_observed": 0,
        "real_testnet_fills_observed": 0,
        "real_testnet_reconciliation_present": False,
        "external_alert_delivery_evidence_present": False,
        "real_account_access_performed": False,
        "secret_store_access_performed": False,  # nosec B105 - boolean audit outcome
        "live_domain_used": False,
        "withdrawals_enabled": False,
        "canary_review_ready": False,
        "live_order_submission_enabled": False,
        "live_trading_locked": True,
        "final_holdout_opened": False,
        "source_artifact_sha256": _artifact_hash_records(source_artifact_commitments()),
        "global_promotion_gate_evaluated": False,
        "global_promotion_decision": "NO_PROMOTION",
        "global_promotion_blocking_dimensions": [
            "DATA",
            "ECONOMICS",
            "STATISTICS",
            "FORWARD",
        ],
        "current_assessment": _assessment_summary(current),
        "development_controls": {
            "all_pass_contract_fixture_is_not_observed_evidence": True,  # nosec B105
            "all_pass_contract_fixture_assessment_sha256": contract_only.assessment_sha256,
            "simulator_control_assessment_sha256": simulated.assessment_sha256,
            "simulator_testnet_gate": _gate_summary(testnet_simulator_gate),
        },
        "checks": checks,
        "acceptance_traceability": {
            "seven_hard_gates": [
                "tests/v5_p12/test_readiness_gates.py::test_exact_seven_hard_gates_are_required_for_canary_review",
                "tests/v5_p12/test_readiness_gates.py::test_risk_failure_cannot_be_averaged_against_six_passes",
            ],
            "real_binance_testnet": [
                "tests/v5_p12/test_readiness_gates.py::test_simulator_cannot_satisfy_real_binance_testnet_gate",
                "tests/v5_p12/test_evidence_receipts.py::test_real_testnet_shape_requires_private_network_and_credential_reference",
            ],
            "external_alert_delivery": [
                "tests/v5_p12/test_alert_boundaries.py::test_loopback_delivery_is_explicitly_development_only",
                "tests/v5_p12/test_alert_boundaries.py::test_partial_delivery_cannot_claim_remote_acknowledgment",
            ],
            "reconciliation": [
                "tests/v5_p12/test_evidence_receipts.py::test_reconciliation_result_is_recomputed_and_authoritative_facts_stay_immutable",
                "tests/v5_p12/test_evidence_receipts.py::test_risk_receipt_cannot_be_spliced_to_another_testnet_run",
            ],
            "attestation_and_live_lock": [
                "tests/v5_p12/test_evidence_receipts.py::test_attestation_uses_precommitted_trusted_key_and_detects_wrong_signer",
                "tests/v5_p12/test_readiness_gates.py::test_canary_review_ready_never_unlocks_live_or_capital",
            ],
        },
        "limitations": [
            "The current assessment contains no real wall-clock Paper, Shadow, or Binance Testnet evidence.",
            "The all-pass path is a deterministic contract fixture and is not an observed readiness result.",
            "The legacy Binance adapter is a no-network simulator and cannot satisfy the Testnet gate.",
            "Loopback alert delivery does not prove delivery to an external on-call recipient.",
            "No credential reference, secret store, real account, Live domain, withdrawal, or Live order capability was accessed.",
            "CANARY_REVIEW_READY would still require manual review and cannot unlock capital or Live trading.",
            "The global Promotion Gate is not evaluated because Data, Economics, Statistics, and Forward proof remain incomplete.",
        ],
        "result": "PASS_WITH_RECORDED_NEGATIVE_RESULTS",
        "promotion_decision": "NO_PROMOTION",
        "required_next_action": "EXTEND_PAPER",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"V5-P12 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P12 Canary-readiness evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P12 Canary-readiness evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
