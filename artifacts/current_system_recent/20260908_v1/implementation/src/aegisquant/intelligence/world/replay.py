"""Point-in-time content replay, leakage stress, placebo checks, and read models."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.values import FiniteDecimal, UnitInterval
from aegisquant.intelligence.world.models import ContentRevision, RuntimeSourceState, WorldSource


class EngagementPoint(DomainModel):
    snapshot_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    observed_at: UtcDateTime
    available_at: UtcDateTime
    metrics: dict[str, int]

    @model_validator(mode="after")
    def validate_engagement(self) -> EngagementPoint:
        if self.observed_at > self.available_at:
            raise ValueError("engagement cannot be available before observation")
        if not self.metrics or any(value < 0 for value in self.metrics.values()):
            raise ValueError("engagement metrics must be non-empty and non-negative")
        return self


class ContentReplaySelection(DomainModel):
    content_id: str
    as_of_time: UtcDateTime
    revision: ContentRevision
    engagement: EngagementPoint | None
    excluded_future_revision_count: int = Field(ge=0)
    excluded_future_engagement_count: int = Field(ge=0)
    deleted_as_of: bool

    @model_validator(mode="after")
    def validate_selection(self) -> ContentReplaySelection:
        if self.revision.available_at > self.as_of_time:
            raise ValueError("replay selected future content revision")
        if self.engagement is not None and self.engagement.available_at > self.as_of_time:
            raise ValueError("replay selected future engagement")
        if self.deleted_as_of != (self.revision.deleted_at is not None):
            raise ValueError("replay deletion state disagrees with selected revision")
        return self


def _validate_revision_ledger(revisions: Sequence[ContentRevision]) -> None:
    if not revisions:
        raise ValueError("revision ledger cannot be empty")
    content_ids = {item.content_id for item in revisions}
    if len(content_ids) != 1:
        raise ValueError("revision ledger cannot mix content ids")
    ordered = sorted(revisions, key=lambda item: item.revision)
    if [item.revision for item in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError("revision ledger must retain the first and every intermediate version")
    if any(later.available_at < earlier.available_at for earlier, later in pairwise(ordered)):
        raise ValueError("revision availability must be monotonic")


def replay_content_as_of(
    *,
    revisions: Sequence[ContentRevision],
    engagement: Sequence[EngagementPoint],
    as_of_time: datetime,
) -> ContentReplaySelection:
    _validate_revision_ledger(revisions)
    as_of = ensure_utc(as_of_time)
    eligible_revisions = [item for item in revisions if item.available_at <= as_of]
    if not eligible_revisions:
        raise ValueError("AQ-REPLAY-CONTENT-NOT-YET-AVAILABLE")
    selected_revision = max(eligible_revisions, key=lambda item: item.revision)
    for item in engagement:
        if item.content_id != selected_revision.content_id:
            raise ValueError("engagement ledger cannot mix content ids")
    eligible_engagement = [item for item in engagement if item.available_at <= as_of]
    selected_engagement = (
        max(eligible_engagement, key=lambda item: (item.available_at, item.snapshot_id))
        if eligible_engagement
        else None
    )
    return ContentReplaySelection(
        content_id=selected_revision.content_id,
        as_of_time=as_of,
        revision=selected_revision,
        engagement=selected_engagement,
        excluded_future_revision_count=len(revisions) - len(eligible_revisions),
        excluded_future_engagement_count=len(engagement) - len(eligible_engagement),
        deleted_as_of=selected_revision.deleted_at is not None,
    )


class FutureEngagementAudit(DomainModel):
    content_id: str
    as_of_time: UtcDateTime
    selected_snapshot_id: str | None
    selected_available_at: UtcDateTime | None
    excluded_future_snapshot_ids: tuple[str, ...]
    passed: bool

    @model_validator(mode="after")
    def future_engagement_is_excluded(self) -> FutureEngagementAudit:
        expected = (
            self.selected_available_at is None or self.selected_available_at <= self.as_of_time
        )
        if self.passed != expected:
            raise ValueError("future-engagement audit result is inconsistent")
        return self


def audit_future_engagement(
    *, content_id: str, snapshots: Sequence[EngagementPoint], as_of_time: datetime
) -> FutureEngagementAudit:
    as_of = ensure_utc(as_of_time)
    if any(item.content_id != content_id for item in snapshots):
        raise ValueError("future-engagement audit cannot mix content ids")
    eligible = [item for item in snapshots if item.available_at <= as_of]
    selected = max(eligible, key=lambda item: item.available_at) if eligible else None
    excluded = tuple(sorted(item.snapshot_id for item in snapshots if item.available_at > as_of))
    return FutureEngagementAudit(
        content_id=content_id,
        as_of_time=as_of,
        selected_snapshot_id=selected.snapshot_id if selected else None,
        selected_available_at=selected.available_at if selected else None,
        excluded_future_snapshot_ids=excluded,
        passed=selected is None or selected.available_at <= as_of,
    )


class ReplayEvidence(DomainModel):
    evidence_id: str = Field(min_length=1)
    source_family_id: str = Field(min_length=1)
    available_at: UtcDateTime
    directional_score: FiniteDecimal

    @model_validator(mode="after")
    def score_is_bounded(self) -> ReplayEvidence:
        if not Decimal("-1") <= self.directional_score <= Decimal("1"):
            raise ValueError("evidence directional score must be in [-1, 1]")
        return self


class LatencyStressScenario(DomainModel):
    delay_seconds: int = Field(ge=0)
    eligible_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    independent_family_count: int = Field(ge=0)
    directional_score: FiniteDecimal


class LatencyStressReport(DomainModel):
    decision_time: UtcDateTime
    scenarios: tuple[LatencyStressScenario, ...]

    @model_validator(mode="after")
    def require_latency_ladder(self) -> LatencyStressReport:
        if tuple(item.delay_seconds for item in self.scenarios) != (5, 30, 120, 600):
            raise ValueError("latency stress requires 5s, 30s, 2m, and 10m")
        return self


def run_latency_stress(
    *, evidence: Sequence[ReplayEvidence], decision_time: datetime
) -> LatencyStressReport:
    decision = ensure_utc(decision_time)
    scenarios: list[LatencyStressScenario] = []
    for delay in (5, 30, 120, 600):
        eligible = [
            item for item in evidence if item.available_at + timedelta(seconds=delay) <= decision
        ]
        best_by_family: dict[str, ReplayEvidence] = {}
        for item in sorted(eligible, key=lambda value: (value.available_at, value.evidence_id)):
            best_by_family.setdefault(item.source_family_id, item)
        selected = tuple(best_by_family.values())
        score = (
            sum((item.directional_score for item in selected), Decimal("0"))
            / Decimal(len(selected))
            if selected
            else Decimal("0")
        )
        eligible_ids = {item.evidence_id for item in eligible}
        scenarios.append(
            LatencyStressScenario(
                delay_seconds=delay,
                eligible_evidence_ids=tuple(sorted(eligible_ids)),
                excluded_evidence_ids=tuple(
                    sorted(
                        item.evidence_id
                        for item in evidence
                        if item.evidence_id not in eligible_ids
                    )
                ),
                independent_family_count=len(selected),
                directional_score=score,
            )
        )
    return LatencyStressReport(decision_time=decision, scenarios=tuple(scenarios))


class PretrendPlaceboAudit(DomainModel):
    pre_event_mean: FiniteDecimal
    post_event_mean: FiniteDecimal
    placebo_mean: FiniteDecimal
    pretrend_detected: bool
    placebo_warning: bool
    passed: bool

    @model_validator(mode="after")
    def validate_audit_result(self) -> PretrendPlaceboAudit:
        if self.passed != (not self.pretrend_detected and not self.placebo_warning):
            raise ValueError("pretrend/placebo audit flag mismatch")
        return self


def audit_pretrend_and_placebo(
    *,
    pre_event_returns: Sequence[Decimal],
    post_event_returns: Sequence[Decimal],
    placebo_returns: Sequence[Decimal],
) -> PretrendPlaceboAudit:
    if not pre_event_returns or not post_event_returns or not placebo_returns:
        raise ValueError("pretrend/placebo audit requires all three windows")

    def mean(values: Sequence[Decimal]) -> Decimal:
        return sum(values, Decimal("0")) / Decimal(len(values))

    pre = mean(pre_event_returns)
    post = mean(post_event_returns)
    placebo = mean(placebo_returns)
    pretrend = abs(pre) >= abs(post) * Decimal("0.5") and post != 0
    placebo_warning = abs(placebo) >= abs(post) and post != 0
    return PretrendPlaceboAudit(
        pre_event_mean=pre,
        post_event_mean=post,
        placebo_mean=placebo,
        pretrend_detected=pretrend,
        placebo_warning=placebo_warning,
        passed=not pretrend and not placebo_warning,
    )


class SourceDisposition(StrEnum):
    RETAIN = "RETAIN"
    RISK_ONLY = "RISK_ONLY"
    MONITOR = "MONITOR"
    RETIRE = "RETIRE"


class SourceIncrementalMetrics(DomainModel):
    source: WorldSource
    event_incremental_value: FiniteDecimal
    risk_incremental_value: FiniteDecimal
    coverage: UnitInterval
    reliability: UnitInterval
    evaluation_windows: int = Field(gt=0)


class SourceMonitorDecision(DomainModel):
    source: WorldSource
    disposition: SourceDisposition
    reason_codes: tuple[str, ...] = Field(min_length=1)
    evaluation_windows: int = Field(gt=0)


def evaluate_source_increment(
    metrics: SourceIncrementalMetrics, *, minimum_windows: int = 3
) -> SourceMonitorDecision:
    if metrics.evaluation_windows < minimum_windows:
        return SourceMonitorDecision(
            source=metrics.source,
            disposition=SourceDisposition.MONITOR,
            reason_codes=("INSUFFICIENT_EVALUATION_WINDOWS",),
            evaluation_windows=metrics.evaluation_windows,
        )
    if metrics.event_incremental_value > 0 and metrics.reliability >= Decimal("0.6"):
        disposition = SourceDisposition.RETAIN
        reasons = ("POSITIVE_EVENT_INCREMENT",)
    elif metrics.risk_incremental_value > 0 and metrics.reliability >= Decimal("0.5"):
        disposition = SourceDisposition.RISK_ONLY
        reasons = ("NO_EVENT_INCREMENT", "POSITIVE_RISK_INCREMENT")
    elif metrics.coverage < Decimal("0.2") or metrics.reliability < Decimal("0.4"):
        disposition = SourceDisposition.RETIRE
        reasons = ("LOW_COVERAGE_OR_RELIABILITY",)
    else:
        disposition = SourceDisposition.MONITOR
        reasons = ("NO_CONFIRMED_INCREMENT",)
    return SourceMonitorDecision(
        source=metrics.source,
        disposition=disposition,
        reason_codes=reasons,
        evaluation_windows=metrics.evaluation_windows,
    )


class EventRadarRow(DomainModel):
    event_cluster_id: str
    status: EventClusterStatus
    impact_score: FiniteDecimal
    confidence: UnitInterval
    independent_family_count: int = Field(ge=0)
    evidence_ids: tuple[str, ...]
    as_of_time: UtcDateTime


class EvidenceGraphRow(DomainModel):
    event_cluster_id: str
    claim_id: str
    evidence_id: str
    relation: str
    source_family_id: str
    policy_id: str
    model_version: str
    available_at: UtcDateTime


class NarrativeMonitorRow(DomainModel):
    narrative_id: str
    topic: str
    propagation_stage: str
    independent_author_count: int = Field(ge=0)
    coordination_risk: UnitInterval
    as_of_time: UtcDateTime


class SourceMonitorRow(DomainModel):
    source: WorldSource
    runtime_state: RuntimeSourceState
    disposition: SourceDisposition
    last_success_at: UtcDateTime | None
    gap_count: int = Field(ge=0)
    reason_codes: tuple[str, ...]


class EventReplayRow(DomainModel):
    content_id: str
    as_of_time: UtcDateTime
    selected_revision: int = Field(ge=1)
    selected_engagement_snapshot_id: str | None
    deleted_as_of: bool
    excluded_future_items: int = Field(ge=0)


class WorldIntelligenceReadModels(DomainModel):
    event_radar: tuple[EventRadarRow, ...]
    evidence_graph: tuple[EvidenceGraphRow, ...]
    narrative_monitor: tuple[NarrativeMonitorRow, ...]
    source_monitor: tuple[SourceMonitorRow, ...]
    event_replay: tuple[EventReplayRow, ...]
    generated_as_of: UtcDateTime

    @model_validator(mode="after")
    def read_models_are_point_in_time(self) -> WorldIntelligenceReadModels:
        times = [item.as_of_time for item in self.event_radar]
        times.extend(item.available_at for item in self.evidence_graph)
        times.extend(item.as_of_time for item in self.narrative_monitor)
        times.extend(item.as_of_time for item in self.event_replay)
        if any(value > self.generated_as_of for value in times):
            raise ValueError("read model contains future row")
        return self


def group_replay_by_content(
    revisions: Sequence[ContentRevision],
) -> dict[str, tuple[ContentRevision, ...]]:
    grouped: dict[str, list[ContentRevision]] = defaultdict(list)
    for revision in revisions:
        grouped[revision.content_id].append(revision)
    return {
        content_id: tuple(sorted(items, key=lambda item: item.revision))
        for content_id, items in grouped.items()
    }
