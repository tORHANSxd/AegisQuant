"""Evidence-derived multi-horizon event impact forecast with abstention."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import ImpactForecastId, ModelVersionId, SourceDocumentId
from aegisquant.domain.intelligence import (
    EventCluster,
    EventImpactForecast,
    ForecastDistribution,
    ForecastHorizon,
    HorizonImpact,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.intelligence.committee import CommitteeResult

HORIZON_SCALE = {
    ForecastHorizon.FIVE_MINUTES: Decimal("0.0002"),
    ForecastHorizon.THIRTY_MINUTES: Decimal("0.0005"),
    ForecastHorizon.FOUR_HOURS: Decimal("0.001"),
    ForecastHorizon.ONE_DAY: Decimal("0.0015"),
    ForecastHorizon.SEVEN_DAYS: Decimal("0.002"),
}


def build_event_impact_forecast(
    *,
    cluster: EventCluster,
    committee: CommitteeResult,
    as_of_time: UtcDateTime,
    affected_exposure_ids: tuple[str, ...],
    market_already_moved_score: Decimal,
) -> EventImpactForecast:
    if cluster.last_updated_time > as_of_time:
        raise ValueError("event impact forecast cannot use future cluster revision")
    evidence = set(committee.arbiter.evidence_ids)
    cluster_evidence = {str(value) for value in cluster.supporting_evidence_ids}
    if not evidence.issubset(cluster_evidence):
        raise ValueError("AQ-IMPACT-EVIDENCE-NOT-IN-CLUSTER")
    strength = (
        committee.arbiter.directional_score
        * committee.arbiter.factual_confidence
        * committee.arbiter.impact_confidence
        * (Decimal("1") - market_already_moved_score)
    )
    horizons: dict[ForecastHorizon, HorizonImpact] = {}
    for horizon, scale in HORIZON_SCALE.items():
        mean = canonical_result(strength * scale)
        width = canonical_result(
            max(
                abs(mean) * Decimal("1.5"),
                scale * (Decimal("1") - committee.arbiter.factual_confidence),
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
    reasons = set(committee.arbiter.abstain_reasons)
    if not affected_exposure_ids:
        reasons.add("NO_AFFECTED_EXPOSURE")
    identity = {
        "event_cluster_id": str(cluster.event_cluster_id),
        "as_of_time": as_of_time.isoformat(),
        "evidence_ids": sorted(evidence),
        "model": "evidence-impact-p08-v1",
    }
    return EventImpactForecast(
        impact_forecast_id=ImpactForecastId(canonical_sha256(identity)),
        event_cluster_id=cluster.event_cluster_id,
        as_of_time=as_of_time,
        affected_exposure_ids=affected_exposure_ids,
        horizons=horizons,
        transmission_channels=("evidence_to_market",),
        market_already_moved_score=market_already_moved_score,
        corroboration_score=cluster.credibility_score,
        source_quality_score=committee.arbiter.factual_confidence,
        novelty_score=Decimal("1") - market_already_moved_score,
        manipulation_risk=cluster.manipulation_risk,
        model_disagreement=Decimal(len(committee.arbiter.conflicts)),
        evidence_ids=tuple(SourceDocumentId(value) for value in sorted(evidence)),
        model_versions=(ModelVersionId("evidence-impact-p08-v1"),),
        should_abstain=bool(reasons),
        abstain_reasons=tuple(sorted(reasons)),
    )
