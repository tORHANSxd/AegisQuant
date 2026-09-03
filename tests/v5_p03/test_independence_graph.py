"""Evidence dependency detection must defeat synthetic multi-source confirmation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aegisquant.intelligence.graph import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceIndependenceModel,
    GraphEdgeType,
    GraphNodeType,
    build_evidence_graph,
)

NOW = datetime(2026, 9, 3, 8, 30, tzinfo=UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_required_provenance_vocabulary_is_present() -> None:
    assert {
        "CLAIM",
        "SOURCE",
        "DOCUMENT",
        "AUTHOR",
        "ACCOUNT",
        "ORGANIZATION",
        "QUOTE",
        "ATTACHMENT",
        "MEDIA_ASSET",
        "EVENT",
    } <= {item.value for item in GraphNodeType}
    assert {
        "PUBLISHED_BY",
        "QUOTES",
        "COPIES",
        "CITES",
        "DERIVED_FROM",
        "REPOSTS",
        "SAME_ORIGIN",
        "CONTRADICTS",
        "SUPPORTS",
        "REVISES",
        "DELETES",
    } <= {item.value for item in GraphEdgeType}


def test_ten_machine_rewrites_from_one_rumor_count_as_one_independent_source() -> None:
    documents = tuple(
        EvidenceGraphNode(
            node_id=f"article-{index}",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
            content_sha256=digest(f"rewritten-article-{index}"),
        )
        for index in range(10)
    )
    claim = EvidenceGraphNode(
        node_id="claim-rumor",
        node_type=GraphNodeType.CLAIM,
        available_at_utc=NOW,
    )
    rumor_origin = EvidenceGraphNode(
        node_id="rumor-origin",
        node_type=GraphNodeType.DOCUMENT,
        available_at_utc=NOW,
    )
    assertion_edges = tuple(
        EvidenceGraphEdge(
            source_node_id=document.node_id,
            target_node_id=claim.node_id,
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=NOW,
        )
        for document in documents
    )
    lineage_edges = tuple(
        EvidenceGraphEdge(
            source_node_id=document.node_id,
            target_node_id=rumor_origin.node_id,
            edge_type=GraphEdgeType.DERIVED_FROM,
            available_at_utc=NOW,
        )
        for document in documents
    )

    graph = build_evidence_graph(
        as_of_time=NOW,
        nodes=(*documents, rumor_origin, claim),
        edges=(*assertion_edges, *lineage_edges),
    )
    result = EvidenceIndependenceModel().evaluate(
        as_of_time=NOW,
        nodes=graph.nodes,
        edges=graph.edges,
        evidence_node_ids=frozenset(document.node_id for document in documents),
    )

    assert result.evidence_item_count == 10
    assert graph.independent_evidence_count == result.independent_evidence_count == 1
    assert graph.evidence_dependency_score == result.evidence_dependency_score == Decimal("0.9")
    assert result.components == (tuple(f"article-{index}" for index in range(10)),)


def test_content_and_origin_fingerprints_detect_unlabelled_dependencies() -> None:
    shared_content = digest("syndicated-copy")
    shared_origin = digest("shared-upstream")
    documents = (
        EvidenceGraphNode(
            node_id="content-a",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
            content_sha256=shared_content,
        ),
        EvidenceGraphNode(
            node_id="content-b",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
            content_sha256=shared_content,
        ),
        EvidenceGraphNode(
            node_id="origin-a",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
            content_sha256=digest("origin-a-rewrite"),
            origin_fingerprint_sha256=shared_origin,
        ),
        EvidenceGraphNode(
            node_id="origin-b",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
            content_sha256=digest("origin-b-rewrite"),
            origin_fingerprint_sha256=shared_origin,
        ),
        EvidenceGraphNode(
            node_id="claim-fingerprints",
            node_type=GraphNodeType.CLAIM,
            available_at_utc=NOW,
        ),
    )
    edges = tuple(
        EvidenceGraphEdge(
            source_node_id=document.node_id,
            target_node_id="claim-fingerprints",
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=NOW,
        )
        for document in documents[:-1]
    )
    graph = build_evidence_graph(as_of_time=NOW, nodes=documents, edges=edges)
    assert graph.independent_evidence_count == 2
    assert graph.evidence_dependency_score == Decimal("0.5")


def test_shared_owner_and_anonymous_quote_form_dependency_components() -> None:
    nodes = (
        *(
            EvidenceGraphNode(
                node_id=f"owner-article-{index}",
                node_type=GraphNodeType.DOCUMENT,
                available_at_utc=NOW,
            )
            for index in range(2)
        ),
        *(
            EvidenceGraphNode(
                node_id=f"quote-article-{index}",
                node_type=GraphNodeType.DOCUMENT,
                available_at_utc=NOW,
            )
            for index in range(2)
        ),
        EvidenceGraphNode(
            node_id="media-brand-a",
            node_type=GraphNodeType.SOURCE,
            available_at_utc=NOW,
            independence_group="media-holding-company",
        ),
        EvidenceGraphNode(
            node_id="media-brand-b",
            node_type=GraphNodeType.SOURCE,
            available_at_utc=NOW,
            independence_group="media-holding-company",
        ),
        EvidenceGraphNode(
            node_id="anonymous-source",
            node_type=GraphNodeType.QUOTE,
            available_at_utc=NOW,
        ),
        EvidenceGraphNode(
            node_id="claim",
            node_type=GraphNodeType.CLAIM,
            available_at_utc=NOW,
        ),
    )
    assertion_edges = tuple(
        EvidenceGraphEdge(
            source_node_id=f"{family}-article-{index}",
            target_node_id="claim",
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=NOW,
        )
        for family in ("owner", "quote")
        for index in range(2)
    )
    dependency_edges = (
        *(
            EvidenceGraphEdge(
                source_node_id=f"owner-article-{index}",
                target_node_id=f"media-brand-{'a' if index == 0 else 'b'}",
                edge_type=GraphEdgeType.PUBLISHED_BY,
                available_at_utc=NOW,
            )
            for index in range(2)
        ),
        *(
            EvidenceGraphEdge(
                source_node_id=f"quote-article-{index}",
                target_node_id="anonymous-source",
                edge_type=GraphEdgeType.QUOTES,
                available_at_utc=NOW,
            )
            for index in range(2)
        ),
    )
    graph = build_evidence_graph(
        as_of_time=NOW,
        nodes=nodes,
        edges=(*assertion_edges, *dependency_edges),
    )
    assert graph.independent_evidence_count == 2
    assert graph.evidence_dependency_score == Decimal("0.5")


def test_unknown_unrelated_evidence_is_independent_and_orphans_do_not_count() -> None:
    nodes = (
        EvidenceGraphNode(
            node_id="document-a",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
        ),
        EvidenceGraphNode(
            node_id="document-b",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
        ),
        EvidenceGraphNode(
            node_id="orphan",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=NOW,
            independence_group="must-not-count",
        ),
        EvidenceGraphNode(
            node_id="claim",
            node_type=GraphNodeType.CLAIM,
            available_at_utc=NOW,
        ),
    )
    edges = tuple(
        EvidenceGraphEdge(
            source_node_id=document_id,
            target_node_id="claim",
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=NOW,
        )
        for document_id in ("document-a", "document-b")
    )
    graph = build_evidence_graph(as_of_time=NOW, nodes=nodes, edges=edges)
    assert graph.independent_evidence_count == 2
    assert graph.evidence_dependency_score == Decimal("0")


def test_independence_model_rejects_unknown_non_evidence_and_future_inputs() -> None:
    document = EvidenceGraphNode(
        node_id="document",
        node_type=GraphNodeType.DOCUMENT,
        available_at_utc=NOW,
    )
    claim = EvidenceGraphNode(
        node_id="claim",
        node_type=GraphNodeType.CLAIM,
        available_at_utc=NOW,
    )
    model = EvidenceIndependenceModel()

    with pytest.raises(ValueError, match="UNKNOWN-EVIDENCE-NODE"):
        model.evaluate(
            as_of_time=NOW,
            nodes=(document,),
            edges=(),
            evidence_node_ids=frozenset({"missing"}),
        )
    with pytest.raises(ValueError, match="NON-EVIDENCE-NODE"):
        model.evaluate(
            as_of_time=NOW,
            nodes=(claim,),
            edges=(),
            evidence_node_ids=frozenset({"claim"}),
        )
    with pytest.raises(ValueError, match="FUTURE-NODE"):
        model.evaluate(
            as_of_time=NOW,
            nodes=(document.model_copy(update={"available_at_utc": NOW.replace(day=4)}),),
            edges=(),
            evidence_node_ids=frozenset({"document"}),
        )
