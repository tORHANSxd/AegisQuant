"""Evidence features, temporal calibration, and Truth Council tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

import pytest

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    SourceDocumentId,
    SourceIdentityId,
    SourcePolicyId,
)
from aegisquant.domain.intelligence import Polarity, RightsState
from aegisquant.domain.truth import (
    AtomicClaim,
    ClaimSpan,
    ClaimType,
    EvidenceQueryKind,
    EvidenceRetrievalHit,
)
from aegisquant.intelligence.graph import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    GraphEdgeType,
    GraphNodeType,
    build_evidence_graph,
)
from aegisquant.research.validation.splits import (
    TemporalFold,
    TemporalSplitPolicy,
    WalkForwardMode,
)
from aegisquant.truth.calibration import (
    ProbabilityCalibrationMethod,
    TruthCalibrationSample,
    TruthModelFamily,
    build_truth_temporal_folds,
    evaluate_truth_probabilities,
    run_truth_council,
)
from aegisquant.truth.features import (
    MODEL_FEATURE_NAMES,
    EvidenceFeatureInputSnapshot,
    EvidenceFeatureVector,
    TruthCalibrationKey,
    extract_evidence_features,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _retrieval_hit(
    *,
    evidence_id: str,
    document_id: str,
    query_kind: EvidenceQueryKind,
    polarity: Polarity,
    official: bool = False,
) -> EvidenceRetrievalHit:
    return EvidenceRetrievalHit(
        evidence_id=ArtifactId(evidence_id),
        search_plan_id=ArtifactId("plan:p04-feature-test"),
        claim_id=ClaimId("claim:p04-feature-test"),
        query_kind=query_kind,
        query_fingerprint_sha256=_sha(query_kind.value),
        source_document_id=SourceDocumentId(document_id),
        source_identity_id=SourceIdentityId(f"source:{document_id}"),
        source_policy_id=SourcePolicyId("policy:public"),
        revision_id=ArtifactId(f"revision:{document_id}:1"),
        revision_number=1,
        canonical_url=f"https://evidence.example/{document_id}",
        content_sha256=_sha(document_id),
        polarity=polarity,
        published_time=BASE_TIME,
        observed_time=BASE_TIME,
        available_at=BASE_TIME,
        retrieved_at=BASE_TIME,
        rights_state=RightsState.ALLOWED,
        is_official_source=official,
        official_identity_verified=official,
        official_identity_assessment_id=(
            ArtifactId(f"identity:{document_id}") if official else None
        ),
    )


def test_feature_extraction_uses_pit_independence_and_keeps_llm_confidence_audit_only() -> None:
    claim = AtomicClaim(
        claim_id=ClaimId("claim:p04-feature-test"),
        source_document_id=SourceDocumentId("document:claim"),
        source_identity_id=SourceIdentityId("source:claim"),
        revision_id=ArtifactId("revision:claim:1"),
        claim_type=ClaimType.FACT,
        original_text="Issuer completed the acquisition.",
        normalized_text="issuer completed acquisition",
        span=ClaimSpan(start=0, end=33, text="Issuer completed the acquisition."),
        language="en",
        entity_ids=("issuer",),
        event_time=BASE_TIME,
        published_time=BASE_TIME,
        first_seen_time=BASE_TIME,
        available_at=BASE_TIME,
        ingested_time=BASE_TIME,
    )
    nodes = (
        EvidenceGraphNode(
            node_id=str(claim.claim_id),
            node_type=GraphNodeType.CLAIM,
            available_at_utc=BASE_TIME,
        ),
        EvidenceGraphNode(
            node_id="document:primary",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=BASE_TIME,
            revision_id=ArtifactId("revision:document:primary:1"),
            source_identity_id=SourceIdentityId("source:document:primary"),
            content_sha256=_sha("document:primary"),
        ),
        EvidenceGraphNode(
            node_id="document:denial",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=BASE_TIME,
            revision_id=ArtifactId("revision:document:denial:1"),
            source_identity_id=SourceIdentityId("source:document:denial"),
            content_sha256=_sha("document:denial"),
        ),
        EvidenceGraphNode(
            node_id="document:shared-origin",
            node_type=GraphNodeType.DOCUMENT,
            available_at_utc=BASE_TIME,
        ),
    )
    edges = (
        EvidenceGraphEdge(
            source_node_id="document:primary",
            target_node_id=str(claim.claim_id),
            edge_type=GraphEdgeType.SUPPORTS,
            available_at_utc=BASE_TIME,
        ),
        EvidenceGraphEdge(
            source_node_id="document:denial",
            target_node_id=str(claim.claim_id),
            edge_type=GraphEdgeType.CONTRADICTS,
            available_at_utc=BASE_TIME,
        ),
        EvidenceGraphEdge(
            source_node_id="document:primary",
            target_node_id="document:shared-origin",
            edge_type=GraphEdgeType.DERIVED_FROM,
            available_at_utc=BASE_TIME,
        ),
        EvidenceGraphEdge(
            source_node_id="document:denial",
            target_node_id="document:shared-origin",
            edge_type=GraphEdgeType.DERIVED_FROM,
            available_at_utc=BASE_TIME,
        ),
    )
    graph = build_evidence_graph(as_of_time=BASE_TIME, nodes=nodes, edges=edges)
    hits = (
        _retrieval_hit(
            evidence_id="hit:primary",
            document_id="document:primary",
            query_kind=EvidenceQueryKind.PRIMARY_SOURCE,
            polarity=Polarity.AFFIRM,
        ),
        _retrieval_hit(
            evidence_id="hit:denial",
            document_id="document:denial",
            query_kind=EvidenceQueryKind.OFFICIAL_DENIAL,
            polarity=Polarity.NEGATE,
            official=True,
        ),
    )
    input_snapshot = EvidenceFeatureInputSnapshot(
        snapshot_id=ArtifactId("feature-inputs:p04-test"),
        claim_id=claim.claim_id,
        source_document_id=claim.source_document_id,
        source_identity_id=claim.source_identity_id,
        source_revision_id=claim.revision_id,
        lineage_artifact_ids=(
            claim.revision_id,
            hits[0].revision_id,
            hits[1].revision_id,
            ArtifactId("source-reliability:p04-test"),
            ArtifactId("consistency-signals:p04-test"),
        ),
        lineage_artifact_sha256s=(
            claim.content_sha256(),
            hits[0].content_sha256,
            hits[1].content_sha256,
            _sha("source-reliability"),
            _sha("consistency-signals"),
        ),
        source_class="OFFICIAL",
        event_type="CORPORATE_ACTION",
        source_reliability_prior=Decimal("0.8"),
        official_signature_valid=True,
        temporal_consistency=Decimal("0.9"),
        entity_consistency=Decimal("1"),
        quote_consistency=Decimal("0.7"),
        media_provenance=Decimal("0.8"),
        retraction_history=Decimal("0.1"),
        language_translation_confidence=Decimal("1"),
        manipulation_signals=Decimal("0.2"),
        llm_confidence_audit_only=Decimal("0.99"),
        observed_at=BASE_TIME,
        available_at=BASE_TIME,
        version="v5-p04-test-v1",
    )
    features = extract_evidence_features(
        feature_id=ArtifactId("features:p04-test"),
        claim=claim,
        evidence_graph=graph,
        evidence_hits=hits,
        input_snapshot=input_snapshot,
        decision_time=BASE_TIME,
    )

    assert graph.independent_evidence_count == 1
    assert features.independent_source_count == 1
    assert features.dependency_score == Decimal("0.5")
    assert features.primary_source_present is True
    assert features.official_denial_present is True
    assert features.contradiction_count == 1
    assert len(features.model_values()) == len(MODEL_FEATURE_NAMES) == 15
    changed_llm = features.model_copy(update={"llm_confidence_audit_only": Decimal("0.01")})
    assert changed_llm.model_values() == features.model_values()

    with pytest.raises(ValueError, match="FUTURE-INPUT"):
        extract_evidence_features(
            feature_id=ArtifactId("features:p04-future-input"),
            claim=claim,
            evidence_graph=graph,
            evidence_hits=hits,
            input_snapshot=input_snapshot.model_copy(
                update={"available_at": BASE_TIME + timedelta(seconds=1)}
            ),
            decision_time=BASE_TIME,
        )
    with pytest.raises(ValueError, match="EVIDENCE-REVISION-MISMATCH"):
        extract_evidence_features(
            feature_id=ArtifactId("features:p04-wrong-revision"),
            claim=claim,
            evidence_graph=graph,
            evidence_hits=(
                hits[0].model_copy(update={"revision_id": ArtifactId("revision:wrong")}),
                hits[1],
            ),
            input_snapshot=input_snapshot,
            decision_time=BASE_TIME,
        )
    invalid_lineage_hashes = list(input_snapshot.lineage_artifact_sha256s)
    invalid_lineage_hashes[0] = _sha("wrong-claim-revision")
    with pytest.raises(ValueError, match="CLAIM-LINEAGE-MISMATCH"):
        extract_evidence_features(
            feature_id=ArtifactId("features:p04-wrong-lineage"),
            claim=claim,
            evidence_graph=graph,
            evidence_hits=hits,
            input_snapshot=input_snapshot.model_copy(
                update={"lineage_artifact_sha256s": tuple(invalid_lineage_hashes)}
            ),
            decision_time=BASE_TIME,
        )


def _feature(index: int, decision_time: datetime, label: int) -> EvidenceFeatureVector:
    quality = (index * 7) % 10
    keys = (
        ("OFFICIAL", "CORPORATE_ACTION", "en", ClaimType.FACT),
        ("NEWSWIRE", "MACRO", "en", ClaimType.QUOTE),
        ("REGULATOR", "POLICY", "zh", ClaimType.FACT),
        ("MEDIA", "GEOPOLITICAL", "zh", ClaimType.QUOTE),
    )
    source_class, event_type, language, claim_type = keys[index % len(keys)]
    return EvidenceFeatureVector(
        feature_id=ArtifactId(f"feature:{index:03d}"),
        claim_id=ClaimId(f"claim:{index:03d}"),
        source_revision_id=ArtifactId(f"revision:{index:03d}:1"),
        input_snapshot_id=ArtifactId(f"feature-inputs:{index:03d}"),
        input_snapshot_sha256=_sha(f"feature-inputs:{index}"),
        calibration_key=TruthCalibrationKey(
            source_class=source_class,
            event_type=event_type,
            language=language,
            claim_type=claim_type,
        ),
        primary_source_present=quality >= 6,
        official_signature_valid=quality >= 8,
        source_reliability_prior=Decimal(30 + quality * 6) / Decimal(100),
        independent_source_count=1 + quality % 4,
        dependency_score=Decimal(9 - quality) / Decimal(10),
        contradiction_count=1 if quality < 4 else 0,
        official_denial_present=quality < 2,
        temporal_consistency=Decimal(4 + quality) / Decimal(14),
        entity_consistency=Decimal(5 + quality) / Decimal(15),
        quote_consistency=Decimal(6 + quality) / Decimal(16),
        media_provenance=Decimal(quality) / Decimal(10),
        revision_count=1 + index % 3,
        retraction_history=Decimal(2 if quality < 3 else 0) / Decimal(10),
        language_translation_confidence=Decimal("0.95") if language == "en" else Decimal("0.8"),
        manipulation_signals=Decimal(9 - quality) / Decimal(10),
        llm_confidence_audit_only=Decimal("0.91") if label == 0 else Decimal("0.09"),
        evidence_graph_sha256=_sha(f"graph:{index}"),
        feature_version="v5-p04-test-v1",
        extracted_at=decision_time,
        available_at=decision_time,
    )


def calibration_samples() -> tuple[TruthCalibrationSample, ...]:
    output: list[TruthCalibrationSample] = []
    for index in range(58):
        decision_time = BASE_TIME + timedelta(days=index)
        quality = (index * 7) % 10
        label: Literal[0, 1] = 1 if quality >= 5 else 0
        if index % 13 == 0:
            label = 0 if label == 1 else 1
        output.append(
            TruthCalibrationSample(
                sample_id=f"sample:{index:03d}",
                claim_id=ClaimId(f"claim:{index:03d}"),
                features=_feature(index, decision_time, label),
                truth_label=label,
                decision_time=decision_time,
                resolved_at=decision_time + timedelta(hours=1),
                label_available_at=decision_time + timedelta(hours=2),
                label_sha256=_sha(f"label:{index}:{label}"),
                sample_version="v5-p04-test-v1",
                created_at=decision_time + timedelta(hours=2),
                available_at=decision_time + timedelta(hours=2),
            )
        )
    return tuple(output)


def split_policy() -> TemporalSplitPolicy:
    return TemporalSplitPolicy(
        policy_id="v5-p04-temporal-test-v1",
        mode=WalkForwardMode.EXPANDING,
        train_groups=28,
        validation_groups=8,
        calibration_groups=8,
        test_groups=12,
        purge_groups=1,
        embargo_groups=1,
        step_groups=58,
        minimum_folds=1,
        shuffle=False,
    )


def test_truth_council_has_disjoint_temporal_calibration_and_no_llm_probability_path() -> None:
    samples = calibration_samples()
    policy = split_policy()
    folds = build_truth_temporal_folds(samples, policy)
    assert len(folds) == 1
    fold = folds[0]
    partitions = (fold.train_ids, fold.validation_ids, fold.calibration_ids, fold.test_ids)
    assert len({sample_id for part in partitions for sample_id in part}) == sum(
        len(part) for part in partitions
    )
    report = run_truth_council(
        samples=samples,
        split_policy=policy,
        fold=fold,
        as_of_time=samples[-1].available_at + timedelta(hours=1),
        minimum_incremental_improvement=Decimal("1"),
    )

    assert {item.family for item in report.candidates} == set(TruthModelFamily)
    assert report.selected_model_id == report.baseline_model_id
    assert {item.method for item in report.calibration_comparisons} == set(
        ProbabilityCalibrationMethod
    )
    assert report.llm_confidence_used_as_model_input is False
    assert report.test_labels_used_for_model_selection is False
    assert "llm_confidence_audit_only" not in report.feature_names
    selected = next(
        item
        for item in report.calibration_comparisons
        if item.method is report.selected_calibration_method
    )
    assert selected.metrics.calibration_slope is not None
    assert selected.metrics.calibration_intercept is not None
    assert len(selected.metrics.reliability_diagram) == 10
    llm_values = tuple(
        next(
            sample for sample in samples if sample.sample_id == sample_id
        ).features.llm_confidence_audit_only
        for sample_id in fold.test_ids
    )
    assert selected.probabilities != llm_values

    with pytest.raises(ValueError, match="FUTURE-LABEL"):
        run_truth_council(
            samples=samples,
            split_policy=policy,
            fold=fold,
            as_of_time=samples[-1].decision_time,
        )


def test_truth_council_rejects_forged_temporal_fold_and_misbound_feature() -> None:
    samples = calibration_samples()
    policy = split_policy()
    fold = build_truth_temporal_folds(samples, policy)[0]
    payload = {
        "train_ids": list(fold.test_ids),
        "validation_ids": list(fold.validation_ids),
        "calibration_ids": list(fold.calibration_ids),
        "test_ids": list(fold.train_ids),
        "purged_ids": list(fold.purged_ids),
        "validation_starts_at": fold.validation_starts_at.isoformat(),
        "test_ends_at": fold.test_ends_at.isoformat(),
    }
    forged = TemporalFold(
        fold_id=canonical_sha256(payload),
        train_ids=fold.test_ids,
        validation_ids=fold.validation_ids,
        calibration_ids=fold.calibration_ids,
        test_ids=fold.train_ids,
        purged_ids=fold.purged_ids,
        validation_starts_at=fold.validation_starts_at,
        test_ends_at=fold.test_ends_at,
    )
    with pytest.raises(ValueError, match="FOLD-POLICY-MISMATCH"):
        run_truth_council(
            samples=samples,
            split_policy=policy,
            fold=forged,
            as_of_time=samples[-1].available_at + timedelta(hours=1),
        )

    sample_payload = {
        field_name: getattr(samples[0], field_name)
        for field_name in TruthCalibrationSample.model_fields
    }
    sample_payload["claim_id"] = ClaimId("claim:wrong")
    with pytest.raises(ValueError, match="FEATURE-CLAIM-MISMATCH"):
        TruthCalibrationSample.model_validate(sample_payload)

    duplicated_claim_feature = samples[-1].features.model_copy(
        update={"claim_id": samples[0].claim_id}
    )
    duplicated_claim_sample = samples[-1].model_copy(
        update={"claim_id": samples[0].claim_id, "features": duplicated_claim_feature}
    )
    with pytest.raises(ValueError, match="DUPLICATE-CALIBRATION-CLAIM-ID"):
        run_truth_council(
            samples=(*samples[:-1], duplicated_claim_sample),
            split_policy=policy,
            fold=fold,
            as_of_time=samples[-1].available_at + timedelta(hours=1),
        )


def test_calibration_metrics_include_brier_logloss_and_reliability_diagram() -> None:
    metrics = evaluate_truth_probabilities(
        probabilities=(Decimal("0.9"), Decimal("0.8"), Decimal("0.2"), Decimal("0.1")),
        labels=(1, 1, 0, 0),
    )

    assert metrics.brier_score == Decimal("0.025")
    assert abs(metrics.log_loss - Decimal("0.164252033486018")) < Decimal("1e-14")
    assert metrics.expected_calibration_error == Decimal("0.15")
    assert metrics.maximum_calibration_error == Decimal("0.2")
    assert metrics.high_confidence_sample_count == 4
    assert metrics.high_confidence_accuracy == Decimal("1")
    assert sum(item.sample_count for item in metrics.reliability_diagram) == 4
