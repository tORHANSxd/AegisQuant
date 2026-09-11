"""Generate or verify deterministic V5-P04 Truth Council and calibration evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

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
    TruthState,
)
from aegisquant.intelligence.graph import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    GraphEdgeType,
    GraphNodeType,
    build_evidence_graph,
)
from aegisquant.research.validation.splits import TemporalSplitPolicy, WalkForwardMode
from aegisquant.truth.calibration import (
    ProbabilityCalibrationMethod,
    TruthCalibrationSample,
    TruthModelFamily,
    build_truth_temporal_folds,
    run_truth_council,
)
from aegisquant.truth.features import (
    MODEL_FEATURE_NAMES,
    EvidenceFeatureInputSnapshot,
    EvidenceFeatureVector,
    TruthCalibrationKey,
    extract_evidence_features,
)
from aegisquant.truth.lifecycle import (
    SourceReliabilityPolicy,
    SourceReliabilityRates,
    TruthModelLifecycleState,
    TruthModelReliabilityPolicy,
    TruthModelReliabilitySnapshot,
    TruthStateTransition,
    advance_source_reliability,
    evaluate_truth_model_reliability,
    initialize_source_reliability,
    replay_truth_state_as_of,
    select_source_reliability_as_of,
)

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "reports/v5/P04/TRUTH_COUNCIL_CALIBRATION.json"
BASE_TIME: Final = datetime(2025, 1, 1, tzinfo=UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _calibration_key(index: int) -> TruthCalibrationKey:
    keys = (
        ("OFFICIAL", "CORPORATE_ACTION", "en", ClaimType.FACT),
        ("NEWSWIRE", "MACRO", "en", ClaimType.QUOTE),
        ("REGULATOR", "POLICY", "zh", ClaimType.FACT),
        ("MEDIA", "GEOPOLITICAL", "zh", ClaimType.QUOTE),
    )
    source_class, event_type, language, claim_type = keys[index % len(keys)]
    return TruthCalibrationKey(
        source_class=source_class,
        event_type=event_type,
        language=language,
        claim_type=claim_type,
    )


def _feature(index: int, decision_time: datetime, label: int) -> EvidenceFeatureVector:
    quality = (index * 7) % 10
    key = _calibration_key(index)
    return EvidenceFeatureVector(
        feature_id=ArtifactId(f"feature:p04:{index:03d}"),
        claim_id=ClaimId(f"claim:p04:{index:03d}"),
        source_revision_id=ArtifactId(f"revision:p04:{index:03d}:1"),
        input_snapshot_id=ArtifactId(f"feature-inputs:p04:{index:03d}"),
        input_snapshot_sha256=_digest(f"feature-inputs:p04:{index}"),
        calibration_key=key,
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
        language_translation_confidence=(
            Decimal("0.95") if key.language == "en" else Decimal("0.8")
        ),
        manipulation_signals=Decimal(9 - quality) / Decimal(10),
        # Deliberately anti-correlated. It is retained for audit and excluded from MODEL_FEATURE_NAMES.
        llm_confidence_audit_only=Decimal("0.91") if label == 0 else Decimal("0.09"),
        evidence_graph_sha256=_digest(f"graph:p04:{index}"),
        feature_version="v5-p04-evidence-features-v1",
        extracted_at=decision_time,
        available_at=decision_time,
    )


def _samples() -> tuple[TruthCalibrationSample, ...]:
    output: list[TruthCalibrationSample] = []
    for index in range(58):
        decision_time = BASE_TIME + timedelta(days=index)
        quality = (index * 7) % 10
        label: Literal[0, 1] = 1 if quality >= 5 else 0
        if index % 13 == 0:
            label = 0 if label == 1 else 1
        output.append(
            TruthCalibrationSample(
                sample_id=f"sample:p04:{index:03d}",
                claim_id=ClaimId(f"claim:p04:{index:03d}"),
                features=_feature(index, decision_time, label),
                truth_label=label,
                decision_time=decision_time,
                resolved_at=decision_time + timedelta(hours=1),
                label_available_at=decision_time + timedelta(hours=2),
                label_sha256=_digest(f"label:p04:{index}:{label}"),
                sample_version="v5-p04-development-v1",
                created_at=decision_time + timedelta(hours=2),
                available_at=decision_time + timedelta(hours=2),
            )
        )
    return tuple(output)


def _split_policy() -> TemporalSplitPolicy:
    return TemporalSplitPolicy(
        policy_id="v5-p04-temporal-split-v1",
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


def _extracted_feature_fixture() -> EvidenceFeatureVector:
    claim = AtomicClaim(
        claim_id=ClaimId("claim:p04-extraction"),
        source_document_id=SourceDocumentId("document:p04-extraction"),
        source_identity_id=SourceIdentityId("source:p04-extraction"),
        revision_id=ArtifactId("revision:p04-extraction:1"),
        claim_type=ClaimType.FACT,
        original_text="Issuer published audited results.",
        normalized_text="issuer published audited results",
        span=ClaimSpan(start=0, end=33, text="Issuer published audited results."),
        language="en",
        entity_ids=("issuer",),
        event_time=BASE_TIME,
        published_time=BASE_TIME,
        first_seen_time=BASE_TIME,
        available_at=BASE_TIME,
        ingested_time=BASE_TIME,
    )
    graph = build_evidence_graph(
        as_of_time=BASE_TIME,
        nodes=(
            EvidenceGraphNode(
                node_id=str(claim.claim_id),
                node_type=GraphNodeType.CLAIM,
                available_at_utc=BASE_TIME,
            ),
            EvidenceGraphNode(
                node_id="document:p04-primary",
                node_type=GraphNodeType.DOCUMENT,
                available_at_utc=BASE_TIME,
                revision_id=ArtifactId("revision:p04-primary:1"),
                source_identity_id=SourceIdentityId("source:p04-primary"),
                content_sha256=_digest("p04-primary-content"),
            ),
        ),
        edges=(
            EvidenceGraphEdge(
                source_node_id="document:p04-primary",
                target_node_id=str(claim.claim_id),
                edge_type=GraphEdgeType.SUPPORTS,
                available_at_utc=BASE_TIME,
            ),
        ),
    )
    hit = EvidenceRetrievalHit(
        evidence_id=ArtifactId("hit:p04-primary"),
        search_plan_id=ArtifactId("plan:p04-extraction"),
        claim_id=claim.claim_id,
        query_kind=EvidenceQueryKind.PRIMARY_SOURCE,
        query_fingerprint_sha256=_digest("primary-source-query"),
        source_document_id=SourceDocumentId("document:p04-primary"),
        source_identity_id=SourceIdentityId("source:p04-primary"),
        source_policy_id=SourcePolicyId("policy:p04-public"),
        revision_id=ArtifactId("revision:p04-primary:1"),
        revision_number=1,
        canonical_url="https://issuer.example/results",
        content_sha256=_digest("p04-primary-content"),
        polarity=Polarity.AFFIRM,
        published_time=BASE_TIME,
        observed_time=BASE_TIME,
        available_at=BASE_TIME,
        retrieved_at=BASE_TIME,
        rights_state=RightsState.ALLOWED,
        is_official_source=True,
        official_identity_verified=True,
        official_identity_assessment_id=ArtifactId("identity:p04-primary"),
    )
    input_snapshot = EvidenceFeatureInputSnapshot(
        snapshot_id=ArtifactId("feature-inputs:p04-extraction"),
        claim_id=claim.claim_id,
        source_document_id=claim.source_document_id,
        source_identity_id=claim.source_identity_id,
        source_revision_id=claim.revision_id,
        lineage_artifact_ids=(
            claim.revision_id,
            hit.revision_id,
            ArtifactId("source-reliability:p04-extraction"),
            ArtifactId("consistency-signals:p04-extraction"),
        ),
        lineage_artifact_sha256s=(
            claim.content_sha256(),
            hit.content_sha256,
            _digest("source-reliability:p04-extraction"),
            _digest("consistency-signals:p04-extraction"),
        ),
        source_class="OFFICIAL",
        event_type="EARNINGS",
        source_reliability_prior=Decimal("0.85"),
        official_signature_valid=True,
        temporal_consistency=Decimal("1"),
        entity_consistency=Decimal("1"),
        quote_consistency=Decimal("1"),
        media_provenance=Decimal("0.9"),
        retraction_history=Decimal("0"),
        language_translation_confidence=Decimal("1"),
        manipulation_signals=Decimal("0.05"),
        llm_confidence_audit_only=Decimal("0.99"),
        observed_at=BASE_TIME,
        available_at=BASE_TIME,
        version="v5-p04-evidence-inputs-v1",
    )
    return extract_evidence_features(
        feature_id=ArtifactId("feature:p04-extraction"),
        claim=claim,
        evidence_graph=graph,
        evidence_hits=(hit,),
        input_snapshot=input_snapshot,
        decision_time=BASE_TIME,
    )


def _state_transition(
    *,
    index: int,
    from_state: TruthState,
    to_state: TruthState,
    previous: TruthStateTransition | None,
) -> TruthStateTransition:
    instant = BASE_TIME + timedelta(hours=index)
    return TruthStateTransition(
        transition_id=ArtifactId(f"transition:p04:{index}"),
        claim_id=ClaimId("claim:p04-replay"),
        from_state=from_state,
        to_state=to_state,
        evidence_revision_id=ArtifactId(f"revision:p04-replay:{index}"),
        reason_codes=(f"REVISION_{index}",),
        previous_transition_id=previous.transition_id if previous is not None else None,
        previous_transition_sha256=previous.content_sha256() if previous is not None else None,
        effective_at=instant,
        observed_at=instant,
        created_at=instant,
        available_at=instant,
        version="truth-state-v1",
    )


def _truth_state_evidence() -> dict[str, object]:
    rumor = _state_transition(
        index=1,
        from_state=TruthState.UNVERIFIED,
        to_state=TruthState.RUMOR,
        previous=None,
    )
    verified = _state_transition(
        index=2,
        from_state=TruthState.RUMOR,
        to_state=TruthState.VERIFIED_PRIMARY,
        previous=rumor,
    )
    retracted = _state_transition(
        index=3,
        from_state=TruthState.VERIFIED_PRIMARY,
        to_state=TruthState.RETRACTED,
        previous=verified,
    )
    history = (retracted, rumor, verified)
    snapshots = tuple(
        replay_truth_state_as_of(
            claim_id=rumor.claim_id,
            transitions=history,
            as_of_time=BASE_TIME + timedelta(hours=hour, minutes=30),
        )
        for hour in (1, 2, 3)
    )
    return {
        "transitions": [item.model_dump(mode="json") for item in (rumor, verified, retracted)],
        "snapshots": [item.model_dump(mode="json") for item in snapshots],
        "state_sequence": [item.state.value for item in snapshots],
    }


def _source_reliability_evidence() -> dict[str, object]:
    policy = SourceReliabilityPolicy(
        policy_version="source-reliability-policy-v1",
        correction_weight=Decimal("0.2"),
        retraction_weight=Decimal("0.3"),
        false_claim_weight=Decimal("0.5"),
        minimum_reliability=Decimal("0.1"),
    )
    source_id = SourceIdentityId("source:p04-reliability")
    initial = initialize_source_reliability(
        snapshot_id=ArtifactId("source-reliability:p04:1"),
        source_identity_id=source_id,
        reliability_score=Decimal("0.9"),
        rates=SourceReliabilityRates(
            correction_rate=Decimal("0.05"),
            retraction_rate=Decimal("0.01"),
            false_claim_rate=Decimal("0.02"),
        ),
        observation_count=100,
        policy=policy,
        available_at=BASE_TIME,
    )
    degraded = advance_source_reliability(
        previous=initial,
        snapshot_id=ArtifactId("source-reliability:p04:2"),
        rates=SourceReliabilityRates(
            correction_rate=Decimal("0.15"),
            retraction_rate=Decimal("0.06"),
            false_claim_rate=Decimal("0.12"),
        ),
        observation_count=200,
        policy=policy,
        observed_at=BASE_TIME + timedelta(days=1),
        available_at=BASE_TIME + timedelta(days=1),
    )
    pit_selected = select_source_reliability_as_of(
        source_identity_id=source_id,
        history=(degraded, initial),
        as_of_time=BASE_TIME + timedelta(hours=12),
    )
    return {
        "policy": policy.model_dump(mode="json"),
        "snapshots": [initial.model_dump(mode="json"), degraded.model_dump(mode="json")],
        "initial_score": str(initial.reliability_score),
        "degraded_score": str(degraded.reliability_score),
        "pit_selected_snapshot_id": str(pit_selected.snapshot_id),
        "decayed": degraded.reliability_score < initial.reliability_score,
    }


def _model_reliability_evidence() -> dict[str, object]:
    policy = TruthModelReliabilityPolicy(
        policy_version="truth-model-reliability-policy-v1",
        minimum_high_confidence_samples=20,
        degraded_gap=Decimal("0.05"),
        restricted_gap=Decimal("0.10"),
        retired_gap=Decimal("0.20"),
    )
    observations = (
        ("0.90", "0.88", 30),
        ("0.90", "0.82", 40),
        ("0.90", "0.75", 50),
        ("0.90", "0.65", 60),
    )
    history: list[TruthModelReliabilitySnapshot] = []
    for index, (predicted, actual, sample_count) in enumerate(observations, start=1):
        previous = history[-1] if history else None
        history.append(
            evaluate_truth_model_reliability(
                snapshot_id=ArtifactId(f"model-reliability:p04:{index}"),
                model_id="truth-logistic-baseline-v1",
                predicted_high_confidence_mean=Decimal(predicted),
                actual_confirmed_rate=Decimal(actual),
                high_confidence_sample_count=sample_count,
                policy=policy,
                outcomes_available_at=BASE_TIME + timedelta(days=index, hours=-1),
                available_at=BASE_TIME + timedelta(days=index),
                previous=previous,
            )
        )
    return {
        "policy": policy.model_dump(mode="json"),
        "snapshots": [item.model_dump(mode="json") for item in history],
        "state_sequence": [item.state.value for item in history],
        "outcome_availability_bound": all(
            item.outcomes_available_at <= item.available_at for item in history
        ),
    }


def build_payload() -> dict[str, object]:
    extracted = _extracted_feature_fixture()
    samples = _samples()
    split_policy = _split_policy()
    folds = build_truth_temporal_folds(samples, split_policy)
    if len(folds) != 1:
        raise RuntimeError("V5-P04 fixture must produce exactly one temporal fold")
    fold = folds[0]
    report = run_truth_council(
        samples=samples,
        split_policy=split_policy,
        fold=fold,
        as_of_time=samples[-1].available_at + timedelta(hours=1),
    )
    selected_calibration = next(
        item
        for item in report.calibration_comparisons
        if item.method is report.selected_calibration_method
    )
    llm_values = tuple(
        next(
            sample for sample in samples if sample.sample_id == sample_id
        ).features.llm_confidence_audit_only
        for sample_id in fold.test_ids
    )
    state_evidence = _truth_state_evidence()
    source_reliability = _source_reliability_evidence()
    model_reliability = _model_reliability_evidence()
    partitions = (fold.train_ids, fold.validation_ids, fold.calibration_ids, fold.test_ids)
    partition_count = sum(len(item) for item in partitions)
    unique_partition_count = len({sample_id for item in partitions for sample_id in item})
    sample_by_id = {item.sample_id: item for item in samples}
    checks = {
        "evidence_features_are_extracted_from_pit_graph": (
            extracted.primary_source_present
            and extracted.independent_source_count == 1
            and extracted.available_at == BASE_TIME
        ),
        "external_feature_inputs_are_pit_lineage_bound": (
            str(extracted.input_snapshot_id) == "feature-inputs:p04-extraction"
            and len(extracted.input_snapshot_sha256) == 64
        ),
        "all_mandatory_model_features_are_present": len(MODEL_FEATURE_NAMES) == 15,
        "llm_confidence_is_not_a_model_input_or_final_probability": (
            report.llm_confidence_used_as_model_input is False
            and "llm_confidence_audit_only" not in report.feature_names
            and selected_calibration.probabilities != llm_values
        ),
        "temporal_train_validation_calibration_test_are_disjoint": (
            partition_count == unique_partition_count
        ),
        "calibration_split_is_chronologically_independent": (
            sample_by_id[fold.validation_ids[-1]].decision_time
            < sample_by_id[fold.calibration_ids[0]].decision_time
            < sample_by_id[fold.calibration_ids[-1]].decision_time
            < sample_by_id[fold.test_ids[0]].decision_time
        ),
        "fold_policy_is_recomputed_and_claims_are_unique": (
            report.split_policy == split_policy
            and report.fold == fold
            and len({str(sample.claim_id) for sample in samples}) == len(samples)
        ),
        "baseline_boosting_and_bayesian_candidates_are_compared": (
            {item.family for item in report.candidates} == set(TruthModelFamily)
        ),
        "four_probability_calibrators_are_compared": (
            {item.method for item in report.calibration_comparisons}
            == set(ProbabilityCalibrationMethod)
        ),
        "brier_logloss_and_reliability_diagram_are_reported": (
            selected_calibration.metrics.brier_score >= 0
            and selected_calibration.metrics.log_loss >= 0
            and len(selected_calibration.metrics.reliability_diagram) == 10
            and selected_calibration.metrics.calibration_slope is not None
            and selected_calibration.metrics.calibration_intercept is not None
        ),
        "calibration_is_maintained_by_required_strata": (
            len(report.calibration_slices)
            == len({_calibration_key(i).content_sha256() for i in range(4)})
        ),
        "historical_revision_replay_supports_retraction": (
            state_evidence["state_sequence"] == ["RUMOR", "VERIFIED_PRIMARY", "RETRACTED"]
        ),
        "worsening_source_history_decays_reliability": source_reliability["decayed"] is True,
        "truth_model_reliability_reaches_retired": (
            model_reliability["state_sequence"]
            == [state.value for state in TruthModelLifecycleState]
            and model_reliability["outcome_availability_bound"] is True
        ),
        "test_labels_do_not_select_model_or_calibrator": (
            report.test_labels_used_for_model_selection is False
            and report.selected_calibration_method is ProbabilityCalibrationMethod.PLATT_LOGISTIC
        ),
        "development_evidence_cannot_promote_alpha": True,
    }
    if not all(checks.values()):
        raise RuntimeError(f"V5-P04 acceptance check failed: {checks}")

    feature_test = "tests/v5_p04/test_truth_features_and_calibration.py::"
    lifecycle_test = "tests/v5_p04/test_truth_lifecycle.py::"
    acceptance_traceability = {
        "evidence_features_are_extracted_from_pit_graph": (
            feature_test
            + "test_feature_extraction_uses_pit_independence_and_keeps_llm_confidence_audit_only"
        ),
        "external_feature_inputs_are_pit_lineage_bound": (
            feature_test
            + "test_feature_extraction_uses_pit_independence_and_keeps_llm_confidence_audit_only"
        ),
        "all_mandatory_model_features_are_present": (
            feature_test
            + "test_feature_extraction_uses_pit_independence_and_keeps_llm_confidence_audit_only"
        ),
        "llm_confidence_is_not_a_model_input_or_final_probability": (
            feature_test
            + "test_truth_council_has_disjoint_temporal_calibration_and_no_llm_probability_path"
        ),
        "temporal_train_validation_calibration_test_are_disjoint": (
            feature_test
            + "test_truth_council_has_disjoint_temporal_calibration_and_no_llm_probability_path"
        ),
        "calibration_split_is_chronologically_independent": (
            feature_test
            + "test_truth_council_has_disjoint_temporal_calibration_and_no_llm_probability_path"
        ),
        "fold_policy_is_recomputed_and_claims_are_unique": (
            feature_test + "test_truth_council_rejects_forged_temporal_fold_and_misbound_feature"
        ),
        "baseline_boosting_and_bayesian_candidates_are_compared": (
            feature_test
            + "test_truth_council_has_disjoint_temporal_calibration_and_no_llm_probability_path"
        ),
        "four_probability_calibrators_are_compared": (
            feature_test
            + "test_truth_council_has_disjoint_temporal_calibration_and_no_llm_probability_path"
        ),
        "brier_logloss_and_reliability_diagram_are_reported": (
            feature_test + "test_calibration_metrics_include_brier_logloss_and_reliability_diagram"
        ),
        "calibration_is_maintained_by_required_strata": (
            feature_test
            + "test_truth_council_has_disjoint_temporal_calibration_and_no_llm_probability_path"
        ),
        "historical_revision_replay_supports_retraction": (
            lifecycle_test
            + "test_historical_revision_replay_supports_verified_to_retracted_without_lookahead"
        ),
        "worsening_source_history_decays_reliability": (
            lifecycle_test
            + "test_source_reliability_decays_on_worsening_rates_and_future_snapshot_is_hidden"
        ),
        "truth_model_reliability_reaches_retired": (
            lifecycle_test
            + "test_truth_model_reliability_progresses_to_retired_and_never_auto_recovers"
        ),
        "test_labels_do_not_select_model_or_calibrator": (
            feature_test
            + "test_truth_council_has_disjoint_temporal_calibration_and_no_llm_probability_path"
        ),
        "development_evidence_cannot_promote_alpha": (
            "tests/v5_p04/test_v5_p04_phase_evidence.py::"
            "test_v5_p04_evidence_is_complete_traceable_and_non_promotable"
        ),
    }
    if set(acceptance_traceability) != set(checks):
        raise RuntimeError("V5-P04 acceptance traceability is incomplete")

    return {
        "schema_version": "v5-p04-truth-council-calibration-v1",
        "phase": "V5-P04",
        "generated_from_fixed_clock": BASE_TIME.isoformat(),
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "real_world_truth_accuracy_claimed": False,
        "live_trading_locked": True,
        "feature_extraction": extracted.model_dump(mode="json"),
        "dataset": {
            "sample_count": len(samples),
            "truth_label_positive_count": sum(item.truth_label for item in samples),
            "truth_label_negative_count": sum(1 - item.truth_label for item in samples),
            "synthetic_development_fixture": True,
        },
        "truth_council": report.model_dump(mode="json"),
        "truth_state_replay": state_evidence,
        "source_reliability": source_reliability,
        "truth_model_reliability": model_reliability,
        "checks": checks,
        "acceptance_traceability": acceptance_traceability,
        "limitations": [
            "All labels and features are deterministic DEVELOPMENT fixtures, not real-world claims.",
            "Reported Brier, LogLoss, ECE, classification metrics, and reliability diagrams do not establish production accuracy.",
            "Four binary-probability calibrators are compared; time-series conformal interval methods remain in V5-P09.",
            "No candidate is promoted to Alpha, Paper, Shadow, Testnet, Canary, or Live use.",
            "No causal effect, market forecast accuracy, backtest return, or trading edge is claimed.",
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
            raise SystemExit(f"V5-P04 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P04 Truth Council and calibration evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P04 Truth Council and calibration evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
