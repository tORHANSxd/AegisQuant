from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.domain.identifiers import (
    ClaimId,
    EventClusterId,
    SourceDocumentId,
)
from aegisquant.domain.intelligence import EventCluster, EventClusterStatus, ForecastHorizon
from aegisquant.intelligence.committee import arbitrate
from aegisquant.intelligence.graph import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    GraphEdgeType,
    GraphNodeType,
    build_evidence_graph,
    transition_event_state,
)
from aegisquant.intelligence.impact import build_event_impact_forecast
from tests.p08_helpers import NOW, fitted_horizon_coefficients
from tests.p08_intelligence_helpers import committee_findings


def test_graph_reports_coverage_conflict_and_rejects_future_nodes() -> None:
    nodes = (
        EvidenceGraphNode(
            node_id="evidence-1",
            node_type=GraphNodeType.EVIDENCE,
            available_at_utc=NOW,
            independence_group="primary",
        ),
        EvidenceGraphNode(
            node_id="evidence-2",
            node_type=GraphNodeType.EVIDENCE,
            available_at_utc=NOW,
            independence_group="independent-wire",
        ),
        EvidenceGraphNode(
            node_id="irrelevant-evidence",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
            independence_group="must-not-inflate-count",
        ),
        EvidenceGraphNode(node_id="claim-1", node_type=GraphNodeType.CLAIM, available_at_utc=NOW),
    )
    edges = (
        EvidenceGraphEdge(
            source_node_id="evidence-1",
            target_node_id="claim-1",
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=NOW,
        ),
        EvidenceGraphEdge(
            source_node_id="evidence-2",
            target_node_id="claim-1",
            edge_type=GraphEdgeType.REFUTES,
            available_at_utc=NOW,
        ),
    )
    graph = build_evidence_graph(as_of_time=NOW, nodes=nodes, edges=edges)
    assert graph.evidence_coverage == 1
    assert graph.independent_evidence_count == 2
    assert graph.evidence_dependency_score == 0
    assert graph.conflicting_claim_ids == ("claim-1",)
    assert graph.content_sha256() == graph.model_copy().content_sha256()
    reordered = build_evidence_graph(
        as_of_time=NOW,
        nodes=tuple(reversed(nodes)),
        edges=tuple(reversed(edges)),
    )
    assert reordered == graph
    assert reordered.content_sha256() == graph.content_sha256()
    with pytest.raises(ValueError, match="future"):
        build_evidence_graph(
            as_of_time=NOW,
            nodes=(
                EvidenceGraphNode(
                    node_id="future",
                    node_type=GraphNodeType.EVIDENCE,
                    available_at_utc=NOW + timedelta(seconds=1),
                ),
            ),
            edges=(),
        )


def test_event_state_and_multihorizon_impact_are_evidence_bound() -> None:
    assert (
        transition_event_state(
            current=EventClusterStatus.EMERGING,
            independent_sources=2,
            official_confirmation=False,
            official_denial=False,
            resolved=False,
        )
        is EventClusterStatus.CORROBORATED
    )
    cluster = EventCluster(
        event_cluster_id=EventClusterId("event-p08-1"),
        event_type="MACRO_RELEASE",
        status=EventClusterStatus.CONFIRMED,
        entity_ids=("asset:BTC",),
        first_observed_time=NOW,
        last_updated_time=NOW,
        claim_ids=(ClaimId("claim-source"),),
        supporting_evidence_ids=(
            SourceDocumentId("evidence-1"),
            SourceDocumentId("evidence-2"),
        ),
        contradicting_evidence_ids=(),
        independent_source_count=2,
        official_confirmation_ids=(SourceDocumentId("evidence-1"),),
        credibility_score=Decimal("0.8"),
        manipulation_risk=Decimal("0.1"),
        uncertainty=Decimal("0.2"),
    )
    committee = arbitrate(
        findings=committee_findings(),
        allowed_evidence_ids=frozenset({"evidence-1", "evidence-2"}),
    )
    forecast = build_event_impact_forecast(
        horizon_coefficients=fitted_horizon_coefficients(),
        cluster=cluster,
        committee=committee,
        as_of_time=NOW,
        affected_exposure_ids=("asset:BTC",),
        market_already_moved_score=Decimal("0.2"),
    )
    assert set(forecast.horizons) == {
        ForecastHorizon.FIVE_MINUTES,
        ForecastHorizon.THIRTY_MINUTES,
        ForecastHorizon.FOUR_HOURS,
        ForecastHorizon.ONE_DAY,
        ForecastHorizon.SEVEN_DAYS,
    }
    assert {str(value) for value in forecast.evidence_ids} == {"evidence-1", "evidence-2"}

    changed_coefficients = fitted_horizon_coefficients()
    changed_coefficients[ForecastHorizon.FOUR_HOURS] = Decimal("0.004")
    changed = build_event_impact_forecast(
        horizon_coefficients=changed_coefficients,
        cluster=cluster,
        committee=committee,
        as_of_time=NOW,
        affected_exposure_ids=("asset:BTC",),
        market_already_moved_score=Decimal("0.2"),
    )
    assert changed.horizon_coefficients_sha256 != forecast.horizon_coefficients_sha256
    assert changed.impact_forecast_id != forecast.impact_forecast_id

    incomplete_coefficients = fitted_horizon_coefficients()
    incomplete_coefficients.pop(ForecastHorizon.FOUR_HOURS)
    with pytest.raises(ValueError, match="one fitted coefficient per horizon"):
        build_event_impact_forecast(
            horizon_coefficients=incomplete_coefficients,
            cluster=cluster,
            committee=committee,
            as_of_time=NOW,
            affected_exposure_ids=("asset:BTC",),
        )
