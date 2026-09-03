"""Deterministic builders for V5-P11 contract tests and DEVELOPMENT evidence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.domain.evidence import EvidenceTier
from aegisquant.forward import (
    ForwardHeartbeat,
    ForwardIncidentSeverity,
    ForwardMode,
    ForwardProofPolicy,
    ForwardRunKind,
    ForwardSample,
    ForwardSession,
    create_forward_heartbeat,
    create_forward_incident,
    create_forward_incident_log,
    create_forward_proof_policy,
    create_forward_recovery_receipt,
    create_forward_sample,
    create_forward_session,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def make_policy(
    *,
    minimum_calendar_days: int = 30,
    minimum_independent_event_count: int = 4,
) -> ForwardProofPolicy:
    return create_forward_proof_policy(
        version="v5-p11-policy-1",
        approved_at=START - timedelta(days=2),
        effective_from=START - timedelta(days=1),
        minimum_calendar_days=minimum_calendar_days,
        minimum_independent_event_count=minimum_independent_event_count,
        independent_event_threshold_rationale=(
            "Precommitted DEVELOPMENT threshold; production requires a domain power study."
        ),
        maximum_heartbeat_gap_seconds=3600,
        maximum_truth_brier_score=Decimal("0.05"),
        maximum_truth_calibration_error=Decimal("0.10"),
        maximum_forecast_mae=Decimal("0.005"),
        minimum_forecast_direction_accuracy=Decimal("0.75"),
        maximum_cost_mae=Decimal("0.0002"),
        maximum_cost_underprediction_rate=Decimal("0.50"),
        maximum_event_increment_mae=Decimal("0.003"),
        minimum_event_direction_accuracy=Decimal("0.75"),
    )


def make_heartbeats(
    *,
    run_id: str,
    mode: ForwardMode,
    started_at: datetime,
    ended_at: datetime,
    step: timedelta = timedelta(hours=1),
) -> tuple[ForwardHeartbeat, ...]:
    instants: list[datetime] = []
    instant = started_at
    while instant < ended_at:
        instants.append(instant)
        instant += step
    instants.append(ended_at)
    result: list[ForwardHeartbeat] = []
    previous: str | None = None
    for sequence, observed_at in enumerate(instants):
        heartbeat = create_forward_heartbeat(
            run_id=run_id,
            mode=mode,
            sequence=sequence,
            observed_at=observed_at,
            source_available_at=observed_at,
            previous_heartbeat_sha256=previous,
        )
        result.append(heartbeat)
        previous = heartbeat.heartbeat_sha256
    return tuple(result)


def make_samples(
    *,
    run_id: str,
    mode: ForwardMode,
    count: int = 4,
    poor_calibration: bool = False,
) -> tuple[ForwardSample, ...]:
    result: list[ForwardSample] = []
    for index in range(count):
        positive = index % 2 == 0
        predicted_return = Decimal("0.02") if positive else Decimal("-0.02")
        realized_return = Decimal("0.018") if positive else Decimal("-0.018")
        predicted_increment = Decimal("0.01") if positive else Decimal("-0.01")
        realized_increment = Decimal("0.009") if positive else Decimal("-0.009")
        realized_truth = positive
        predicted_truth = Decimal("0.9") if positive else Decimal("0.1")
        if poor_calibration:
            realized_truth = not realized_truth
            realized_return = -realized_return
            realized_increment = -realized_increment
        decision_time = START + timedelta(hours=2 + index * 3)
        result.append(
            create_forward_sample(
                run_id=run_id,
                mode=mode,
                sample_id=f"sample-{index:04d}",
                event_independence_key=f"independent-event-{index:04d}",
                decision_report_sha256=digest(f"p10-decision-{index}"),
                prediction_input_sha256=digest(f"pit-input-{index}"),
                source_available_at=decision_time - timedelta(minutes=1),
                decision_time=decision_time,
                prediction_recorded_at=decision_time + timedelta(seconds=1),
                outcome_available_at=decision_time + timedelta(hours=1),
                realization_recorded_at=decision_time + timedelta(hours=1, seconds=1),
                predicted_truth_probability=predicted_truth,
                realized_truth=realized_truth,
                predicted_return=predicted_return,
                realized_return=realized_return,
                predicted_cost=Decimal("0.001"),
                realized_cost=(Decimal("0.0011") if index % 2 == 1 else Decimal("0.0009")),
                predicted_event_increment=predicted_increment,
                realized_event_increment=realized_increment,
            )
        )
    return tuple(result)


def make_session(
    *,
    mode: ForwardMode,
    run_kind: ForwardRunKind = ForwardRunKind.DEVELOPMENT_FIXTURE,
    days: int = 1,
    sample_count: int = 4,
    poor_calibration: bool = False,
    heartbeat_step: timedelta = timedelta(hours=1),
    data_loss_detected: bool = False,
    future_correction_attempted: bool = False,
) -> ForwardSession:
    run_id = f"{mode.value.lower()}-run"
    ended_at = START + timedelta(days=days)
    heartbeats = make_heartbeats(
        run_id=run_id,
        mode=mode,
        started_at=START,
        ended_at=ended_at,
        step=heartbeat_step,
    )
    samples = make_samples(
        run_id=run_id,
        mode=mode,
        count=sample_count,
        poor_calibration=poor_calibration,
    )
    incident = create_forward_incident(
        run_id=run_id,
        mode=mode,
        incident_id=f"{mode.value.lower()}-planned-restart",
        severity=ForwardIncidentSeverity.INFO,
        category="PLANNED_RESTART_RECOVERY_DRILL",
        detected_at=START + timedelta(hours=16),
        recorded_at=START + timedelta(hours=16, seconds=1),
        resolved_at=START + timedelta(hours=16, minutes=2),
        requires_restart=True,
        data_loss_detected=data_loss_detected,
        future_correction_attempted=future_correction_attempted,
    )
    incident_log = create_forward_incident_log(
        run_id=run_id,
        mode=mode,
        coverage_started_at=START,
        coverage_ended_at=ended_at,
        incidents=(incident,),
        log_complete=True,
    )
    checkpoint_time = START + timedelta(hours=15)
    chain_head = max(
        (item for item in heartbeats if item.observed_at <= checkpoint_time),
        key=lambda item: item.sequence,
    )
    receipt = create_forward_recovery_receipt(
        run_id=run_id,
        mode=mode,
        incident_id=incident.incident_id,
        checkpoint_sha256=digest(f"{run_id}-checkpoint"),
        chain_head_sha256=chain_head.heartbeat_sha256,
        checkpoint_recorded_at=checkpoint_time,
        resumed_at=START + timedelta(hours=16, minutes=1),
        last_durable_sequence=chain_head.sequence,
        gap_count=0,
        duplicate_count=0,
        restored_without_loss=True,
        planned_drill=True,
    )
    return create_forward_session(
        pair_id="paper-shadow-pair-1",
        run_id=run_id,
        mode=mode,
        run_kind=run_kind,
        evidence_tier=(
            EvidenceTier.DEVELOPMENT
            if run_kind is ForwardRunKind.DEVELOPMENT_FIXTURE
            else (
                EvidenceTier.PAPER_FORWARD
                if mode is ForwardMode.PAPER
                else EvidenceTier.SHADOW_FORWARD
            )
        ),
        started_at=START,
        ended_at=ended_at,
        heartbeats=heartbeats,
        samples=samples,
        incident_log=incident_log,
        recovery_receipts=(receipt,),
        time_compressed=run_kind is ForwardRunKind.DEVELOPMENT_FIXTURE,
    )
