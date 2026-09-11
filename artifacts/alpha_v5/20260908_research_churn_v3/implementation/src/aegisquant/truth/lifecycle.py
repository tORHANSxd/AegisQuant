"""Append-only Truth state replay and automatic reliability decay."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final, Self

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ArtifactId, ClaimId, SourceIdentityId
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.truth import TruthState
from aegisquant.domain.values import NonNegativeDecimal, UnitInterval

_ESTABLISHED_TRUTH_STATES: Final = frozenset(TruthState) - {TruthState.UNVERIFIED}
_ALLOWED_TRUTH_STATE_TRANSITIONS: Final = {
    TruthState.UNVERIFIED: frozenset(
        {
            TruthState.RUMOR,
            TruthState.PARTIALLY_CORROBORATED,
            TruthState.VERIFIED_PRIMARY,
            TruthState.VERIFIED_MULTI_SOURCE,
            TruthState.CONTRADICTED,
            TruthState.UNKNOWN,
        }
    ),
    **{state: _ESTABLISHED_TRUTH_STATES for state in _ESTABLISHED_TRUTH_STATES},
}


class TruthStateTransition(DomainModel):
    """One evidence-bound state revision in a hash-linked claim history."""

    transition_id: ArtifactId
    claim_id: ClaimId
    from_state: TruthState
    to_state: TruthState
    evidence_revision_id: ArtifactId
    reason_codes: tuple[str, ...] = Field(min_length=1)
    previous_transition_id: ArtifactId | None = None
    previous_transition_sha256: str | None = None
    effective_at: UtcDateTime
    observed_at: UtcDateTime
    available_at: UtcDateTime
    created_at: UtcDateTime
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        if self.to_state is TruthState.UNVERIFIED:
            raise ValueError("AQ-TRUTH-STATE-CANNOT-RETURN-TO-UNVERIFIED")
        if self.to_state not in _ALLOWED_TRUTH_STATE_TRANSITIONS[self.from_state]:
            raise ValueError("AQ-TRUTH-STATE-ILLEGAL-TRANSITION")
        if not (self.effective_at <= self.observed_at <= self.created_at <= self.available_at):
            raise ValueError("AQ-TRUTH-STATE-TRANSITION-TIME-ORDER")
        if (self.previous_transition_id is None) != (self.previous_transition_sha256 is None):
            raise ValueError("AQ-TRUTH-STATE-TRANSITION-PREDECESSOR-PARTIAL")
        if self.previous_transition_sha256 is not None:
            ensure_sha256(
                self.previous_transition_sha256,
                field_name="previous_transition_sha256",
            )
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("AQ-TRUTH-STATE-EMPTY-REASON")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("AQ-TRUTH-STATE-DUPLICATE-REASON")
        if not self.version.strip():
            raise ValueError("AQ-TRUTH-STATE-EMPTY-VERSION")
        return self

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class TruthStateSnapshot(DomainModel):
    claim_id: ClaimId
    as_of_time: UtcDateTime
    state: TruthState
    visible_transition_count: int = Field(ge=0)
    latest_transition_id: ArtifactId | None
    latest_transition_sha256: str | None
    visible_history_sha256: str

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        ensure_sha256(self.visible_history_sha256, field_name="visible_history_sha256")
        if (self.latest_transition_id is None) != (self.latest_transition_sha256 is None):
            raise ValueError("AQ-TRUTH-STATE-SNAPSHOT-LATEST-PARTIAL")
        if self.latest_transition_sha256 is not None:
            ensure_sha256(
                self.latest_transition_sha256,
                field_name="latest_transition_sha256",
            )
        if (self.visible_transition_count == 0) != (self.latest_transition_id is None):
            raise ValueError("AQ-TRUTH-STATE-SNAPSHOT-COUNT-MISMATCH")
        return self


def _validated_truth_history(
    transitions: tuple[TruthStateTransition, ...], claim_id: ClaimId
) -> tuple[TruthStateTransition, ...]:
    if any(item.claim_id != claim_id for item in transitions):
        raise ValueError("AQ-TRUTH-STATE-HISTORY-CLAIM-MISMATCH")
    if len({str(item.transition_id) for item in transitions}) != len(transitions):
        raise ValueError("AQ-TRUTH-STATE-DUPLICATE-TRANSITION-ID")
    ordered = tuple(
        sorted(
            transitions,
            key=lambda item: (
                item.available_at,
                item.observed_at,
                item.effective_at,
                str(item.transition_id),
            ),
        )
    )
    current = TruthState.UNVERIFIED
    previous: TruthStateTransition | None = None
    for transition in ordered:
        expected_id = previous.transition_id if previous is not None else None
        expected_sha = previous.content_sha256() if previous is not None else None
        if transition.previous_transition_id != expected_id:
            raise ValueError("AQ-TRUTH-STATE-TRANSITION-PREDECESSOR-ID-MISMATCH")
        if transition.previous_transition_sha256 != expected_sha:
            raise ValueError("AQ-TRUTH-STATE-TRANSITION-PREDECESSOR-HASH-MISMATCH")
        if transition.from_state is not current:
            raise ValueError("AQ-TRUTH-STATE-TRANSITION-FROM-STATE-MISMATCH")
        if previous is not None and not (
            previous.effective_at <= transition.effective_at
            and previous.observed_at <= transition.observed_at
            and previous.available_at < transition.available_at
        ):
            raise ValueError("AQ-TRUTH-STATE-TRANSITION-TIME-REGRESSION")
        current = transition.to_state
        previous = transition
    return ordered


def replay_truth_state_as_of(
    *,
    claim_id: ClaimId,
    transitions: tuple[TruthStateTransition, ...],
    as_of_time: datetime,
) -> TruthStateSnapshot:
    """Replay only state revisions available at the requested decision time."""

    as_of = ensure_utc(as_of_time)
    visible = _validated_truth_history(
        tuple(item for item in transitions if item.available_at <= as_of),
        claim_id,
    )
    latest = visible[-1] if visible else None
    hashes = [item.content_sha256() for item in visible]
    return TruthStateSnapshot(
        claim_id=claim_id,
        as_of_time=as_of,
        state=latest.to_state if latest is not None else TruthState.UNVERIFIED,
        visible_transition_count=len(visible),
        latest_transition_id=latest.transition_id if latest is not None else None,
        latest_transition_sha256=latest.content_sha256() if latest is not None else None,
        visible_history_sha256=canonical_sha256(hashes),
    )


class SourceReliabilityRates(DomainModel):
    correction_rate: UnitInterval
    retraction_rate: UnitInterval
    false_claim_rate: UnitInterval


class SourceReliabilityPolicy(DomainModel):
    policy_version: str = Field(min_length=1)
    correction_weight: UnitInterval
    retraction_weight: UnitInterval
    false_claim_weight: UnitInterval
    minimum_reliability: UnitInterval

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.correction_weight + self.retraction_weight + self.false_claim_weight > Decimal("1"):
            raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-WEIGHT-SUM")
        return self


class SourceReliabilitySnapshot(DomainModel):
    snapshot_id: ArtifactId
    source_identity_id: SourceIdentityId
    reliability_score: UnitInterval
    rates: SourceReliabilityRates
    observation_count: int = Field(ge=0)
    policy_version: str = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    previous_snapshot_id: ArtifactId | None = None
    previous_snapshot_sha256: str | None = None
    created_at: UtcDateTime
    available_at: UtcDateTime
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.created_at > self.available_at:
            raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-TIME-ORDER")
        if (self.previous_snapshot_id is None) != (self.previous_snapshot_sha256 is None):
            raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-PREDECESSOR-PARTIAL")
        if self.previous_snapshot_sha256 is not None:
            ensure_sha256(
                self.previous_snapshot_sha256,
                field_name="previous_snapshot_sha256",
            )
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-EMPTY-REASON")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-DUPLICATE-REASON")
        return self

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def initialize_source_reliability(
    *,
    snapshot_id: ArtifactId,
    source_identity_id: SourceIdentityId,
    reliability_score: Decimal,
    rates: SourceReliabilityRates,
    observation_count: int,
    policy: SourceReliabilityPolicy,
    available_at: datetime,
) -> SourceReliabilitySnapshot:
    available = ensure_utc(available_at)
    if reliability_score < policy.minimum_reliability:
        raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-BELOW-POLICY-FLOOR")
    return SourceReliabilitySnapshot(
        snapshot_id=snapshot_id,
        source_identity_id=source_identity_id,
        reliability_score=reliability_score,
        rates=rates,
        observation_count=observation_count,
        policy_version=policy.policy_version,
        reason_codes=("SOURCE_REGISTRY_PRIOR",),
        created_at=available,
        available_at=available,
        version="source-reliability-v1",
    )


def advance_source_reliability(
    *,
    previous: SourceReliabilitySnapshot,
    snapshot_id: ArtifactId,
    rates: SourceReliabilityRates,
    observation_count: int,
    policy: SourceReliabilityPolicy,
    observed_at: datetime,
    available_at: datetime,
) -> SourceReliabilitySnapshot:
    """Decay reliability only when correction, retraction, or false-claim rates worsen."""

    observed = ensure_utc(observed_at)
    available = ensure_utc(available_at)
    if previous.policy_version != policy.policy_version:
        raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-POLICY-MISMATCH")
    if (
        previous.available_at > observed
        or previous.available_at >= available
        or observed > available
    ):
        raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-TIME-REGRESSION")
    if observation_count < previous.observation_count:
        raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-COUNT-REGRESSION")
    deltas = {
        "CORRECTION_RATE_INCREASED": max(
            rates.correction_rate - previous.rates.correction_rate, Decimal("0")
        ),
        "RETRACTION_RATE_INCREASED": max(
            rates.retraction_rate - previous.rates.retraction_rate, Decimal("0")
        ),
        "FALSE_CLAIM_RATE_INCREASED": max(
            rates.false_claim_rate - previous.rates.false_claim_rate, Decimal("0")
        ),
    }
    penalty = (
        deltas["CORRECTION_RATE_INCREASED"] * policy.correction_weight
        + deltas["RETRACTION_RATE_INCREASED"] * policy.retraction_weight
        + deltas["FALSE_CLAIM_RATE_INCREASED"] * policy.false_claim_weight
    )
    reliability = min(
        previous.reliability_score,
        max(
            policy.minimum_reliability,
            previous.reliability_score * (Decimal("1") - penalty),
        ),
    )
    reasons = tuple(reason for reason, delta in deltas.items() if delta > 0) or (
        "NO_WORSENING_NO_AUTOMATIC_UPGRADE",
    )
    return SourceReliabilitySnapshot(
        snapshot_id=snapshot_id,
        source_identity_id=previous.source_identity_id,
        reliability_score=reliability,
        rates=rates,
        observation_count=observation_count,
        policy_version=policy.policy_version,
        reason_codes=reasons,
        previous_snapshot_id=previous.snapshot_id,
        previous_snapshot_sha256=previous.content_sha256(),
        created_at=observed,
        available_at=available,
        version=previous.version,
    )


def select_source_reliability_as_of(
    *,
    source_identity_id: SourceIdentityId,
    history: tuple[SourceReliabilitySnapshot, ...],
    as_of_time: datetime,
) -> SourceReliabilitySnapshot:
    as_of = ensure_utc(as_of_time)
    visible = tuple(item for item in history if item.available_at <= as_of)
    if not visible:
        raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-NOT-YET-AVAILABLE")
    if any(item.source_identity_id != source_identity_id for item in visible):
        raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-HISTORY-MISMATCH")
    if len({str(item.snapshot_id) for item in visible}) != len(visible):
        raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-DUPLICATE-SNAPSHOT")
    if len({item.policy_version for item in visible}) != 1:
        raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-POLICY-MISMATCH")
    ordered = tuple(sorted(visible, key=lambda item: (item.available_at, str(item.snapshot_id))))
    previous: SourceReliabilitySnapshot | None = None
    for item in ordered:
        expected_id = previous.snapshot_id if previous is not None else None
        expected_sha = previous.content_sha256() if previous is not None else None
        if (
            item.previous_snapshot_id != expected_id
            or item.previous_snapshot_sha256 != expected_sha
        ):
            raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-PREDECESSOR-MISMATCH")
        if previous is not None and (
            item.available_at <= previous.available_at
            or item.observation_count < previous.observation_count
            or item.reliability_score > previous.reliability_score
        ):
            raise ValueError("AQ-TRUTH-SOURCE-RELIABILITY-HISTORY-REGRESSION")
        previous = item
    return ordered[-1]


class TruthModelLifecycleState(StrEnum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    RESTRICTED = "RESTRICTED"
    RETIRED = "RETIRED"


_MODEL_STATE_SEVERITY = {
    TruthModelLifecycleState.NORMAL: 0,
    TruthModelLifecycleState.DEGRADED: 1,
    TruthModelLifecycleState.RESTRICTED: 2,
    TruthModelLifecycleState.RETIRED: 3,
}


class TruthModelReliabilityPolicy(DomainModel):
    policy_version: str = Field(min_length=1)
    minimum_high_confidence_samples: int = Field(gt=0)
    degraded_gap: UnitInterval
    restricted_gap: UnitInterval
    retired_gap: UnitInterval

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if not self.degraded_gap < self.restricted_gap < self.retired_gap:
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-THRESHOLD-ORDER")
        return self


class TruthModelReliabilitySnapshot(DomainModel):
    snapshot_id: ArtifactId
    model_id: str = Field(min_length=1)
    state: TruthModelLifecycleState
    predicted_high_confidence_mean: UnitInterval
    actual_confirmed_rate: UnitInterval
    high_confidence_sample_count: int = Field(ge=0)
    calibration_gap: NonNegativeDecimal
    policy_version: str = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    previous_snapshot_id: ArtifactId | None = None
    previous_snapshot_sha256: str | None = None
    outcomes_available_at: UtcDateTime
    created_at: UtcDateTime
    available_at: UtcDateTime
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        expected_gap = max(
            self.predicted_high_confidence_mean - self.actual_confirmed_rate,
            Decimal("0"),
        )
        if self.calibration_gap != expected_gap:
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-GAP-MISMATCH")
        if not self.outcomes_available_at <= self.created_at <= self.available_at:
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-TIME-ORDER")
        if (self.previous_snapshot_id is None) != (self.previous_snapshot_sha256 is None):
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-PREDECESSOR-PARTIAL")
        if self.previous_snapshot_sha256 is not None:
            ensure_sha256(
                self.previous_snapshot_sha256,
                field_name="previous_snapshot_sha256",
            )
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-EMPTY-REASON")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-DUPLICATE-REASON")
        return self

    def content_sha256(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def evaluate_truth_model_reliability(
    *,
    snapshot_id: ArtifactId,
    model_id: str,
    predicted_high_confidence_mean: Decimal,
    actual_confirmed_rate: Decimal,
    high_confidence_sample_count: int,
    policy: TruthModelReliabilityPolicy,
    outcomes_available_at: datetime,
    available_at: datetime,
    previous: TruthModelReliabilitySnapshot | None = None,
) -> TruthModelReliabilitySnapshot:
    """Move NORMAL→DEGRADED→RESTRICTED→RETIRED without automatic recovery."""

    outcomes_available = ensure_utc(outcomes_available_at)
    available = ensure_utc(available_at)
    if outcomes_available > available:
        raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-FUTURE-OUTCOME")
    if previous is not None:
        if previous.model_id != model_id or previous.policy_version != policy.policy_version:
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-HISTORY-MISMATCH")
        if previous.available_at >= available:
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-TIME-REGRESSION")
        if outcomes_available < previous.available_at:
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-OUTCOME-TIME-REGRESSION")
        if high_confidence_sample_count < previous.high_confidence_sample_count:
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-COUNT-REGRESSION")
    gap = max(predicted_high_confidence_mean - actual_confirmed_rate, Decimal("0"))
    if high_confidence_sample_count < policy.minimum_high_confidence_samples:
        proposed = previous.state if previous is not None else TruthModelLifecycleState.NORMAL
        reasons = ("INSUFFICIENT_HIGH_CONFIDENCE_SAMPLE",)
    elif gap >= policy.retired_gap:
        proposed = TruthModelLifecycleState.RETIRED
        reasons = ("HIGH_CONFIDENCE_CALIBRATION_GAP_RETIRED",)
    elif gap >= policy.restricted_gap:
        proposed = TruthModelLifecycleState.RESTRICTED
        reasons = ("HIGH_CONFIDENCE_CALIBRATION_GAP_RESTRICTED",)
    elif gap >= policy.degraded_gap:
        proposed = TruthModelLifecycleState.DEGRADED
        reasons = ("HIGH_CONFIDENCE_CALIBRATION_GAP_DEGRADED",)
    else:
        proposed = TruthModelLifecycleState.NORMAL
        reasons = ("HIGH_CONFIDENCE_CALIBRATION_WITHIN_POLICY",)
    if (
        previous is not None
        and _MODEL_STATE_SEVERITY[previous.state] > _MODEL_STATE_SEVERITY[proposed]
    ):
        state = previous.state
        reasons = (*reasons, "NO_AUTOMATIC_RECOVERY")
    else:
        state = proposed
    return TruthModelReliabilitySnapshot(
        snapshot_id=snapshot_id,
        model_id=model_id,
        state=state,
        predicted_high_confidence_mean=predicted_high_confidence_mean,
        actual_confirmed_rate=actual_confirmed_rate,
        high_confidence_sample_count=high_confidence_sample_count,
        calibration_gap=gap,
        policy_version=policy.policy_version,
        reason_codes=reasons,
        previous_snapshot_id=previous.snapshot_id if previous is not None else None,
        previous_snapshot_sha256=previous.content_sha256() if previous is not None else None,
        outcomes_available_at=outcomes_available,
        created_at=available,
        available_at=available,
        version="truth-model-reliability-v1",
    )


def select_truth_model_reliability_as_of(
    *,
    model_id: str,
    history: tuple[TruthModelReliabilitySnapshot, ...],
    as_of_time: datetime,
) -> TruthModelReliabilitySnapshot:
    as_of = ensure_utc(as_of_time)
    visible = tuple(item for item in history if item.available_at <= as_of)
    if not visible:
        raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-NOT-YET-AVAILABLE")
    if any(item.model_id != model_id for item in visible):
        raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-HISTORY-MISMATCH")
    if len({str(item.snapshot_id) for item in visible}) != len(visible):
        raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-DUPLICATE-SNAPSHOT")
    if len({item.policy_version for item in visible}) != 1:
        raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-POLICY-MISMATCH")
    ordered = tuple(sorted(visible, key=lambda item: (item.available_at, str(item.snapshot_id))))
    previous: TruthModelReliabilitySnapshot | None = None
    for item in ordered:
        expected_id = previous.snapshot_id if previous is not None else None
        expected_sha = previous.content_sha256() if previous is not None else None
        if (
            item.previous_snapshot_id != expected_id
            or item.previous_snapshot_sha256 != expected_sha
        ):
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-PREDECESSOR-MISMATCH")
        if previous is not None and (
            item.available_at <= previous.available_at
            or item.outcomes_available_at < previous.available_at
            or item.high_confidence_sample_count < previous.high_confidence_sample_count
            or _MODEL_STATE_SEVERITY[item.state] < _MODEL_STATE_SEVERITY[previous.state]
        ):
            raise ValueError("AQ-TRUTH-MODEL-RELIABILITY-HISTORY-REGRESSION")
        previous = item
    return ordered[-1]
