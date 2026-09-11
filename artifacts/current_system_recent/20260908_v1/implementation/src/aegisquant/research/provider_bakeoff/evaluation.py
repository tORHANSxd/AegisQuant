"""Deterministic P17 scoring, news metrics, authority, and degradation gates."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from aegisquant.research.provider_bakeoff.models import (
    DegradationMode,
    DegradationSelection,
    EvidenceState,
    NewsBakeoffMetrics,
    NewsDetection,
    NewsReferenceEvent,
    ProcurementDecision,
    ProviderCandidate,
    ProviderDecisionRecord,
    SourceAuthority,
    TradingFactRecord,
    TrialMeasurement,
    TrialPlan,
)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return Decimal(numerator) / Decimal(denominator)


def evaluate_candidate(
    *,
    candidate: ProviderCandidate,
    plan: TrialPlan,
    measurement: TrialMeasurement | None,
    condition_satisfied: bool = True,
) -> ProviderDecisionRecord:
    """Approve only complete OOS evidence that clears every cost, rights, and ops gate."""
    if candidate.provider_id not in plan.provider_ids:
        raise ValueError("candidate is not part of the trial plan")
    if not condition_satisfied:
        return ProviderDecisionRecord(
            provider_id=candidate.provider_id,
            comparison_group=candidate.comparison_group,
            decision=ProcurementDecision.NOT_APPLICABLE,
            evidence_state=candidate.evidence_state,
            reason_codes=("AQ-P17-CONDITION-NOT-SATISFIED",),
        )
    if (
        measurement is None
        or candidate.evidence_state is not EvidenceState.TRIAL_COMPLETE
        or not plan.activated
    ):
        reasons = ["AQ-P17-TRIAL-NOT-COMPLETED"]
        if not plan.budget.user_budget_approved:
            reasons.append("AQ-P17-BUDGET-NOT-APPROVED")
        if not candidate.license_review_complete:
            reasons.append("AQ-P17-LICENSE-NOT-APPROVED")
        return ProviderDecisionRecord(
            provider_id=candidate.provider_id,
            comparison_group=candidate.comparison_group,
            decision=ProcurementDecision.DEFER,
            evidence_state=candidate.evidence_state,
            reason_codes=tuple(reasons),
        )
    if measurement.provider_id != candidate.provider_id:
        raise ValueError("measurement provider does not match candidate")

    criteria = plan.criteria
    failures: list[str] = []
    checks = (
        (measurement.license_approved, "AQ-P17-LICENSE-NOT-APPROVED"),
        (measurement.point_in_time_verified, "AQ-P17-PIT-NOT-VERIFIED"),
        (
            measurement.oos_observations >= criteria.min_oos_observations,
            "AQ-P17-OOS-SAMPLE-INSUFFICIENT",
        ),
        (
            measurement.official_match_rate >= criteria.min_official_match_rate,
            "AQ-P17-OFFICIAL-CROSSCHECK-FAILED",
        ),
        (
            measurement.completeness_rate >= criteria.min_completeness_rate,
            "AQ-P17-COMPLETENESS-FAILED",
        ),
        (measurement.gap_rate <= criteria.max_gap_rate, "AQ-P17-GAP-RATE-FAILED"),
        (
            measurement.p95_latency_ms <= criteria.max_p95_latency_ms,
            "AQ-P17-LATENCY-FAILED",
        ),
        (
            measurement.net_incremental_bps >= criteria.min_net_incremental_bps,
            "AQ-P17-NET-INCREMENT-FAILED",
        ),
        (
            measurement.adjusted_p_value <= criteria.max_adjusted_p_value,
            "AQ-P17-MULTIPLE-TESTING-FAILED",
        ),
        (
            measurement.operations_minutes_per_day <= criteria.max_operations_minutes_per_day,
            "AQ-P17-OPERATIONS-COST-FAILED",
        ),
        (
            measurement.total_cost_usd <= plan.budget.approved_max_cost_usd,
            "AQ-P17-BUDGET-EXCEEDED",
        ),
        (measurement.negative_result_retained, "AQ-P17-NEGATIVE-RESULT-MISSING"),
    )
    failures.extend(code for passed, code in checks if not passed)
    approved = not failures
    return ProviderDecisionRecord(
        provider_id=candidate.provider_id,
        comparison_group=candidate.comparison_group,
        decision=ProcurementDecision.APPROVE if approved else ProcurementDecision.REJECT,
        evidence_state=candidate.evidence_state,
        reason_codes=("AQ-P17-ALL-GATES-PASSED",) if approved else tuple(failures),
        net_incremental_bps=measurement.net_incremental_bps,
        selected_as_primary=approved,
    )


def enforce_primary_source_limit(decisions: tuple[ProviderDecisionRecord, ...]) -> None:
    approved_by_group: dict[str, int] = defaultdict(int)
    for decision in decisions:
        if decision.decision is ProcurementDecision.APPROVE:
            approved_by_group[decision.comparison_group] += 1
    violations = sorted(group for group, count in approved_by_group.items() if count > 1)
    if violations:
        raise ValueError("multiple primary providers in groups: " + ", ".join(violations))


def calculate_news_metrics(
    *, references: tuple[NewsReferenceEvent, ...], detections: tuple[NewsDetection, ...]
) -> NewsBakeoffMetrics:
    if not references:
        raise ValueError("news bake-off requires official reference events")
    reference_by_id = {item.event_id: item for item in references}
    if len(reference_by_id) != len(references):
        raise ValueError("official reference event IDs must be unique")
    detection_ids = [item.detection_id for item in detections]
    if len(detection_ids) != len(set(detection_ids)):
        raise ValueError("news detection IDs must be unique")

    matched = {
        item.matched_official_event_id
        for item in detections
        if item.matched_official_event_id in reference_by_id
    }
    false_alerts = sum(
        item.matched_official_event_id is None
        or item.matched_official_event_id not in reference_by_id
        for item in detections
    )
    duplicates = len(detections) - len({item.story_fingerprint for item in detections})
    lead_seconds: list[Decimal] = []
    for event_id in matched:
        earliest = min(
            item.available_time for item in detections if item.matched_official_event_id == event_id
        )
        lead_seconds.append(
            Decimal(
                str((reference_by_id[event_id].official_available_time - earliest).total_seconds())
            )
        )
    risk_events = {item.event_id for item in references if item.risk_relevant}
    risk_matches = len(risk_events & matched)
    mean_lead = (
        sum(lead_seconds, Decimal("0")) / Decimal(len(lead_seconds))
        if lead_seconds
        else Decimal("0")
    )
    return NewsBakeoffMetrics(
        reference_event_count=len(references),
        detection_count=len(detections),
        matched_event_count=len(matched),
        recall=_ratio(len(matched), len(references)),
        false_alert_rate=_ratio(false_alerts, len(detections)),
        duplicate_rate=_ratio(duplicates, len(detections)),
        mean_lead_time_seconds=mean_lead,
        risk_coverage_rate=_ratio(risk_matches, len(risk_events)),
    )


def fallback_to_free_baseline(
    *,
    baseline_record_ids: tuple[str, ...],
    candidate_record_ids: tuple[str, ...],
    candidate_approved: bool,
    provider_available: bool,
) -> DegradationSelection:
    if not baseline_record_ids:
        raise ValueError("free baseline cannot be empty")
    if len(baseline_record_ids) != len(set(baseline_record_ids)):
        raise ValueError("free baseline record IDs must be unique")
    use_candidate = candidate_approved and provider_available
    selected = baseline_record_ids + (candidate_record_ids if use_candidate else ())
    return DegradationSelection(
        mode=(
            DegradationMode.BASELINE_PLUS_APPROVED_SOURCE
            if use_candidate
            else DegradationMode.BASELINE_ONLY
        ),
        selected_record_ids=selected,
        baseline_preserved=selected[: len(baseline_record_ids)] == baseline_record_ids,
        candidate_records_used=use_candidate,
        runtime_hard_dependency=False,
    )


def require_official_trading_fact(record: TradingFactRecord) -> TradingFactRecord:
    if record.source_authority is not SourceAuthority.OFFICIAL_EXCHANGE:
        raise PermissionError("AQ-P17-THIRD-PARTY-NOT-TRADING-FACT-AUTHORITY")
    return record
