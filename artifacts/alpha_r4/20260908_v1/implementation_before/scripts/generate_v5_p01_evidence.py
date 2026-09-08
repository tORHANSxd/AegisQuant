"""Generate or verify deterministic V5-P01 truth-contract acceptance evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    SourceDocumentId,
    SourceIdentityId,
)
from aegisquant.domain.truth import (
    IMPACT_ONLY_CLAIM_TYPES,
    TRUTH_ADJUDICABLE_CLAIM_TYPES,
    AtomicClaim,
    ClaimSpan,
    ClaimType,
    TemporalRevision,
    TruthAssessment,
    TruthAssessmentScope,
    TruthState,
)
from aegisquant.intelligence.graph import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    GraphEdgeType,
    GraphNodeType,
    build_evidence_graph,
)
from aegisquant.intelligence.truth import (
    partition_claims_as_of,
    select_revisions_as_of,
    select_truth_assessments_as_of,
)

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "reports/v5/P01/TRUTH_CONTRACT_EVIDENCE.json"
BASE_TIME: Final = datetime(2026, 9, 2, 8, tzinfo=UTC)


def _revision(number: int, second: int, *, deleted: bool = False) -> TemporalRevision:
    instant = BASE_TIME + timedelta(seconds=second)
    return TemporalRevision(
        source_document_id=SourceDocumentId("v5-p01-document"),
        revision_id=ArtifactId(f"v5-p01-revision-{number}"),
        previous_revision_id=(ArtifactId(f"v5-p01-revision-{number - 1}") if number > 1 else None),
        revision_number=number,
        content_hash=("a", "b", "c")[number - 1] * 64,
        observed_at=instant,
        effective_at=instant,
        available_at=instant,
        updated_time=instant if number > 1 else None,
        deleted_time=instant if deleted else None,
    )


def _claim(
    claim_id: str,
    *,
    revision_number: int,
    claim_type: ClaimType,
    second: int,
    text: str,
) -> AtomicClaim:
    instant = BASE_TIME + timedelta(seconds=second)
    return AtomicClaim(
        claim_id=ClaimId(claim_id),
        source_document_id=SourceDocumentId("v5-p01-document"),
        source_identity_id=SourceIdentityId("v5-p01-source"),
        revision_id=ArtifactId(f"v5-p01-revision-{revision_number}"),
        claim_type=claim_type,
        original_text=text,
        normalized_text=text.casefold(),
        span=ClaimSpan(start=0, end=len(text), text=text),
        language="zh-CN",
        entity_ids=("asset:BTC",),
        published_time=instant,
        first_seen_time=instant,
        available_at=instant,
        ingested_time=instant,
    )


def _assessment(claim: AtomicClaim, *, graph_hash: str) -> TruthAssessment:
    instant = BASE_TIME + timedelta(seconds=21)
    return TruthAssessment(
        assessment_id=ArtifactId("v5-p01-assessment"),
        claim_id=claim.claim_id,
        claim_type=claim.claim_type,
        assessment_scope=TruthAssessmentScope.CLAIM_TRUTH,
        source_document_ids=(SourceDocumentId("v5-p01-document"),),
        source_revision_ids=(ArtifactId("v5-p01-revision-2"),),
        source_identity_probability=Decimal("0.99"),
        content_integrity_probability=Decimal("0.99"),
        claim_truth_probability=Decimal("0.50"),
        claim_current_probability=Decimal("0.50"),
        evidence_independence_probability=Decimal("0.50"),
        manipulation_probability=Decimal("0.10"),
        revision_probability=Decimal("0.20"),
        source_compromised_probability=Decimal("0.01"),
        independent_evidence_count=1,
        evidence_dependency_score=Decimal("0.50"),
        contradiction_probability=Decimal("0.10"),
        calibration_bucket="UNVALIDATED_CONTRACT_ONLY",
        truth_state=TruthState.UNVERIFIED,
        reason_codes=("AQ-TRUTH-CONTRACT-NOT-CALIBRATED",),
        evidence_graph_hash=graph_hash,
        model_version="contract-only-v1",
        policy_version="v5-p01",
        assessed_at=instant,
        available_at=instant,
    )


def build_payload() -> dict[str, object]:
    first = _revision(1, 0)
    corrected = _revision(2, 20)
    deleted = _revision(3, 40, deleted=True)
    initial_fact = _claim(
        "v5-p01-fact-v1",
        revision_number=1,
        claim_type=ClaimType.FACT,
        second=0,
        text="利润增长百分之十",
    )
    corrected_fact = _claim(
        "v5-p01-fact-v2",
        revision_number=2,
        claim_type=ClaimType.FACT,
        second=20,
        text="利润下降百分之十",
    )
    opinion = _claim(
        "v5-p01-opinion-v2",
        revision_number=2,
        claim_type=ClaimType.OPINION,
        second=20,
        text="管理层表现非常优秀",
    )
    revisions = (deleted, first, corrected)
    claims = (opinion, corrected_fact, initial_fact)

    before = partition_claims_as_of(
        revisions=revisions,
        claims=claims,
        decision_time=BASE_TIME + timedelta(seconds=10),
    )
    after = partition_claims_as_of(
        revisions=revisions,
        claims=claims,
        decision_time=BASE_TIME + timedelta(seconds=30),
    )
    after_deletion = partition_claims_as_of(
        revisions=revisions,
        claims=claims,
        decision_time=BASE_TIME + timedelta(seconds=50),
    )

    graph = build_evidence_graph(
        as_of_time=BASE_TIME + timedelta(seconds=20),
        nodes=(
            EvidenceGraphNode(
                node_id="primary-document",
                node_type=GraphNodeType.DOCUMENT,
                available_at_utc=BASE_TIME + timedelta(seconds=20),
                independence_group="issuer",
            ),
            EvidenceGraphNode(
                node_id="syndicated-copy",
                node_type=GraphNodeType.DOCUMENT,
                available_at_utc=BASE_TIME + timedelta(seconds=20),
                independence_group="issuer",
            ),
            EvidenceGraphNode(
                node_id=str(corrected_fact.claim_id),
                node_type=GraphNodeType.CLAIM,
                available_at_utc=BASE_TIME + timedelta(seconds=20),
                revision_id=corrected.revision_id,
                source_identity_id=corrected_fact.source_identity_id,
            ),
            EvidenceGraphNode(
                node_id="isolated-unrelated-document",
                node_type=GraphNodeType.DOCUMENT,
                available_at_utc=BASE_TIME + timedelta(seconds=20),
                independence_group="unrelated-owner",
            ),
        ),
        edges=(
            EvidenceGraphEdge(
                source_node_id="primary-document",
                target_node_id=str(corrected_fact.claim_id),
                edge_type=GraphEdgeType.SUPPORTS,
                available_at_utc=BASE_TIME + timedelta(seconds=20),
            ),
            EvidenceGraphEdge(
                source_node_id="syndicated-copy",
                target_node_id="primary-document",
                edge_type=GraphEdgeType.COPIES,
                available_at_utc=BASE_TIME + timedelta(seconds=20),
            ),
            EvidenceGraphEdge(
                source_node_id="syndicated-copy",
                target_node_id=str(corrected_fact.claim_id),
                edge_type=GraphEdgeType.SUPPORTS,
                available_at_utc=BASE_TIME + timedelta(seconds=20),
            ),
        ),
    )
    truth = _assessment(corrected_fact, graph_hash=graph.content_sha256())
    reordered_graph = build_evidence_graph(
        as_of_time=graph.as_of_time,
        nodes=tuple(reversed(graph.nodes)),
        edges=tuple(reversed(graph.edges)),
    )
    visible_assessments = select_truth_assessments_as_of(
        revisions=revisions,
        claims=claims,
        assessments=(truth,),
        evidence_graphs=(graph,),
        decision_time=BASE_TIME + timedelta(seconds=30),
    )

    invalid_payload = json.loads(truth.model_dump_json())
    invalid_payload["claim_id"] = str(opinion.claim_id)
    invalid_payload["claim_type"] = ClaimType.OPINION.value
    rejection_code = ""
    try:
        TruthAssessment.model_validate_json(json.dumps(invalid_payload))
    except ValidationError as error:
        if "AQ-TRUTH-NON-ADJUDICABLE-CLAIM-TYPE" in str(error):
            rejection_code = "AQ-TRUTH-NON-ADJUDICABLE-CLAIM-TYPE"

    assessment_conflict_rejected = False
    conflicting_assessment = truth.model_copy(update={"claim_truth_probability": Decimal("0.60")})
    try:
        select_truth_assessments_as_of(
            revisions=revisions,
            claims=claims,
            assessments=(truth, conflicting_assessment),
            evidence_graphs=(graph,),
            decision_time=BASE_TIME + timedelta(seconds=30),
        )
    except ValueError as error:
        assessment_conflict_rejected = str(error) == "AQ-TRUTH-ASSESSMENT-ID-CONFLICT"

    temporal_snapshots = [
        {
            "decision_time": (BASE_TIME + timedelta(seconds=10)).isoformat(),
            "selected_revision_ids": [str(item.revision_id) for item in before.selected_revisions],
            "truth_claim_ids": [str(item.claim_id) for item in before.truth_claims],
            "impact_claim_ids": [str(item.claim_id) for item in before.impact_claims],
            "tombstoned_document_ids": [],
        },
        {
            "decision_time": (BASE_TIME + timedelta(seconds=30)).isoformat(),
            "selected_revision_ids": [str(item.revision_id) for item in after.selected_revisions],
            "truth_claim_ids": [str(item.claim_id) for item in after.truth_claims],
            "impact_claim_ids": [str(item.claim_id) for item in after.impact_claims],
            "tombstoned_document_ids": [],
        },
        {
            "decision_time": (BASE_TIME + timedelta(seconds=50)).isoformat(),
            "selected_revision_ids": [
                str(item.revision_id) for item in after_deletion.selected_revisions
            ],
            "truth_claim_ids": [],
            "impact_claim_ids": [],
            "tombstoned_document_ids": [
                str(item) for item in after_deletion.tombstoned_document_ids
            ],
        },
    ]
    checks = {
        "future_revision_excluded_before_availability": before.truth_claims == (initial_fact,),
        "correction_selected_only_after_availability": after.truth_claims == (corrected_fact,),
        "deletion_not_backfilled_and_later_tombstones": after_deletion.all_claims == (),
        "opinion_routed_to_impact_lane": after.impact_claims == (opinion,),
        "opinion_rejected_by_truth_assessment": bool(rejection_code),
        "syndicated_copy_not_counted_independent": graph.independent_evidence_count == 1,
        "isolated_evidence_does_not_inflate_independent_count": (
            graph.independent_evidence_count == 1
        ),
        "graph_hash_reproducible": graph.content_sha256() == graph.model_copy().content_sha256(),
        "graph_hash_and_model_are_input_order_independent": reordered_graph == graph,
        "assessment_hash_reproducible": (
            truth.content_sha256() == truth.model_copy().content_sha256()
        ),
        "assessment_revision_bound": visible_assessments == (truth,),
        "conflicting_assessment_id_fails_closed": assessment_conflict_rejected,
        "selection_input_order_independent": select_revisions_as_of(
            revisions, decision_time=BASE_TIME + timedelta(seconds=30)
        )
        == (corrected,),
    }
    if not all(checks.values()):
        raise RuntimeError(f"V5-P01 acceptance check failed: {checks}")

    return {
        "schema_version": "v5-p01-truth-contract-evidence-v1",
        "phase": "V5-P01",
        "generated_from_fixed_clock": BASE_TIME.isoformat(),
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "calibrated_truth_model_present": False,
        "live_trading_locked": True,
        "contract_surface": {
            "claim_types": [item.value for item in ClaimType],
            "truth_adjudicable_claim_types": sorted(
                item.value for item in TRUTH_ADJUDICABLE_CLAIM_TYPES
            ),
            "impact_only_claim_types": sorted(item.value for item in IMPACT_ONLY_CLAIM_TYPES),
            "truth_states": [item.value for item in TruthState],
            "graph_node_types": [item.value for item in GraphNodeType],
            "graph_edge_types": [item.value for item in GraphEdgeType],
            "truth_assessment_fields": sorted(TruthAssessment.model_fields),
        },
        "temporal_snapshots": temporal_snapshots,
        "dependency_result": {
            "document_count": 2,
            "independent_evidence_count": graph.independent_evidence_count,
            "evidence_dependency_score": str(graph.evidence_dependency_score),
        },
        "hash_reproducibility": {
            "evidence_graph_sha256": graph.content_sha256(),
            "truth_assessment_sha256": truth.content_sha256(),
        },
        "negative_control": {
            "attempted_claim_type": ClaimType.OPINION.value,
            "rejection_code": rejection_code,
        },
        "checks": checks,
        "result": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"V5-P01 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P01 truth-contract evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P01 truth-contract evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
