"""Point-in-time Claim/Event evidence graph, coverage, conflicts, and state transitions."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import UnitInterval


class GraphNodeType(StrEnum):
    EVIDENCE = "EVIDENCE"
    CLAIM = "CLAIM"
    EVENT = "EVENT"
    ENTITY = "ENTITY"


class GraphEdgeType(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    MENTIONS = "MENTIONS"
    CLUSTERS_IN = "CLUSTERS_IN"


class EvidenceGraphNode(DomainModel):
    node_id: str
    node_type: GraphNodeType
    available_at_utc: UtcDateTime


class EvidenceGraphEdge(DomainModel):
    source_node_id: str
    target_node_id: str
    edge_type: GraphEdgeType


class EvidenceGraph(DomainModel):
    as_of_time: UtcDateTime
    nodes: tuple[EvidenceGraphNode, ...] = Field(min_length=1)
    edges: tuple[EvidenceGraphEdge, ...]
    evidence_coverage: UnitInterval
    conflicting_claim_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_graph(self) -> EvidenceGraph:
        node_ids = {item.node_id for item in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("evidence graph node ids must be unique")
        if any(item.available_at_utc > self.as_of_time for item in self.nodes):
            raise ValueError("evidence graph contains future node")
        if any(
            edge.source_node_id not in node_ids or edge.target_node_id not in node_ids
            for edge in self.edges
        ):
            raise ValueError("evidence graph edge references unknown node")
        return self


def build_evidence_graph(
    *,
    as_of_time: UtcDateTime,
    nodes: tuple[EvidenceGraphNode, ...],
    edges: tuple[EvidenceGraphEdge, ...],
) -> EvidenceGraph:
    node_by_id = {item.node_id: item for item in nodes}
    claim_ids = {item.node_id for item in nodes if item.node_type is GraphNodeType.CLAIM}
    supported = {
        edge.target_node_id
        for edge in edges
        if edge.edge_type is GraphEdgeType.SUPPORTS
        and node_by_id.get(edge.source_node_id) is not None
        and node_by_id[edge.source_node_id].node_type is GraphNodeType.EVIDENCE
    }
    refuted = {
        edge.target_node_id
        for edge in edges
        if edge.edge_type is GraphEdgeType.REFUTES
        and node_by_id.get(edge.source_node_id) is not None
        and node_by_id[edge.source_node_id].node_type is GraphNodeType.EVIDENCE
    }
    coverage = (
        Decimal(len(claim_ids & (supported | refuted))) / Decimal(len(claim_ids))
        if claim_ids
        else Decimal("0")
    )
    return EvidenceGraph(
        as_of_time=as_of_time,
        nodes=nodes,
        edges=edges,
        evidence_coverage=coverage,
        conflicting_claim_ids=tuple(sorted(claim_ids & supported & refuted)),
    )


_STATUS_ORDER = {
    EventClusterStatus.RUMOR: 0,
    EventClusterStatus.EMERGING: 1,
    EventClusterStatus.CORROBORATED: 2,
    EventClusterStatus.CONFIRMED: 3,
    EventClusterStatus.DENIED: 4,
    EventClusterStatus.RESOLVED: 4,
}


def transition_event_state(
    *,
    current: EventClusterStatus,
    independent_sources: int,
    official_confirmation: bool,
    official_denial: bool,
    resolved: bool,
) -> EventClusterStatus:
    if independent_sources < 0:
        raise ValueError("independent source count cannot be negative")
    if official_confirmation and official_denial:
        return current
    if resolved:
        proposed = EventClusterStatus.RESOLVED
    elif official_denial:
        proposed = EventClusterStatus.DENIED
    elif official_confirmation:
        proposed = EventClusterStatus.CONFIRMED
    elif independent_sources >= 2:
        proposed = EventClusterStatus.CORROBORATED
    elif independent_sources == 1:
        proposed = EventClusterStatus.EMERGING
    else:
        proposed = EventClusterStatus.RUMOR
    return proposed if _STATUS_ORDER[proposed] >= _STATUS_ORDER[current] else current
