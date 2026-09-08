"""Generate deterministic V5-P11 Paper/Shadow forward-proof evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from aegisquant.forward import (
    ForwardMode,
    ForwardProofPolicy,
    ForwardProofStatus,
    ForwardRunKind,
    create_forward_sample,
    evaluate_forward_mode,
    evaluate_paper_shadow_forward,
)
from tests.v5_p11.helpers import START, digest, make_policy, make_session

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "v5" / "P11" / "FORWARD_PROOF_EVIDENCE.json"


def _rejected(operation: Callable[[], object], expected_code: str | None = None) -> bool:
    try:
        operation()
    except (TypeError, ValueError) as error:
        return expected_code is None or expected_code in str(error)
    return False


def build_payload() -> dict[str, object]:
    policy = make_policy()
    paper = evaluate_forward_mode(
        session=make_session(mode=ForwardMode.PAPER),
        policy=policy,
    )
    shadow = evaluate_forward_mode(
        session=make_session(mode=ForwardMode.SHADOW),
        policy=policy,
    )
    proof = evaluate_paper_shadow_forward(paper=paper, shadow=shadow)

    insufficient_events = evaluate_forward_mode(
        session=make_session(
            mode=ForwardMode.PAPER,
            run_kind=ForwardRunKind.WALL_CLOCK_FORWARD,
            days=30,
            sample_count=3,
        ),
        policy=policy,
    )
    gap_failure = evaluate_forward_mode(
        session=make_session(
            mode=ForwardMode.PAPER,
            heartbeat_step=timedelta(hours=2),
        ),
        policy=policy,
    )
    calibration_failure = evaluate_forward_mode(
        session=make_session(mode=ForwardMode.PAPER, poor_calibration=True),
        policy=policy,
    )

    forged_session = paper.session.model_copy(update={"backtest_substitution": True})
    negative_controls = {
        "backtest_run_kind_is_not_representable": _rejected(lambda: ForwardRunKind("BACKTEST")),
        "backtest_substitution_flag_is_rejected": _rejected(
            lambda: evaluate_forward_mode(session=forged_session, policy=policy)
        ),
        "future_source_data_is_rejected": _rejected(
            lambda: create_forward_sample(
                run_id="paper-run",
                mode=ForwardMode.PAPER,
                sample_id="future-source",
                event_independence_key="event-1",
                decision_report_sha256=digest("decision"),
                prediction_input_sha256=digest("input"),
                source_available_at=START + timedelta(seconds=1),
                decision_time=START,
                prediction_recorded_at=START + timedelta(seconds=2),
                outcome_available_at=START + timedelta(hours=1),
                realization_recorded_at=START + timedelta(hours=1, seconds=1),
                predicted_truth_probability=Decimal("0.5"),
                realized_truth=True,
                predicted_return=Decimal("0.01"),
                realized_return=Decimal("0.01"),
                predicted_cost=Decimal("0.001"),
                realized_cost=Decimal("0.001"),
                predicted_event_increment=Decimal("0.002"),
                realized_event_increment=Decimal("0.002"),
            ),
            "AQ-TIME-LOOKAHEAD",
        ),
        "minimum_30_day_policy_cannot_be_lowered": _rejected(
            lambda: ForwardProofPolicy.model_validate(
                {**policy.model_dump(mode="python"), "minimum_calendar_days": 29}
            )
        ),
        "heartbeat_gap_fails_closed": (
            gap_failure.status is ForwardProofStatus.FAIL_CLOSED
            and "CONTINUOUS_FORWARD_GAP_EXCEEDED" in gap_failure.reason_codes
        ),
        "poor_calibration_fails_closed": (
            calibration_failure.status is ForwardProofStatus.FAIL_CLOSED
            and not calibration_failure.truth_calibration_pass
            and not calibration_failure.forecast_calibration_pass
            and not calibration_failure.event_increment_attribution_pass
        ),
    }
    checks = {
        "continuous_forward_chain_is_recomputed": (
            paper.continuous_forward_data_pass
            and shadow.continuous_forward_data_pass
            and paper.maximum_heartbeat_gap_seconds == Decimal("3600")
        ),
        "future_corrections_are_forbidden": (
            paper.no_future_corrections_pass
            and shadow.no_future_corrections_pass
            and all(item.prediction_revision == 0 for item in paper.session.samples)
        ),
        "truth_forecast_cost_calibration_is_recomputed": (
            paper.truth_calibration_pass
            and paper.forecast_calibration_pass
            and paper.cost_calibration_pass
        ),
        "event_increment_attribution_is_recomputed": (
            paper.event_increment_attribution_pass
            and paper.event_increment_attribution.independent_event_count == 4
        ),
        "incident_and_restart_recovery_are_bound": (
            paper.incident_log_pass
            and paper.restart_recovery_pass
            and shadow.incident_log_pass
            and shadow.restart_recovery_pass
        ),
        "development_fixture_cannot_claim_forward": (
            paper.status is ForwardProofStatus.EXTEND_PAPER
            and shadow.status is ForwardProofStatus.EXTEND_PAPER
            and proof.decision.value == "NO_PROMOTION"
            and not proof.paper_pass
            and not proof.shadow_pass
        ),
        "insufficient_events_extend_instead_of_lowering_gate": (
            insufficient_events.status is ForwardProofStatus.EXTEND_PAPER
            and "INDEPENDENT_EVENT_SAMPLE_INSUFFICIENT" in insufficient_events.reason_codes
        ),
        "p11_cannot_emit_canary_or_unlock_live": (
            not proof.canary_review_ready
            and not proof.alpha_promotion_eligible
            and not proof.order_submission_enabled
            and proof.live_trading_locked
        ),
    }
    return {
        "schema_version": "1.0.0",
        "phase": "V5-P11",
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "real_forward_evidence_present": False,
        "paper_calendar_days_observed": 0,
        "shadow_calendar_days_observed": 0,
        "backtest_substituted_for_forward": False,
        "final_holdout_opened": False,
        "canary_review_ready": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
        "checks": checks,
        "negative_controls": negative_controls,
        "development_fixture_proof": proof.model_dump(mode="json"),
        "insufficient_event_control": insufficient_events.model_dump(mode="json"),
        "heartbeat_gap_control": gap_failure.model_dump(mode="json"),
        "calibration_failure_control": calibration_failure.model_dump(mode="json"),
        "acceptance_traceability": {
            "continuous_forward_data": [
                "tests/v5_p11/test_forward_evaluation.py::test_heartbeat_gap_fails_closed",
                "tests/v5_p11/test_forward_records.py::test_heartbeat_chain_tamper_is_rejected_at_session_boundary",
            ],
            "no_future_corrections": [
                "tests/v5_p11/test_forward_records.py::test_future_source_data_is_rejected",
                "tests/v5_p11/test_forward_records.py::test_prediction_and_sample_hashes_reject_revision",
                "tests/v5_p11/test_forward_evaluation.py::test_future_correction_attempt_fails_closed",
            ],
            "predicted_vs_realized_calibration": [
                "tests/v5_p11/test_forward_evaluation.py::test_calibration_failure_fails_closed",
                "tests/v5_p11/test_forward_evaluation.py::test_30_day_wall_clock_run_can_pass_contract_gate",
            ],
            "event_increment_attribution": [
                "tests/v5_p11/test_forward_evaluation.py::test_calibration_failure_fails_closed",
            ],
            "incident_and_recovery": [
                "tests/v5_p11/test_forward_evaluation.py::test_data_loss_incident_fails_closed",
                "tests/v5_p11/test_forward_records.py::test_restart_receipt_is_mandatory",
            ],
            "minimum_duration_and_independent_events": [
                "tests/v5_p11/test_forward_evaluation.py::test_policy_cannot_lower_master_plan_duration",
                "tests/v5_p11/test_forward_evaluation.py::test_insufficient_independent_events_extends_instead_of_lowering_threshold",
            ],
            "backtest_not_forward": [
                "tests/v5_p11/test_forward_records.py::test_model_construct_cannot_bypass_session_revalidation",
                "tests/v5_p11/test_forward_evaluation.py::test_development_fixture_never_becomes_forward_proof",
            ],
        },
        "limitations": [
            "All included sessions are deterministic DEVELOPMENT fixtures and are not wall-clock Paper or Shadow evidence.",
            "Zero real calendar days have been observed; the master-plan minimum of 30 calendar days is not met.",
            "The independent-event threshold is precommitted for contract testing, not established by a production power study.",
            "The 30-day wall-clock paths in tests validate fail-closed contract logic only and do not attest that time elapsed.",
            "No backtest, accelerated runtime, fixture, or synthetic result is accepted as Forward evidence.",
            "P11 cannot emit CANARY_REVIEW_READY and cannot unlock live trading.",
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
            raise SystemExit(f"V5-P11 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P11 forward-proof evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P11 forward-proof evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
