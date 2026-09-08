"""Generate or verify deterministic V5-P03 retrieval and independence evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    SourceDocumentId,
    SourceId,
    SourceIdentityId,
    SourcePolicyId,
)
from aegisquant.domain.intelligence import Polarity, RightsState
from aegisquant.domain.truth import (
    EvidenceQuery,
    EvidenceQueryKind,
    EvidenceRetrievalHit,
    EvidenceSearchPlan,
)
from aegisquant.intelligence.graph import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceIndependenceModel,
    GraphEdgeType,
    GraphNodeType,
    build_evidence_graph,
)
from aegisquant.intelligence.truth import select_evidence_as_of
from aegisquant.truth.contracts import (
    IdentityFactor,
    OfficialIdentityAssessment,
    OfficialIdentityState,
)

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "reports/v5/P03/EVIDENCE_RETRIEVAL_INDEPENDENCE.json"
BASE_TIME: Final = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
DECISION_TIME: Final = BASE_TIME + timedelta(minutes=10)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _query(text: str) -> EvidenceQuery:
    return EvidenceQuery(text=text, language="en", end_time=DECISION_TIME)


def _plan() -> EvidenceSearchPlan:
    return EvidenceSearchPlan(
        search_plan_id=ArtifactId("v5-p03-search-plan:claim-rumor"),
        claim_id=ClaimId("claim-rumor"),
        generated_at=BASE_TIME,
        available_at=BASE_TIME,
        decision_time=DECISION_TIME,
        support_queries=(_query("issuer confirms acquisition"),),
        contradiction_queries=(_query("issuer denies acquisition"),),
        primary_source_queries=(_query("site:issuer.example acquisition filing"),),
        official_denial_queries=(_query("site:issuer.example acquisition denied"),),
        revision_queries=(_query("acquisition correction retraction"),),
        timeline_queries=(_query("acquisition announcement timeline"),),
    )


def _hit(
    plan: EvidenceSearchPlan,
    evidence_id: str,
    document_id: str,
    *,
    query_kind: EvidenceQueryKind = EvidenceQueryKind.SUPPORT,
    revision_number: int = 1,
    previous_revision_id: ArtifactId | None = None,
    minute: int = 1,
    deleted: bool = False,
    rights_state: RightsState = RightsState.ALLOWED,
    official: bool = False,
    polarity: Polarity = Polarity.AFFIRM,
) -> EvidenceRetrievalHit:
    query = {
        EvidenceQueryKind.SUPPORT: plan.support_queries[0],
        EvidenceQueryKind.CONTRADICTION: plan.contradiction_queries[0],
        EvidenceQueryKind.PRIMARY_SOURCE: plan.primary_source_queries[0],
        EvidenceQueryKind.OFFICIAL_DENIAL: plan.official_denial_queries[0],
        EvidenceQueryKind.REVISION: plan.revision_queries[0],
        EvidenceQueryKind.TIMELINE: plan.timeline_queries[0],
    }[query_kind]
    observed_at = BASE_TIME + timedelta(minutes=minute)
    return EvidenceRetrievalHit(
        evidence_id=ArtifactId(evidence_id),
        search_plan_id=plan.search_plan_id,
        claim_id=plan.claim_id,
        query_kind=query_kind,
        query_fingerprint_sha256=query.content_sha256(),
        source_document_id=SourceDocumentId(document_id),
        source_identity_id=SourceIdentityId(f"source:{document_id}"),
        source_policy_id=SourcePolicyId("policy:public-evidence"),
        revision_id=ArtifactId(f"revision:{document_id}:{revision_number}"),
        revision_number=revision_number,
        previous_revision_id=previous_revision_id,
        canonical_url=f"https://evidence.example/{document_id}/{revision_number}",
        content_sha256=_digest(f"{document_id}:{revision_number}"),
        polarity=polarity,
        published_time=BASE_TIME,
        observed_time=observed_at,
        available_at=observed_at,
        retrieved_at=observed_at,
        deleted_time=observed_at if deleted else None,
        rights_state=rights_state,
        is_official_source=official,
        official_identity_verified=official,
        official_identity_assessment_id=(
            ArtifactId(f"identity-assessment:{document_id}") if official else None
        ),
        lineage_node_ids=(f"document:{document_id}",),
    )


def build_payload() -> dict[str, object]:
    plan = _plan()
    first = _hit(plan, "hit:primary:1", "primary")
    second = _hit(
        plan,
        "hit:primary:2",
        "primary",
        revision_number=2,
        previous_revision_id=first.revision_id,
        minute=5,
    )
    official_denial = _hit(
        plan,
        "hit:official-denial",
        "official-denial",
        query_kind=EvidenceQueryKind.OFFICIAL_DENIAL,
        minute=6,
        official=True,
        polarity=Polarity.NEGATE,
    )
    future = _hit(plan, "hit:future", "future", minute=11)
    deleted = _hit(plan, "hit:deleted", "deleted", minute=7, deleted=True)
    prohibited = _hit(
        plan,
        "hit:prohibited",
        "prohibited",
        minute=8,
        rights_state=RightsState.PROHIBITED,
    )
    unknown_rights = _hit(
        plan,
        "hit:unknown-rights",
        "unknown-rights",
        minute=9,
        rights_state=RightsState.UNKNOWN,
    )
    denial_assessment = OfficialIdentityAssessment(
        assessment_id=ArtifactId("identity-assessment:official-denial"),
        source_id=SourceId("issuer"),
        source_identity_id=official_denial.source_identity_id,
        registry_entry_id=ArtifactId("registry-entry:issuer:v1"),
        state=OfficialIdentityState.AUTHENTIC,
        matched_factors=(IdentityFactor.API_ENDPOINT,),
        reason_codes=("OFFICIAL_ENDPOINT_MATCH",),
        observed_at=BASE_TIME,
        available_at=BASE_TIME,
    )
    selected = select_evidence_as_of(
        plan=plan,
        hits=(future, prohibited, unknown_rights, first, deleted, official_denial, second),
        official_identity_assessments=(denial_assessment,),
    )

    articles = tuple(
        EvidenceGraphNode(
            node_id=f"article-{index}",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=DECISION_TIME,
            content_sha256=_digest(f"machine-rewrite-{index}"),
        )
        for index in range(10)
    )
    claim = EvidenceGraphNode(
        node_id="claim-rumor",
        node_type=GraphNodeType.CLAIM,
        available_at_utc=DECISION_TIME,
    )
    rumor_origin = EvidenceGraphNode(
        node_id="rumor-origin",
        node_type=GraphNodeType.DOCUMENT,
        available_at_utc=DECISION_TIME,
    )
    assertion_edges = tuple(
        EvidenceGraphEdge(
            source_node_id=article.node_id,
            target_node_id=claim.node_id,
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=DECISION_TIME,
        )
        for article in articles
    )
    lineage_edges = tuple(
        EvidenceGraphEdge(
            source_node_id=article.node_id,
            target_node_id=rumor_origin.node_id,
            edge_type=GraphEdgeType.DERIVED_FROM,
            available_at_utc=DECISION_TIME,
        )
        for article in articles
    )
    graph = build_evidence_graph(
        as_of_time=DECISION_TIME,
        nodes=(*articles, rumor_origin, claim),
        edges=(*assertion_edges, *lineage_edges),
    )
    independence = EvidenceIndependenceModel().evaluate(
        as_of_time=DECISION_TIME,
        nodes=graph.nodes,
        edges=graph.edges,
        evidence_node_ids=frozenset(article.node_id for article in articles),
    )
    selected_ids = {str(hit.evidence_id) for hit in selected}
    required_nodes = {
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
    }
    required_edges = {
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
    }
    checks = {
        "six_query_lanes_are_nonempty": all(plan.query_hashes(kind) for kind in EvidenceQueryKind),
        "support_and_contradiction_queries_are_distinct": (
            plan.query_hashes(EvidenceQueryKind.SUPPORT).isdisjoint(
                plan.query_hashes(EvidenceQueryKind.CONTRADICTION)
            )
        ),
        "agent_vote_probability_is_forbidden": (
            plan.probability_aggregation == "CALIBRATED_MODEL_NOT_AGENT_VOTE"
        ),
        "latest_visible_revision_is_selected": (
            str(second.revision_id) in {str(hit.revision_id) for hit in selected}
            and str(first.revision_id) not in {str(hit.revision_id) for hit in selected}
        ),
        "future_evidence_is_excluded": str(future.evidence_id) not in selected_ids,
        "deleted_and_nonusable_rights_evidence_are_excluded": (
            str(deleted.evidence_id) not in selected_ids
            and str(prohibited.evidence_id) not in selected_ids
            and str(unknown_rights.evidence_id) not in selected_ids
        ),
        "official_denial_is_identity_bound": (
            official_denial.official_identity_verified
            and official_denial.polarity is Polarity.NEGATE
            and official_denial.official_identity_assessment_id == denial_assessment.assessment_id
            and str(official_denial.evidence_id) in selected_ids
        ),
        "required_provenance_vocabulary_is_present": (
            required_nodes <= {item.value for item in GraphNodeType}
            and required_edges <= {item.value for item in GraphEdgeType}
        ),
        "actual_provenance_edges_drive_the_fixture": (
            sum(edge.edge_type is GraphEdgeType.DERIVED_FROM for edge in graph.edges) == 10
        ),
        "ten_articles_are_observed": independence.evidence_item_count == 10,
        "one_rumor_is_one_independent_component": (
            graph.independent_evidence_count == independence.independent_evidence_count == 1
        ),
        "dependency_score_is_nine_tenths": (
            str(graph.evidence_dependency_score)
            == str(independence.evidence_dependency_score)
            == "0.9"
        ),
        "high_dependency_does_not_become_multi_source_confirmation": (
            independence.evidence_item_count == 10 and independence.independent_evidence_count == 1
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"V5-P03 acceptance check failed: {checks}")

    retrieval_test = "tests/v5_p03/test_evidence_retrieval.py::"
    independence_test = "tests/v5_p03/test_independence_graph.py::"
    acceptance_traceability = {
        "six_query_lanes_are_nonempty": (
            retrieval_test + "test_search_plan_requires_six_bounded_non_vote_query_lanes"
        ),
        "support_and_contradiction_queries_are_distinct": (
            retrieval_test + "test_search_plan_requires_six_bounded_non_vote_query_lanes"
        ),
        "agent_vote_probability_is_forbidden": (
            retrieval_test + "test_search_plan_requires_six_bounded_non_vote_query_lanes"
        ),
        "latest_visible_revision_is_selected": (
            retrieval_test
            + "test_selection_uses_latest_visible_revision_and_filters_future_deleted_and_prohibited"
        ),
        "future_evidence_is_excluded": (
            retrieval_test
            + "test_selection_uses_latest_visible_revision_and_filters_future_deleted_and_prohibited"
        ),
        "deleted_and_nonusable_rights_evidence_are_excluded": (
            retrieval_test
            + "test_selection_uses_latest_visible_revision_and_filters_future_deleted_and_prohibited"
        ),
        "official_denial_is_identity_bound": (
            retrieval_test + "test_official_denial_requires_verified_official_identity_and_negation"
        ),
        "required_provenance_vocabulary_is_present": (
            independence_test + "test_required_provenance_vocabulary_is_present"
        ),
        "actual_provenance_edges_drive_the_fixture": (
            independence_test
            + "test_ten_machine_rewrites_from_one_rumor_count_as_one_independent_source"
        ),
        "ten_articles_are_observed": (
            independence_test
            + "test_ten_machine_rewrites_from_one_rumor_count_as_one_independent_source"
        ),
        "one_rumor_is_one_independent_component": (
            independence_test
            + "test_ten_machine_rewrites_from_one_rumor_count_as_one_independent_source"
        ),
        "dependency_score_is_nine_tenths": (
            independence_test
            + "test_ten_machine_rewrites_from_one_rumor_count_as_one_independent_source"
        ),
        "high_dependency_does_not_become_multi_source_confirmation": (
            independence_test
            + "test_ten_machine_rewrites_from_one_rumor_count_as_one_independent_source"
        ),
    }
    if set(acceptance_traceability) != set(checks):
        raise RuntimeError("V5-P03 acceptance traceability is incomplete")

    return {
        "schema_version": "v5-p03-evidence-retrieval-independence-v1",
        "phase": "V5-P03",
        "generated_from_fixed_clock": BASE_TIME.isoformat(),
        "decision_time": DECISION_TIME.isoformat(),
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "calibrated_truth_model_present": False,
        "live_trading_locked": True,
        "search_plan": {
            "query_lane_count": len(EvidenceQueryKind),
            "query_count_by_lane": {
                kind.value: len(plan.query_hashes(kind)) for kind in EvidenceQueryKind
            },
            "probability_aggregation": plan.probability_aggregation,
        },
        "pit_retrieval": {
            "input_hit_count": 7,
            "selected_hit_ids": sorted(selected_ids),
            "selected_revision_ids": sorted(str(hit.revision_id) for hit in selected),
            "future_hit_excluded": str(future.evidence_id) not in selected_ids,
            "deleted_hit_excluded": str(deleted.evidence_id) not in selected_ids,
            "prohibited_hit_excluded": str(prohibited.evidence_id) not in selected_ids,
            "unknown_rights_hit_excluded": str(unknown_rights.evidence_id) not in selected_ids,
        },
        "independence": {
            "model_version": EvidenceIndependenceModel.version,
            "article_count": independence.evidence_item_count,
            "independent_evidence_count": independence.independent_evidence_count,
            "evidence_dependency_score": str(independence.evidence_dependency_score),
            "component_count": len(independence.components),
            "component_members": [list(component) for component in independence.components],
            "graph_sha256": graph.content_sha256(),
        },
        "checks": checks,
        "acceptance_traceability": acceptance_traceability,
        "limitations": [
            "Evidence is deterministic DEVELOPMENT data, not a real-world retrieval benchmark.",
            "Origin fingerprints and provenance edges must be produced by governed upstream collectors.",
            "No semantic similarity model or calibrated truth probability is implemented in P03.",
            "No causal effect, forecast accuracy, backtest, or trading Alpha is claimed.",
        ],
        "result": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"V5-P03 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P03 retrieval and independence evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P03 retrieval and independence evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
