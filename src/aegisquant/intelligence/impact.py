"""Evidence-derived multi-horizon event impact forecast with abstention."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import ImpactForecastId, ModelVersionId, SourceDocumentId
from aegisquant.domain.intelligence import (
    EVENT_IMPACT_HORIZONS,
    EventCluster,
    EventImpactForecast,
    ForecastDistribution,
    ForecastHorizon,
    HorizonImpact,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.intelligence.canonical_events import (
    CanonicalEvent,
    EventDirectionalGate,
    build_event_directional_gate,
)
from aegisquant.intelligence.committee import CommitteeResult


def build_event_impact_forecast(
    *,
    cluster: EventCluster,
    committee: CommitteeResult,
    as_of_time: UtcDateTime,
    affected_exposure_ids: tuple[str, ...],
    horizon_coefficients: Mapping[ForecastHorizon, Decimal],
    market_already_moved_score: Decimal | None = None,
    canonical_event: CanonicalEvent | None = None,
    directional_gate: EventDirectionalGate | None = None,
) -> EventImpactForecast:
    if set(horizon_coefficients) != set(EVENT_IMPACT_HORIZONS):
        raise ValueError("event impact requires one fitted coefficient per horizon")
    if any(not value.is_finite() or value < 0 for value in horizon_coefficients.values()):
        raise ValueError("event impact horizon coefficients must be finite and non-negative")
    coefficients_sha256 = canonical_sha256(
        {
            horizon.value: format(horizon_coefficients[horizon].normalize(), "f")
            for horizon in EVENT_IMPACT_HORIZONS
        }
    )
    if cluster.last_updated_time > as_of_time:
        raise ValueError("event impact forecast cannot use future cluster revision")
    if (canonical_event is None) != (directional_gate is None):
        raise ValueError("AQ-IMPACT-CANONICAL-EVENT-GATE-PAIR-REQUIRED")
    event_revision_id = None
    directional_gate_id = None
    reflection_score = market_already_moved_score
    gate_allows = False
    if canonical_event is not None and directional_gate is not None:
        if canonical_event.available_at > as_of_time or directional_gate.as_of_time > as_of_time:
            raise ValueError("AQ-IMPACT-CANONICAL-EVENT-LOOKAHEAD")
        if canonical_event.source_cluster != cluster:
            raise ValueError("AQ-IMPACT-CANONICAL-EVENT-CLUSTER-MISMATCH")
        expected_gate = build_event_directional_gate(
            event=canonical_event,
            as_of_time=directional_gate.as_of_time,
        )
        if directional_gate != expected_gate:
            raise ValueError("AQ-IMPACT-DIRECTIONAL-GATE-BINDING")
        if (
            market_already_moved_score is not None
            and market_already_moved_score != directional_gate.market_reflection_score
        ):
            raise ValueError("AQ-IMPACT-LEGACY-REFLECTION-SCORE-MISMATCH")
        event_revision_id = canonical_event.revision_id
        directional_gate_id = directional_gate.gate_id
        reflection_score = directional_gate.market_reflection_score
        gate_allows = directional_gate.directional_candidate_allowed
    evidence = set(committee.arbiter.evidence_ids)
    cluster_evidence = {str(value) for value in cluster.supporting_evidence_ids}
    if not evidence.issubset(cluster_evidence):
        raise ValueError("AQ-IMPACT-EVIDENCE-NOT-IN-CLUSTER")
    reasons = set(committee.arbiter.abstain_reasons)
    if not affected_exposure_ids:
        reasons.add("NO_AFFECTED_EXPOSURE")
    if directional_gate is None:
        reasons.add("CANONICAL_EVENT_GATE_REQUIRED")
    elif not gate_allows:
        reasons.update(directional_gate.reason_codes)
    directional_allowed = gate_allows and not reasons
    if not directional_allowed:
        reasons.add("EVENT_DIRECTIONAL_PATH_DENIED")
    strength = Decimal("0")
    if directional_allowed and reflection_score is not None:
        strength = (
            committee.arbiter.directional_score
            * committee.arbiter.factual_confidence
            * committee.arbiter.impact_confidence
            * (Decimal("1") - reflection_score)
        )
    horizons: dict[ForecastHorizon, HorizonImpact] = {}
    for horizon in EVENT_IMPACT_HORIZONS:
        coefficient = horizon_coefficients[horizon]
        mean = canonical_result(strength * coefficient)
        width = canonical_result(
            max(
                abs(mean) * Decimal("1.5"),
                coefficient * (Decimal("1") - committee.arbiter.factual_confidence),
            )
        )
        horizons[horizon] = HorizonImpact(
            return_distribution=ForecastDistribution(
                mean=mean,
                std=width / Decimal("1.64485362695147"),
                q05=mean - width,
                q50=mean,
                q95=mean + width,
            ),
            volatility_delta=width,
            liquidity_delta=canonical_result(-abs(mean)),
            tail_risk_delta=width,
        )
    identity = {
        "event_cluster_id": str(cluster.event_cluster_id),
        "event_revision_id": str(event_revision_id) if event_revision_id is not None else None,
        "directional_gate_id": str(directional_gate_id)
        if directional_gate_id is not None
        else None,
        "as_of_time": as_of_time.isoformat(),
        "evidence_ids": sorted(evidence),
        "model": "evidence-impact-p08-v1",
        "horizon_coefficients_sha256": coefficients_sha256,
    }
    return EventImpactForecast(
        impact_forecast_id=ImpactForecastId(canonical_sha256(identity)),
        event_cluster_id=cluster.event_cluster_id,
        event_revision_id=event_revision_id,
        directional_gate_id=directional_gate_id,
        as_of_time=as_of_time,
        affected_exposure_ids=affected_exposure_ids,
        horizons=horizons,
        horizon_coefficients_sha256=coefficients_sha256,
        transmission_channels=("evidence_to_market",),
        market_already_moved_score=reflection_score,
        corroboration_score=cluster.credibility_score,
        source_quality_score=committee.arbiter.factual_confidence,
        novelty_score=(
            Decimal("0") if reflection_score is None else Decimal("1") - reflection_score
        ),
        manipulation_risk=cluster.manipulation_risk,
        model_disagreement=Decimal(len(committee.arbiter.conflicts)),
        evidence_ids=tuple(SourceDocumentId(value) for value in sorted(evidence)),
        model_versions=(ModelVersionId("evidence-impact-p08-v1"),),
        directional_candidate_allowed=directional_allowed,
        should_abstain=bool(reasons),
        abstain_reasons=tuple(sorted(reasons)),
    )
