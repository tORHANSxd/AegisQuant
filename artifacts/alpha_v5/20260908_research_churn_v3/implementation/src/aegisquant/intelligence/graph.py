"""Point-in-time Claim/Event evidence graph, coverage, conflicts, and state transitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Self, cast

from pydantic import Field, JsonValue, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ArtifactId, SourceIdentityId
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.domain.serialization import canonical_content_hash
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import UnitInterval


class GraphNodeType(StrEnum):
    EVIDENCE = "EVIDENCE"
    CLAIM = "CLAIM"
    EVENT = "EVENT"
    ENTITY = "ENTITY"
    SOURCE = "SOURCE"
    DOCUMENT = "DOCUMENT"
    AUTHOR = "AUTHOR"
    ACCOUNT = "ACCOUNT"
    ORGANIZATION = "ORGANIZATION"
    QUOTE = "QUOTE"
    ATTACHMENT = "ATTACHMENT"
    MEDIA_ASSET = "MEDIA_ASSET"


class GraphEdgeType(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    MENTIONS = "MENTIONS"
    CLUSTERS_IN = "CLUSTERS_IN"
    PUBLISHED_BY = "PUBLISHED_BY"
    QUOTES = "QUOTES"
    COPIES = "COPIES"
    CITES = "CITES"
    DERIVED_FROM = "DERIVED_FROM"
    REPOSTS = "REPOSTS"
    SAME_ORIGIN = "SAME_ORIGIN"
    CONTRADICTS = "CONTRADICTS"
    REVISES = "REVISES"
    DELETES = "DELETES"


class EvidenceGraphNode(DomainModel):
    node_id: str = Field(min_length=1)
    node_type: GraphNodeType
    available_at_utc: UtcDateTime
    revision_id: ArtifactId | None = None
    source_identity_id: SourceIdentityId | None = None
    independence_group: str | None = None
    content_sha256: str | None = None
    origin_fingerprint_sha256: str | None = None

    @model_validator(mode="after")
    def validate_group(self) -> Self:
        if self.independence_group is not None and not self.independence_group.strip():
            raise ValueError("AQ-TRUTH-EMPTY-INDEPENDENCE-GROUP")
        for field_name, value in (
            ("content_sha256", self.content_sha256),
            ("origin_fingerprint_sha256", self.origin_fingerprint_sha256),
        ):
            if value is not None and (
                len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{field_name} must be a lowercase SHA-256")
        return self


class EvidenceGraphEdge(DomainModel):
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    edge_type: GraphEdgeType
    available_at_utc: UtcDateTime


class EvidenceGraph(DomainModel):
    as_of_time: UtcDateTime
    nodes: tuple[EvidenceGraphNode, ...] = Field(min_length=1)
    edges: tuple[EvidenceGraphEdge, ...]
    evidence_coverage: UnitInterval
    independent_evidence_count: int = Field(ge=0)
    evidence_dependency_score: UnitInterval
    conflicting_claim_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_graph(self) -> EvidenceGraph:
        node_by_id = {item.node_id: item for item in self.nodes}
        node_ids = set(node_by_id)
        if len(node_ids) != len(self.nodes):
            raise ValueError("evidence graph node ids must be unique")
        if any(item.available_at_utc > self.as_of_time for item in self.nodes):
            raise ValueError("evidence graph contains future node")
        if any(
            edge.source_node_id not in node_ids or edge.target_node_id not in node_ids
            for edge in self.edges
        ):
            raise ValueError("evidence graph edge references unknown node")
        if any(edge.available_at_utc > self.as_of_time for edge in self.edges):
            raise ValueError("evidence graph contains future edge")
        if any(
            edge.available_at_utc < node_by_id[edge.source_node_id].available_at_utc
            or edge.available_at_utc < node_by_id[edge.target_node_id].available_at_utc
            for edge in self.edges
        ):
            raise ValueError("evidence graph edge predates one of its endpoints")
        edge_keys = {
            (
                edge.source_node_id,
                edge.target_node_id,
                edge.edge_type,
                edge.available_at_utc,
            )
            for edge in self.edges
        }
        if len(edge_keys) != len(self.edges):
            raise ValueError("evidence graph edges must be unique")
        expected = _derived_metrics(
            as_of_time=self.as_of_time,
            nodes=self.nodes,
            edges=self.edges,
        )
        if self.evidence_coverage != expected[0]:
            raise ValueError("evidence graph coverage is inconsistent")
        if self.independent_evidence_count != expected[1]:
            raise ValueError("evidence graph independent evidence count is inconsistent")
        if self.evidence_dependency_score != expected[2]:
            raise ValueError("evidence graph dependency score is inconsistent")
        if self.conflicting_claim_ids != expected[3]:
            raise ValueError("evidence graph conflicting claims are inconsistent")
        return self

    def content_sha256(self) -> str:
        payload = cast(dict[str, JsonValue], self.model_dump(mode="json"))
        for field_name in ("nodes", "edges"):
            values = payload[field_name]
            if not isinstance(values, list):
                raise TypeError(f"evidence graph {field_name} must serialize as a list")
            payload[field_name] = sorted(
                values,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            )
        return canonical_content_hash(payload)


_EVIDENCE_NODE_TYPES = frozenset(
    {
        GraphNodeType.EVIDENCE,
        GraphNodeType.SOURCE,
        GraphNodeType.DOCUMENT,
        GraphNodeType.QUOTE,
        GraphNodeType.ATTACHMENT,
        GraphNodeType.MEDIA_ASSET,
    }
)
_DEPENDENCY_ANCHOR_NODE_TYPES = _EVIDENCE_NODE_TYPES | frozenset(
    {
        GraphNodeType.AUTHOR,
        GraphNodeType.ACCOUNT,
        GraphNodeType.ORGANIZATION,
    }
)

_DEPENDENCY_EDGE_TYPES = frozenset(
    {
        GraphEdgeType.PUBLISHED_BY,
        GraphEdgeType.QUOTES,
        GraphEdgeType.COPIES,
        GraphEdgeType.CITES,
        GraphEdgeType.DERIVED_FROM,
        GraphEdgeType.REPOSTS,
        GraphEdgeType.SAME_ORIGIN,
        GraphEdgeType.REVISES,
        GraphEdgeType.DELETES,
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceIndependenceResult:
    evidence_item_count: int
    independent_evidence_count: int
    evidence_dependency_score: Decimal
    components: tuple[tuple[str, ...], ...]


class EvidenceIndependenceModel:
    """Collapse evidence that shares content, origin, ownership, or provenance."""

    version = "v5-p03-deterministic-v1"

    def evaluate(
        self,
        *,
        as_of_time: UtcDateTime,
        nodes: tuple[EvidenceGraphNode, ...],
        edges: tuple[EvidenceGraphEdge, ...],
        evidence_node_ids: frozenset[str],
    ) -> EvidenceIndependenceResult:
        node_by_id = {node.node_id: node for node in nodes}
        if len(node_by_id) != len(nodes):
            raise ValueError("AQ-TRUTH-INDEPENDENCE-DUPLICATE-NODE-ID")
        if any(node.available_at_utc > as_of_time for node in nodes):
            raise ValueError("AQ-TRUTH-INDEPENDENCE-FUTURE-NODE: future node")
        missing_ids = evidence_node_ids - node_by_id.keys()
        if missing_ids:
            raise ValueError("AQ-TRUTH-INDEPENDENCE-UNKNOWN-EVIDENCE-NODE")
        if any(
            node_by_id[node_id].node_type not in _EVIDENCE_NODE_TYPES
            for node_id in evidence_node_ids
        ):
            raise ValueError("AQ-TRUTH-INDEPENDENCE-NON-EVIDENCE-NODE")
        adjacency = {node_id: set[str]() for node_id in node_by_id}
        for edge in edges:
            if edge.source_node_id not in node_by_id or edge.target_node_id not in node_by_id:
                raise ValueError("AQ-TRUTH-INDEPENDENCE-EDGE-UNKNOWN-NODE")
            if edge.available_at_utc > as_of_time:
                raise ValueError("AQ-TRUTH-INDEPENDENCE-FUTURE-EDGE: future edge")
            if (
                edge.available_at_utc < node_by_id[edge.source_node_id].available_at_utc
                or edge.available_at_utc < node_by_id[edge.target_node_id].available_at_utc
            ):
                raise ValueError("AQ-TRUTH-INDEPENDENCE-EDGE-PREDATES-ENDPOINT")
            if edge.edge_type in _DEPENDENCY_EDGE_TYPES:
                adjacency[edge.source_node_id].add(edge.target_node_id)
                adjacency[edge.target_node_id].add(edge.source_node_id)

        for field_name in (
            "independence_group",
            "content_sha256",
            "origin_fingerprint_sha256",
        ):
            first_by_value: dict[str, str] = {}
            for node in nodes:
                allowed_types = (
                    _DEPENDENCY_ANCHOR_NODE_TYPES
                    if field_name == "independence_group"
                    else _EVIDENCE_NODE_TYPES
                )
                if node.node_type not in allowed_types:
                    continue
                value = cast(str | None, getattr(node, field_name))
                if value is None:
                    continue
                first = first_by_value.setdefault(value, node.node_id)
                adjacency[first].add(node.node_id)
                adjacency[node.node_id].add(first)

        component_by_node: dict[str, int] = {}
        component_index = 0
        for start in sorted(node_by_id):
            if start in component_by_node:
                continue
            stack = [start]
            while stack:
                node_id = stack.pop()
                if node_id in component_by_node:
                    continue
                component_by_node[node_id] = component_index
                stack.extend(adjacency[node_id])
            component_index += 1

        grouped: dict[int, list[str]] = {}
        for node_id in sorted(evidence_node_ids):
            grouped.setdefault(component_by_node[node_id], []).append(node_id)
        components = tuple(tuple(grouped[key]) for key in sorted(grouped))
        evidence_count = len(evidence_node_ids)
        independent_count = len(components)
        dependency = (
            Decimal(evidence_count - independent_count) / Decimal(evidence_count)
            if evidence_count
            else Decimal("0")
        )
        return EvidenceIndependenceResult(
            evidence_item_count=evidence_count,
            independent_evidence_count=independent_count,
            evidence_dependency_score=dependency,
            components=components,
        )


def _derived_metrics(
    *,
    as_of_time: UtcDateTime,
    nodes: tuple[EvidenceGraphNode, ...],
    edges: tuple[EvidenceGraphEdge, ...],
) -> tuple[Decimal, int, Decimal, tuple[str, ...]]:
    node_by_id = {item.node_id: item for item in nodes}
    claim_ids = {item.node_id for item in nodes if item.node_type is GraphNodeType.CLAIM}
    linked_evidence_ids = {
        edge.source_node_id
        for edge in edges
        if edge.target_node_id in claim_ids
        and edge.edge_type
        in {GraphEdgeType.SUPPORTS, GraphEdgeType.REFUTES, GraphEdgeType.CONTRADICTS}
        and node_by_id.get(edge.source_node_id) is not None
        and node_by_id[edge.source_node_id].node_type in _EVIDENCE_NODE_TYPES
    }
    supported = {
        edge.target_node_id
        for edge in edges
        if edge.edge_type is GraphEdgeType.SUPPORTS
        and node_by_id.get(edge.source_node_id) is not None
        and node_by_id[edge.source_node_id].node_type in _EVIDENCE_NODE_TYPES
    }
    refuted = {
        edge.target_node_id
        for edge in edges
        if edge.edge_type in {GraphEdgeType.REFUTES, GraphEdgeType.CONTRADICTS}
        and node_by_id.get(edge.source_node_id) is not None
        and node_by_id[edge.source_node_id].node_type in _EVIDENCE_NODE_TYPES
    }
    coverage = (
        Decimal(len(claim_ids & (supported | refuted))) / Decimal(len(claim_ids))
        if claim_ids
        else Decimal("0")
    )
    independence = EvidenceIndependenceModel().evaluate(
        as_of_time=as_of_time,
        nodes=nodes,
        edges=edges,
        evidence_node_ids=frozenset(linked_evidence_ids),
    )
    conflicts = tuple(sorted(claim_ids & supported & refuted))
    return (
        coverage,
        independence.independent_evidence_count,
        independence.evidence_dependency_score,
        conflicts,
    )


def build_evidence_graph(
    *,
    as_of_time: UtcDateTime,
    nodes: tuple[EvidenceGraphNode, ...],
    edges: tuple[EvidenceGraphEdge, ...],
) -> EvidenceGraph:
    ordered_nodes = tuple(sorted(nodes, key=lambda item: item.node_id))
    ordered_edges = tuple(
        sorted(
            edges,
            key=lambda item: (
                item.source_node_id,
                item.target_node_id,
                item.edge_type.value,
                item.available_at_utc,
            ),
        )
    )
    coverage, independent_count, dependency, conflicts = _derived_metrics(
        as_of_time=as_of_time,
        nodes=ordered_nodes,
        edges=ordered_edges,
    )
    return EvidenceGraph(
        as_of_time=as_of_time,
        nodes=ordered_nodes,
        edges=ordered_edges,
        evidence_coverage=coverage,
        independent_evidence_count=independent_count,
        evidence_dependency_score=dependency,
        conflicting_claim_ids=conflicts,
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
