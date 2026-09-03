"""Point-in-time, append-only, incident, and recovery contract tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.evidence import EvidenceTier
from aegisquant.forward import (
    ForwardIncidentSeverity,
    ForwardMode,
    ForwardRunKind,
    ForwardSession,
    create_forward_incident,
    create_forward_incident_log,
    create_forward_recovery_receipt,
    create_forward_sample,
    create_forward_session,
    evaluate_forward_mode,
)
from tests.v5_p11.helpers import START, digest, make_policy, make_session


def test_future_source_data_is_rejected() -> None:
    with pytest.raises(ValueError, match="AQ-TIME-LOOKAHEAD"):
        create_forward_sample(
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
        )


def test_prediction_must_be_recorded_before_outcome_is_available() -> None:
    with pytest.raises(ValueError, match="AQ-P11-FORWARD-SAMPLE-TIME-ORDER-VIOLATION"):
        create_forward_sample(
            run_id="paper-run",
            mode=ForwardMode.PAPER,
            sample_id="late-prediction",
            event_independence_key="event-1",
            decision_report_sha256=digest("decision"),
            prediction_input_sha256=digest("input"),
            source_available_at=START,
            decision_time=START,
            prediction_recorded_at=START + timedelta(hours=2),
            outcome_available_at=START + timedelta(hours=1),
            realization_recorded_at=START + timedelta(hours=2),
            predicted_truth_probability=Decimal("0.5"),
            realized_truth=True,
            predicted_return=Decimal("0.01"),
            realized_return=Decimal("0.01"),
            predicted_cost=Decimal("0.001"),
            realized_cost=Decimal("0.001"),
            predicted_event_increment=Decimal("0.002"),
            realized_event_increment=Decimal("0.002"),
        )


def test_prediction_and_sample_hashes_reject_revision() -> None:
    sample = make_session(mode=ForwardMode.PAPER).samples[0]
    forged = sample.model_copy(update={"predicted_return": Decimal("0.99")})
    with pytest.raises(ValidationError, match="AQ-P11-PREDICTION-HASH-MISMATCH"):
        type(sample).model_validate_json(forged.model_dump_json())


def test_heartbeat_chain_tamper_is_rejected_at_session_boundary() -> None:
    session = make_session(mode=ForwardMode.PAPER)
    forged_heartbeat = session.heartbeats[1].model_copy(
        update={"previous_heartbeat_sha256": digest("wrong-chain-head")}
    )
    forged = session.model_copy(
        update={"heartbeats": (session.heartbeats[0], forged_heartbeat, *session.heartbeats[2:])}
    )
    with pytest.raises(
        ValidationError,
        match=r"HEARTBEAT-HASH-MISMATCH|HEARTBEAT-CHAIN-BROKEN",
    ):
        ForwardSession.model_validate_json(forged.model_dump_json())


def test_model_construct_cannot_bypass_session_revalidation() -> None:
    session = make_session(mode=ForwardMode.PAPER)
    forged = session.model_copy(update={"backtest_substitution": True})
    with pytest.raises(ValidationError):
        evaluate_forward_mode(session=forged, policy=make_policy())


def test_wall_clock_tier_must_match_mode() -> None:
    fixture = make_session(mode=ForwardMode.PAPER)
    with pytest.raises(ValidationError, match="WALL-CLOCK-FORWARD-EVIDENCE-MISMATCH"):
        create_forward_session(
            pair_id=fixture.pair_id,
            run_id=fixture.run_id,
            mode=fixture.mode,
            run_kind=ForwardRunKind.WALL_CLOCK_FORWARD,
            evidence_tier=EvidenceTier.SHADOW_FORWARD,
            started_at=fixture.started_at,
            ended_at=fixture.ended_at,
            heartbeats=fixture.heartbeats,
            samples=fixture.samples,
            incident_log=fixture.incident_log,
            recovery_receipts=fixture.recovery_receipts,
            time_compressed=False,
        )


def test_real_forward_cannot_be_time_compressed() -> None:
    fixture = make_session(mode=ForwardMode.PAPER)
    with pytest.raises(ValidationError, match="WALL-CLOCK-FORWARD-EVIDENCE-MISMATCH"):
        create_forward_session(
            pair_id=fixture.pair_id,
            run_id=fixture.run_id,
            mode=fixture.mode,
            run_kind=ForwardRunKind.WALL_CLOCK_FORWARD,
            evidence_tier=EvidenceTier.PAPER_FORWARD,
            started_at=fixture.started_at,
            ended_at=fixture.ended_at,
            heartbeats=fixture.heartbeats,
            samples=fixture.samples,
            incident_log=fixture.incident_log,
            recovery_receipts=fixture.recovery_receipts,
            time_compressed=True,
        )


def test_restart_receipt_is_mandatory() -> None:
    session = make_session(mode=ForwardMode.PAPER)
    with pytest.raises(ValidationError):
        create_forward_session(
            pair_id=session.pair_id,
            run_id=session.run_id,
            mode=session.mode,
            run_kind=session.run_kind,
            evidence_tier=session.evidence_tier,
            started_at=session.started_at,
            ended_at=session.ended_at,
            heartbeats=session.heartbeats,
            samples=session.samples,
            incident_log=session.incident_log,
            recovery_receipts=(),
            time_compressed=session.time_compressed,
        )


def test_duplicate_independent_event_samples_are_rejected() -> None:
    session = make_session(mode=ForwardMode.PAPER)
    duplicate = create_forward_sample(
        run_id=session.run_id,
        mode=session.mode,
        sample_id="sample-duplicate",
        event_independence_key=session.samples[0].event_independence_key,
        decision_report_sha256=digest("duplicate-decision"),
        prediction_input_sha256=digest("duplicate-input"),
        source_available_at=START + timedelta(hours=12, minutes=59),
        decision_time=START + timedelta(hours=13),
        prediction_recorded_at=START + timedelta(hours=13, seconds=1),
        outcome_available_at=START + timedelta(hours=14),
        realization_recorded_at=START + timedelta(hours=14, seconds=1),
        predicted_truth_probability=Decimal("0.9"),
        realized_truth=True,
        predicted_return=Decimal("0.02"),
        realized_return=Decimal("0.018"),
        predicted_cost=Decimal("0.001"),
        realized_cost=Decimal("0.0009"),
        predicted_event_increment=Decimal("0.01"),
        realized_event_increment=Decimal("0.009"),
    )
    with pytest.raises(ValidationError, match="INDEPENDENT-EVENT-SAMPLE-DUPLICATED"):
        create_forward_session(
            pair_id=session.pair_id,
            run_id=session.run_id,
            mode=session.mode,
            run_kind=session.run_kind,
            evidence_tier=session.evidence_tier,
            started_at=session.started_at,
            ended_at=session.ended_at,
            heartbeats=session.heartbeats,
            samples=(*session.samples, duplicate),
            incident_log=session.incident_log,
            recovery_receipts=session.recovery_receipts,
            time_compressed=session.time_compressed,
        )


def test_incident_outside_log_coverage_is_rejected() -> None:
    incident = create_forward_incident(
        run_id="paper-run",
        mode=ForwardMode.PAPER,
        incident_id="future-incident",
        severity=ForwardIncidentSeverity.WARNING,
        category="OUTSIDE_WINDOW",
        detected_at=START + timedelta(days=2),
        recorded_at=START + timedelta(days=2, seconds=1),
        resolved_at=START + timedelta(days=2, minutes=1),
        requires_restart=False,
    )
    with pytest.raises(ValidationError, match="INCIDENT-OUTSIDE-LOG-COVERAGE"):
        create_forward_incident_log(
            run_id="paper-run",
            mode=ForwardMode.PAPER,
            coverage_started_at=START,
            coverage_ended_at=START + timedelta(days=1),
            incidents=(incident,),
            log_complete=True,
        )


def test_recovery_durable_sequence_must_bind_session_chain() -> None:
    session = make_session(mode=ForwardMode.PAPER)
    original = session.recovery_receipts[0]
    forged = create_forward_recovery_receipt(
        run_id=original.run_id,
        mode=original.mode,
        incident_id=original.incident_id,
        checkpoint_sha256=original.checkpoint_sha256,
        chain_head_sha256=original.pre_restart_chain_head_sha256,
        checkpoint_recorded_at=original.checkpoint_recorded_at,
        resumed_at=original.resumed_at,
        last_durable_sequence=len(session.heartbeats),
        gap_count=0,
        duplicate_count=0,
        restored_without_loss=True,
        planned_drill=True,
    )
    with pytest.raises(ValidationError, match="DURABLE-SEQUENCE-OUT-OF-RANGE"):
        create_forward_session(
            pair_id=session.pair_id,
            run_id=session.run_id,
            mode=session.mode,
            run_kind=session.run_kind,
            evidence_tier=session.evidence_tier,
            started_at=session.started_at,
            ended_at=session.ended_at,
            heartbeats=session.heartbeats,
            samples=session.samples,
            incident_log=session.incident_log,
            recovery_receipts=(forged,),
            time_compressed=session.time_compressed,
        )
