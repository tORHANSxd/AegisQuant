"""Generate or verify deterministic V5-P05 event-context evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    EventClusterId,
    ProviderId,
    SourceDocumentId,
)
from aegisquant.domain.intelligence import (
    ContentType,
    EventCluster,
    EventClusterStatus,
    QualityState,
)
from aegisquant.domain.truth import (
    ClaimType,
    TruthAssessment,
    TruthAssessmentScope,
    TruthState,
)
from aegisquant.intelligence.canonical_events import (
    DEFAULT_MARKET_REFLECTION_POLICY,
    CanonicalEvent,
    EventValueKind,
    MarketReflectionMetric,
    build_canonical_event,
    build_event_directional_gate,
    build_event_value_snapshot,
    build_market_reflection_metric,
    build_narrative_diffusion,
    build_narrative_observation,
    build_timed_event_value,
    calculate_event_surprise,
    calculate_market_reflection,
)
from aegisquant.intelligence.collectors import CollectedContent, SourceKind
from aegisquant.intelligence.pipeline import run_pipeline

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "reports/v5/P05/EVENT_CANONICALIZATION_EVIDENCE.json"
BASE_TIME: Final = datetime(2026, 9, 2, 12, tzinfo=UTC)
AS_OF_TIME: Final = BASE_TIME + timedelta(minutes=30)
HASH_A: Final = "a" * 64
HASH_B: Final = "b" * 64
CLUSTER_ID: Final = EventClusterId("event:p05:macro-release")


def _cluster(status: EventClusterStatus) -> EventCluster:
    return EventCluster(
        event_cluster_id=CLUSTER_ID,
        event_type="MACRO_RELEASE",
        status=status,
        entity_ids=("asset:BTC", "regulator:US_FED"),
        claimed_event_time=BASE_TIME,
        first_observed_time=BASE_TIME,
        last_updated_time=BASE_TIME + timedelta(minutes=10),
        claim_ids=(ClaimId("claim:p05:macro-release"),),
        supporting_evidence_ids=(
            SourceDocumentId("document:p05:official"),
            SourceDocumentId("document:p05:wire"),
        ),
        contradicting_evidence_ids=(),
        independent_source_count=2,
        official_confirmation_ids=(
            (SourceDocumentId("document:p05:official"),)
            if status is EventClusterStatus.CONFIRMED
            else ()
        ),
        credibility_score=Decimal("0.95"),
        manipulation_risk=Decimal("0.02"),
        uncertainty=Decimal("0.10"),
    )


def _truth(state: TruthState) -> TruthAssessment:
    available_at = BASE_TIME + timedelta(minutes=10)
    return TruthAssessment(
        assessment_id=ArtifactId(f"truth:p05:{state.value.casefold()}"),
        claim_id=ClaimId("claim:p05:macro-release"),
        claim_type=ClaimType.FACT,
        assessment_scope=TruthAssessmentScope.CLAIM_TRUTH,
        source_document_ids=(
            SourceDocumentId("document:p05:official"),
            SourceDocumentId("document:p05:wire"),
        ),
        source_revision_ids=(
            ArtifactId("revision:p05:official:1"),
            ArtifactId("revision:p05:wire:1"),
        ),
        source_identity_probability=Decimal("0.99"),
        content_integrity_probability=Decimal("0.99"),
        claim_truth_probability=Decimal("0.97"),
        claim_current_probability=Decimal("0.98"),
        evidence_independence_probability=Decimal("0.95"),
        manipulation_probability=Decimal("0.02"),
        revision_probability=Decimal("0.03"),
        source_compromised_probability=Decimal("0.01"),
        independent_evidence_count=2,
        evidence_dependency_score=Decimal("0.05"),
        contradiction_probability=Decimal("0.02"),
        calibration_bucket="DEVELOPMENT_P05",
        truth_state=state,
        reason_codes=("AQ-P05-DEVELOPMENT-TRUTH",),
        evidence_graph_hash=HASH_A,
        model_version="truth-p04-development-v1",
        policy_version="v5-p04",
        assessed_at=available_at,
        available_at=available_at,
    )


def _value_and_surprise():
    values = tuple(
        build_timed_event_value(
            event_cluster_id=CLUSTER_ID,
            kind=kind,
            value=value,
            unit="percent",
            observed_at=BASE_TIME + timedelta(minutes=index),
            available_at=BASE_TIME + timedelta(minutes=index + 1),
            source_artifact_id=ArtifactId(f"value-source:p05:{kind.value.casefold()}"),
            source_sha256=HASH_B,
        )
        for index, (kind, value) in enumerate(
            (
                (EventValueKind.ACTUAL, Decimal("3.5")),
                (EventValueKind.CONSENSUS, Decimal("3.0")),
                (EventValueKind.WHISPER, Decimal("3.2")),
            ),
            start=5,
        )
    )
    snapshot = build_event_value_snapshot(
        event_cluster_id=CLUSTER_ID,
        as_of_time=BASE_TIME + timedelta(minutes=20),
        values=values,
    )
    return snapshot, calculate_event_surprise(
        snapshot,
        materiality_threshold=Decimal("0.1"),
    )


def _diffusion():
    observations = (
        build_narrative_observation(
            event_cluster_id=CLUSTER_ID,
            source_id="source:p05:rumor",
            independence_group="origin:p05:rumor",
            platform="social",
            language="en",
            verified_source=False,
            kol_source=True,
            observed_at=BASE_TIME,
            available_at=BASE_TIME + timedelta(minutes=1),
            source_sha256=HASH_A,
        ),
        build_narrative_observation(
            event_cluster_id=CLUSTER_ID,
            source_id="source:p05:official",
            independence_group="origin:p05:official",
            platform="official-web",
            language="zh",
            verified_source=True,
            news_wire_source=True,
            observed_at=BASE_TIME + timedelta(minutes=5),
            available_at=BASE_TIME + timedelta(minutes=6),
            source_sha256=HASH_B,
        ),
    )
    return build_narrative_diffusion(
        event_cluster_id=CLUSTER_ID,
        observations=observations,
        as_of_time=AS_OF_TIME,
        window_hours=Decimal("0.5"),
        price_response_at=BASE_TIME + timedelta(minutes=8),
        price_response_available_at=BASE_TIME + timedelta(minutes=9),
        price_response_source_sha256=HASH_A,
        volume_response_at=BASE_TIME + timedelta(minutes=9),
        volume_response_available_at=BASE_TIME + timedelta(minutes=10),
        volume_response_source_sha256=HASH_B,
    )


def _reflection(
    strength: Decimal,
    *,
    omit: MarketReflectionMetric | None = None,
):
    metrics = tuple(
        build_market_reflection_metric(
            event_cluster_id=CLUSTER_ID,
            metric=metric,
            reflection_strength=strength,
            observed_at=BASE_TIME + timedelta(minutes=8),
            available_at=BASE_TIME + timedelta(minutes=9),
            source_id=f"market:p05:{metric.value.casefold()}",
            source_sha256=HASH_A,
        )
        for metric in DEFAULT_MARKET_REFLECTION_POLICY.required_metrics
        if metric is not omit
    )
    return calculate_market_reflection(
        event_cluster_id=CLUSTER_ID,
        metrics=metrics,
        as_of_time=AS_OF_TIME,
    )


def _event(
    *,
    status: EventClusterStatus,
    truth_state: TruthState,
    reflection_strength: Decimal,
    omit: MarketReflectionMetric | None = None,
) -> CanonicalEvent:
    values, surprise = _value_and_surprise()
    return build_canonical_event(
        cluster=_cluster(status),
        truth_assessment=_truth(truth_state),
        narrative_diffusion=_diffusion(),
        market_reflection=_reflection(reflection_strength, omit=omit),
        event_value_snapshot=values,
        event_surprise=surprise,
        as_of_time=AS_OF_TIME,
        jurisdiction="US",
        affected_assets=("asset:BTC",),
        novelty=Decimal("0.8"),
        severity=Decimal("0.6"),
        persistence=Decimal("0.5"),
        transmission_channels=("liquidity", "rates"),
    )


def _content(*, native_id: str, text: str, observed_minutes: int) -> CollectedContent:
    return CollectedContent(
        source=SourceKind.GITHUB,
        provider_id=ProviderId("github_public"),
        native_id=native_id,
        source_native_id="official/project",
        display_name="official/project",
        ownership_group="official/project",
        independence_group="official/project",
        verified_source=True,
        content_type=ContentType.ANNOUNCEMENT,
        canonical_url=f"https://github.com/official/project/releases/{native_id}",
        text=text,
        language="en",
        published_time=BASE_TIME,
        observed_time=BASE_TIME + timedelta(minutes=observed_minutes),
        revision=1,
        checkpoint=f"{native_id}:1",
    )


def build_payload() -> dict[str, object]:
    low_event = _event(
        status=EventClusterStatus.CONFIRMED,
        truth_state=TruthState.VERIFIED_PRIMARY,
        reflection_strength=Decimal("0.40"),
    )
    high_event = _event(
        status=EventClusterStatus.CONFIRMED,
        truth_state=TruthState.VERIFIED_PRIMARY,
        reflection_strength=Decimal("0.90"),
    )
    incomplete_event = _event(
        status=EventClusterStatus.CONFIRMED,
        truth_state=TruthState.VERIFIED_PRIMARY,
        reflection_strength=Decimal("0.10"),
        omit=MarketReflectionMetric.MARKET_DEPTH_CHANGE,
    )
    rumor_event = _event(
        status=EventClusterStatus.RUMOR,
        truth_state=TruthState.RUMOR,
        reflection_strength=Decimal("0.10"),
    )
    low_gate = build_event_directional_gate(event=low_event, as_of_time=AS_OF_TIME)
    high_gate = build_event_directional_gate(event=high_event, as_of_time=AS_OF_TIME)
    incomplete_gate = build_event_directional_gate(
        event=incomplete_event,
        as_of_time=AS_OF_TIME,
    )
    rumor_gate = build_event_directional_gate(event=rumor_event, as_of_time=AS_OF_TIME)

    rumor_content = _content(
        native_id="rumor",
        text="Unconfirmed rumor: Bitcoin protocol release",
        observed_minutes=1,
    )
    future_confirmation = _content(
        native_id="confirmation",
        text="Bitcoin protocol release approved",
        observed_minutes=40,
    )
    pit_decision_time = BASE_TIME + timedelta(minutes=20)
    pit_result = run_pipeline(
        (rumor_content, future_confirmation),
        as_of_time=pit_decision_time,
    )
    pit_cluster = pit_result.event_clusters[0]
    actual_value = low_event.actual_value
    expected_value = low_event.expected_value
    whisper_value = low_event.whisper_value
    if actual_value is None or expected_value is None or whisper_value is None:
        raise RuntimeError("V5-P05 fixture must include actual, consensus, and whisper values")

    checks: dict[str, bool] = {
        "actual_consensus_whisper_are_pit_bound": (
            actual_value == Decimal("3.5")
            and expected_value == Decimal("3.0")
            and whisper_value == Decimal("3.2")
        ),
        "surprise_is_recomputed_from_actual_minus_consensus": (
            low_event.surprise_value == actual_value - expected_value == Decimal("0.5")
        ),
        "narrative_diffusion_preserves_first_and_first_verified_sources": (
            low_event.narrative_diffusion.first_source_id == "source:p05:rumor"
            and low_event.narrative_diffusion.first_verified_source_id == "source:p05:official"
        ),
        "low_price_in_is_research_candidate_only": (
            low_gate.directional_candidate_allowed
            and low_gate.action == "RESEARCH_PROPOSAL_ONLY"
            and not low_gate.order_submission_allowed
        ),
        "high_price_in_blocks_directional_candidate": (
            not high_gate.directional_candidate_allowed
            and "EVENT_ALREADY_PRICED" in high_gate.reason_codes
        ),
        "missing_reflection_metric_fails_closed": (
            incomplete_event.market_reflection.quality_state is QualityState.DEGRADED
            and incomplete_event.market_reflection.market_reflection_score is None
            and not incomplete_gate.directional_candidate_allowed
            and "MARKET_REFLECTION_INSUFFICIENT" in incomplete_gate.reason_codes
        ),
        "rumor_is_separate_and_directionally_blocked": (
            rumor_event.event_stage is EventClusterStatus.RUMOR
            and not rumor_gate.directional_candidate_allowed
            and "EVENT_NOT_CONFIRMED" in rumor_gate.reason_codes
        ),
        "future_official_confirmation_is_not_visible_in_past": (
            len(pit_result.claims) == 1
            and pit_cluster.status is EventClusterStatus.RUMOR
            and not pit_cluster.official_confirmation_ids
            and pit_cluster.last_updated_time == rumor_content.observed_time
        ),
        "all_outputs_remain_development_and_non_trading": all(
            not gate.order_submission_allowed
            for gate in (low_gate, high_gate, incomplete_gate, rumor_gate)
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"V5-P05 evidence checks failed: {checks}")

    return {
        "schema_version": "1.0.0",
        "phase": "V5-P05",
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "real_world_forecast_accuracy_claimed": False,
        "live_trading_locked": True,
        "order_submission_enabled": False,
        "as_of_time": AS_OF_TIME.isoformat().replace("+00:00", "Z"),
        "market_reflection_policy": DEFAULT_MARKET_REFLECTION_POLICY.model_dump(mode="json"),
        "canonical_event": low_event.model_dump(mode="json"),
        "event_value_snapshot": low_event.event_value_snapshot.model_dump(mode="json")
        if low_event.event_value_snapshot is not None
        else None,
        "event_surprise": low_event.event_surprise.model_dump(mode="json")
        if low_event.event_surprise is not None
        else None,
        "narrative_diffusion": low_event.narrative_diffusion.model_dump(mode="json"),
        "market_reflection_scenarios": {
            "low": low_event.market_reflection.model_dump(mode="json"),
            "high": high_event.market_reflection.model_dump(mode="json"),
            "incomplete": incomplete_event.market_reflection.model_dump(mode="json"),
        },
        "directional_gates": {
            "low": low_gate.model_dump(mode="json"),
            "high": high_gate.model_dump(mode="json"),
            "incomplete": incomplete_gate.model_dump(mode="json"),
            "rumor": rumor_gate.model_dump(mode="json"),
        },
        "pipeline_pit": {
            "decision_time": pit_decision_time.isoformat().replace("+00:00", "Z"),
            "input_observed_times": {
                "rumor": rumor_content.observed_time.isoformat().replace("+00:00", "Z"),
                "future_confirmation": future_confirmation.observed_time.isoformat().replace(
                    "+00:00", "Z"
                ),
            },
            "visible_claim_count": len(pit_result.claims),
            "cluster": {
                "event_type": pit_cluster.event_type,
                "status": pit_cluster.status.value,
                "first_observed_time": pit_cluster.first_observed_time.isoformat().replace(
                    "+00:00", "Z"
                ),
                "last_updated_time": pit_cluster.last_updated_time.isoformat().replace(
                    "+00:00", "Z"
                ),
                "official_confirmation_count": len(pit_cluster.official_confirmation_ids),
            },
        },
        "checks": checks,
        "acceptance_traceability": {
            "high_price_in_confirmed_event_is_not_directional_by_default": [
                "tests/v5_p05/test_canonical_events.py::test_market_reflection_is_fail_closed_when_incomplete_or_high",
                "tests/v5_p05/test_canonical_events.py::test_high_price_in_and_legacy_paths_cannot_emit_directional_impact",
                "tests/v5_p05/test_canonical_events.py::test_fusion_honors_the_same_directional_gate",
                "tests/v5_p05/test_canonical_events.py::test_self_consistent_forged_gate_cannot_override_event_reflection_policy",
                "tests/v5_p05/test_canonical_events.py::test_fusion_rejects_gate_timestamp_before_canonical_event_availability",
            ],
            "rumor_and_confirmed_are_separate": [
                "tests/v5_p05/test_canonical_events.py::test_rumor_never_becomes_directional_candidate",
                "tests/v5_p05/test_pipeline_pit.py::test_future_official_content_cannot_confirm_past_rumor",
            ],
            "all_fields_are_point_in_time": [
                "tests/v5_p05/test_canonical_events.py::test_actual_expected_whisper_surprise_is_bound_and_recomputed",
                "tests/v5_p05/test_canonical_events.py::test_future_surprise_timestamp_cannot_enter_canonical_event",
                "tests/v5_p05/test_canonical_events.py::test_narrative_diffusion_is_pit_and_tracks_first_verified_source",
                "tests/v5_p05/test_pipeline_pit.py::test_pipeline_selects_latest_revision_visible_at_decision_time",
                "tests/v5_p05/test_pipeline_pit.py::test_duplicate_or_time_regressing_revisions_fail_closed",
                "tests/v5_p05/test_pipeline_pit.py::test_collected_content_rejects_future_modification_knowledge",
                "tests/v5_p05/test_pipeline_pit.py::test_revision_history_rejects_publication_and_lifecycle_regressions",
            ],
        },
        "limitations": [
            "All values, truth assessments, and market observations are deterministic DEVELOPMENT fixtures.",
            "The weighted MarketReflectionScore is a versioned bootstrap heuristic, not a calibrated probability.",
            "A low-reflection confirmed event is only a research candidate; no order path is enabled.",
            "No causal effect, market forecast accuracy, backtest return, or trading edge is claimed.",
            "Real PIT public event and market data validation remains required in later phases.",
            "Provider revision numbers may be sparse when local collection begins after earlier edits; observed histories still enforce monotonic time and lifecycle state.",
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
            raise SystemExit(f"V5-P05 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P05 event-context evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P05 event-context evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
