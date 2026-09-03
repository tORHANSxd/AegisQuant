"""Historical truth-state replay and automatic reliability-decay tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.identifiers import ArtifactId, ClaimId, SourceIdentityId
from aegisquant.domain.truth import TruthState
from aegisquant.truth.lifecycle import (
    SourceReliabilityPolicy,
    SourceReliabilityRates,
    TruthModelLifecycleState,
    TruthModelReliabilityPolicy,
    TruthModelReliabilitySnapshot,
    TruthStateTransition,
    advance_source_reliability,
    evaluate_truth_model_reliability,
    initialize_source_reliability,
    replay_truth_state_as_of,
    select_source_reliability_as_of,
    select_truth_model_reliability_as_of,
)

BASE_TIME = datetime(2026, 2, 1, tzinfo=UTC)


def _transition(
    *,
    index: int,
    from_state: TruthState,
    to_state: TruthState,
    previous: TruthStateTransition | None,
) -> TruthStateTransition:
    instant = BASE_TIME + timedelta(hours=index)
    return TruthStateTransition(
        transition_id=ArtifactId(f"transition:{index}"),
        claim_id=ClaimId("claim:state-replay"),
        from_state=from_state,
        to_state=to_state,
        evidence_revision_id=ArtifactId(f"revision:{index}"),
        reason_codes=(f"REVISION_{index}",),
        previous_transition_id=previous.transition_id if previous is not None else None,
        previous_transition_sha256=previous.content_sha256() if previous is not None else None,
        effective_at=instant,
        observed_at=instant,
        created_at=instant,
        available_at=instant,
        version="truth-state-v1",
    )


def test_historical_revision_replay_supports_verified_to_retracted_without_lookahead() -> None:
    rumor = _transition(
        index=1,
        from_state=TruthState.UNVERIFIED,
        to_state=TruthState.RUMOR,
        previous=None,
    )
    verified = _transition(
        index=2,
        from_state=TruthState.RUMOR,
        to_state=TruthState.VERIFIED_PRIMARY,
        previous=rumor,
    )
    retracted = _transition(
        index=3,
        from_state=TruthState.VERIFIED_PRIMARY,
        to_state=TruthState.RETRACTED,
        previous=verified,
    )
    history = (retracted, rumor, verified)

    assert (
        replay_truth_state_as_of(
            claim_id=rumor.claim_id,
            transitions=history,
            as_of_time=BASE_TIME + timedelta(hours=1, minutes=30),
        ).state
        is TruthState.RUMOR
    )
    assert (
        replay_truth_state_as_of(
            claim_id=rumor.claim_id,
            transitions=history,
            as_of_time=BASE_TIME + timedelta(hours=2, minutes=30),
        ).state
        is TruthState.VERIFIED_PRIMARY
    )
    final = replay_truth_state_as_of(
        claim_id=rumor.claim_id,
        transitions=history,
        as_of_time=BASE_TIME + timedelta(hours=4),
    )
    assert final.state is TruthState.RETRACTED
    assert final.visible_transition_count == 3

    broken = retracted.model_copy(update={"previous_transition_sha256": "0" * 64})
    assert (
        replay_truth_state_as_of(
            claim_id=rumor.claim_id,
            transitions=(rumor, verified, broken),
            as_of_time=BASE_TIME + timedelta(hours=2, minutes=30),
        ).state
        is TruthState.VERIFIED_PRIMARY
    )
    with pytest.raises(ValueError, match="PREDECESSOR-HASH-MISMATCH"):
        replay_truth_state_as_of(
            claim_id=rumor.claim_id,
            transitions=(rumor, verified, broken),
            as_of_time=BASE_TIME + timedelta(hours=4),
        )

    with pytest.raises(ValueError, match="ILLEGAL-TRANSITION"):
        _transition(
            index=0,
            from_state=TruthState.UNVERIFIED,
            to_state=TruthState.RETRACTED,
            previous=None,
        )


def test_source_reliability_decays_on_worsening_rates_and_future_snapshot_is_hidden() -> None:
    policy = SourceReliabilityPolicy(
        policy_version="source-reliability-policy-v1",
        correction_weight=Decimal("0.2"),
        retraction_weight=Decimal("0.3"),
        false_claim_weight=Decimal("0.5"),
        minimum_reliability=Decimal("0.1"),
    )
    source_id = SourceIdentityId("source:reliability-test")
    initial = initialize_source_reliability(
        snapshot_id=ArtifactId("source-reliability:1"),
        source_identity_id=source_id,
        reliability_score=Decimal("0.9"),
        rates=SourceReliabilityRates(
            correction_rate=Decimal("0.05"),
            retraction_rate=Decimal("0.01"),
            false_claim_rate=Decimal("0.02"),
        ),
        observation_count=100,
        policy=policy,
        available_at=BASE_TIME,
    )
    degraded = advance_source_reliability(
        previous=initial,
        snapshot_id=ArtifactId("source-reliability:2"),
        rates=SourceReliabilityRates(
            correction_rate=Decimal("0.15"),
            retraction_rate=Decimal("0.06"),
            false_claim_rate=Decimal("0.12"),
        ),
        observation_count=200,
        policy=policy,
        observed_at=BASE_TIME + timedelta(days=1),
        available_at=BASE_TIME + timedelta(days=1),
    )

    assert degraded.reliability_score < initial.reliability_score
    assert "FALSE_CLAIM_RATE_INCREASED" in degraded.reason_codes
    assert (
        select_source_reliability_as_of(
            source_identity_id=source_id,
            history=(degraded, initial),
            as_of_time=BASE_TIME + timedelta(hours=12),
        )
        == initial
    )

    with pytest.raises(ValueError, match="BELOW-POLICY-FLOOR"):
        initialize_source_reliability(
            snapshot_id=ArtifactId("source-reliability:below-floor"),
            source_identity_id=source_id,
            reliability_score=Decimal("0.05"),
            rates=initial.rates,
            observation_count=100,
            policy=policy,
            available_at=BASE_TIME,
        )
    with pytest.raises(ValueError, match="TIME-REGRESSION"):
        advance_source_reliability(
            previous=initial,
            snapshot_id=ArtifactId("source-reliability:observed-too-early"),
            rates=initial.rates,
            observation_count=101,
            policy=policy,
            observed_at=BASE_TIME - timedelta(minutes=1),
            available_at=BASE_TIME + timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="POLICY-MISMATCH"):
        select_source_reliability_as_of(
            source_identity_id=source_id,
            history=(initial, degraded.model_copy(update={"policy_version": "other-policy"})),
            as_of_time=BASE_TIME + timedelta(days=2),
        )


def test_truth_model_reliability_progresses_to_retired_and_never_auto_recovers() -> None:
    policy = TruthModelReliabilityPolicy(
        policy_version="truth-model-reliability-policy-v1",
        minimum_high_confidence_samples=20,
        degraded_gap=Decimal("0.05"),
        restricted_gap=Decimal("0.10"),
        retired_gap=Decimal("0.20"),
    )
    first = evaluate_truth_model_reliability(
        snapshot_id=ArtifactId("model-reliability:1"),
        model_id="truth-logistic-baseline-v1",
        predicted_high_confidence_mean=Decimal("0.9"),
        actual_confirmed_rate=Decimal("0.83"),
        high_confidence_sample_count=30,
        policy=policy,
        outcomes_available_at=BASE_TIME,
        available_at=BASE_TIME,
    )
    second = evaluate_truth_model_reliability(
        snapshot_id=ArtifactId("model-reliability:2"),
        model_id=first.model_id,
        predicted_high_confidence_mean=Decimal("0.9"),
        actual_confirmed_rate=Decimal("0.76"),
        high_confidence_sample_count=40,
        policy=policy,
        outcomes_available_at=BASE_TIME + timedelta(days=1),
        available_at=BASE_TIME + timedelta(days=1),
        previous=first,
    )
    retired = evaluate_truth_model_reliability(
        snapshot_id=ArtifactId("model-reliability:3"),
        model_id=first.model_id,
        predicted_high_confidence_mean=Decimal("0.9"),
        actual_confirmed_rate=Decimal("0.65"),
        high_confidence_sample_count=50,
        policy=policy,
        outcomes_available_at=BASE_TIME + timedelta(days=2),
        available_at=BASE_TIME + timedelta(days=2),
        previous=second,
    )
    no_recovery = evaluate_truth_model_reliability(
        snapshot_id=ArtifactId("model-reliability:4"),
        model_id=first.model_id,
        predicted_high_confidence_mean=Decimal("0.9"),
        actual_confirmed_rate=Decimal("0.9"),
        high_confidence_sample_count=60,
        policy=policy,
        outcomes_available_at=BASE_TIME + timedelta(days=3),
        available_at=BASE_TIME + timedelta(days=3),
        previous=retired,
    )

    assert first.state is TruthModelLifecycleState.DEGRADED
    assert second.state is TruthModelLifecycleState.RESTRICTED
    assert retired.state is TruthModelLifecycleState.RETIRED
    assert no_recovery.state is TruthModelLifecycleState.RETIRED
    assert "NO_AUTOMATIC_RECOVERY" in no_recovery.reason_codes
    assert (
        select_truth_model_reliability_as_of(
            model_id=first.model_id,
            history=(no_recovery, second, first, retired),
            as_of_time=BASE_TIME + timedelta(days=1, hours=12),
        ).state
        is TruthModelLifecycleState.RESTRICTED
    )

    with pytest.raises(ValueError, match="FUTURE-OUTCOME"):
        evaluate_truth_model_reliability(
            snapshot_id=ArtifactId("model-reliability:future-outcome"),
            model_id=first.model_id,
            predicted_high_confidence_mean=Decimal("0.9"),
            actual_confirmed_rate=Decimal("0.9"),
            high_confidence_sample_count=61,
            policy=policy,
            outcomes_available_at=BASE_TIME + timedelta(days=5),
            available_at=BASE_TIME + timedelta(days=4),
            previous=no_recovery,
        )
    with pytest.raises(ValueError, match="COUNT-REGRESSION"):
        evaluate_truth_model_reliability(
            snapshot_id=ArtifactId("model-reliability:count-regression"),
            model_id=first.model_id,
            predicted_high_confidence_mean=Decimal("0.9"),
            actual_confirmed_rate=Decimal("0.9"),
            high_confidence_sample_count=59,
            policy=policy,
            outcomes_available_at=BASE_TIME + timedelta(days=4),
            available_at=BASE_TIME + timedelta(days=4),
            previous=no_recovery,
        )
    with pytest.raises(ValueError, match="POLICY-MISMATCH"):
        select_truth_model_reliability_as_of(
            model_id=first.model_id,
            history=(first, second.model_copy(update={"policy_version": "other-policy"})),
            as_of_time=BASE_TIME + timedelta(days=2),
        )
    with pytest.raises(ValueError, match="EMPTY-REASON"):
        snapshot_payload = {
            field_name: getattr(first, field_name)
            for field_name in TruthModelReliabilitySnapshot.model_fields
        }
        snapshot_payload["reason_codes"] = (" ",)
        TruthModelReliabilitySnapshot.model_validate(snapshot_payload)
