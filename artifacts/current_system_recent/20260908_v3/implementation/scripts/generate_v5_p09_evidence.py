"""Generate deterministic V5-P09 forecast-governance evidence."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from aegisquant.data.hashing import canonical_sha256
from aegisquant.research.forecasting import (
    AdaptiveConformalReport,
    ForecastGovernanceReport,
    MetaReasonerRecommendation,
    StatisticalWeightProposal,
    WeightEvidenceSource,
    build_forecast_governance_report,
    route_dynamic_stacking,
)
from tests.v5_p09.helpers import (
    NOW,
    conformal_report,
    coverage_observations,
    coverage_window,
    disagreement_report,
    governance_report,
    meta_recommendation,
    reasoning_context,
    route_decision,
    routing_snapshot,
    signal_snapshot,
    skeptic_assessment,
    stacking_policy,
    weight_proposal,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "v5" / "P09" / "FORECAST_GOVERNANCE_EVIDENCE.json"


def _rejected(operation: Callable[[], object], expected_code: str | None = None) -> bool:
    try:
        operation()
    except (TypeError, ValueError) as error:
        return expected_code is None or expected_code in str(error)
    return False


def _forged_recomputed_payload(
    model: AdaptiveConformalReport | ForecastGovernanceReport,
    field: str,
    value: object,
) -> dict[str, object]:
    payload = model.model_dump(mode="json")
    payload[field] = value
    hash_field = "report_sha256"
    payload[hash_field] = canonical_sha256(
        {key: item for key, item in payload.items() if key != hash_field}
    )
    return payload


def _governance_has_no_execution_import() -> bool:
    source = (ROOT / "src/aegisquant/research/forecasting/governance.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    return not any(module.startswith("aegisquant.execution") for module in imported_modules)


def build_payload() -> dict[str, object]:
    healthy = governance_report()
    high_disagreement = governance_report(
        disagreement=disagreement_report(
            snapshot=signal_snapshot(returns=(Decimal("-0.04"), Decimal("0.05")))
        )
    )
    ood = governance_report(route=route_decision(snapshot=routing_snapshot(ood_score=Decimal("5"))))
    calibration_drift = governance_report(
        calibration=conformal_report(
            window=coverage_window(observations=coverage_observations(realized=(Decimal("1"),) * 5))
        )
    )
    skeptic_block = governance_report(skeptic_blocks=True)
    meta_abstain = governance_report(recommend_abstain=True)

    context = healthy.context
    shared_prompt = healthy.meta_reasoner.prompt_sha256
    forged_meta = healthy.meta_reasoner.model_dump(mode="json")
    forged_meta["action"] = "PLACE_ORDER"
    forged_holdout = healthy.regime_route.proposal.model_dump(mode="json")
    forged_holdout["final_holdout_used"] = True
    future_proposal = weight_proposal(available_at=NOW + timedelta(seconds=1))
    high_disagreement_only = disagreement_report(
        snapshot=signal_snapshot(returns=(Decimal("-0.04"), Decimal("0.05")))
    )
    wrong_context = reasoning_context(
        disagreement=high_disagreement_only,
        route=healthy.regime_route,
        calibration=healthy.calibration,
    )

    negative_controls = {
        "llm_order_action_rejected": _rejected(
            lambda: MetaReasonerRecommendation.model_validate_json(json.dumps(forged_meta))
        ),
        "skeptic_shared_identity_rejected": _rejected(
            lambda: reasoning_context(
                meta_reasoner_prompt_sha256=shared_prompt,
                skeptic_prompt_sha256=shared_prompt,
            ),
            "SKEPTIC-NOT-INDEPENDENT",
        ),
        "unbound_reviewer_revision_rejected": _rejected(
            lambda: build_forecast_governance_report(
                context=context,
                meta_reasoner=healthy.meta_reasoner,
                skeptic=skeptic_assessment(
                    context,
                    model_revision_sha256=canonical_sha256({"fixture": "unapproved-skeptic-model"}),
                ),
                disagreement=healthy.disagreement,
                regime_route=healthy.regime_route,
                calibration=healthy.calibration,
            ),
            "REVIEWER-BINDING-MISMATCH",
        ),
        "future_weight_proposal_rejected": _rejected(
            lambda: route_dynamic_stacking(
                snapshot=routing_snapshot(),
                proposal=future_proposal,
                policy=stacking_policy(),
            ),
            "LOOKAHEAD",
        ),
        "final_holdout_weight_training_rejected": _rejected(
            lambda: StatisticalWeightProposal.model_validate_json(json.dumps(forged_holdout))
        ),
        "self_reported_coverage_recalculation_rejected": _rejected(
            lambda: AdaptiveConformalReport.model_validate_json(
                json.dumps(
                    _forged_recomputed_payload(
                        healthy.calibration,
                        "observed_coverage",
                        "1",
                    )
                )
            ),
            "COVERAGE-RECOMPUTATION-MISMATCH",
        ),
        "forecast_context_splice_rejected": _rejected(
            lambda: build_forecast_governance_report(
                context=wrong_context,
                meta_reasoner=meta_recommendation(wrong_context),
                skeptic=skeptic_assessment(wrong_context),
                disagreement=healthy.disagreement,
                regime_route=healthy.regime_route,
                calibration=healthy.calibration,
            ),
            "FORECAST-CONTEXT-SPLICE",
        ),
        "caller_abstain_override_rejected": _rejected(
            lambda: ForecastGovernanceReport.model_validate_json(
                json.dumps(
                    _forged_recomputed_payload(
                        healthy,
                        "should_abstain",
                        True,
                    )
                )
            ),
            "GOVERNANCE-RECOMPUTATION-MISMATCH",
        ),
    }

    selected = healthy.regime_route.selected_weights
    checks = {
        "meta_reasoner_and_skeptic_are_advisory_only": (
            healthy.meta_reasoner.action == "RESEARCH_RECOMMENDATION_ONLY"
            and healthy.skeptic.action == "RESEARCH_RECOMMENDATION_ONLY"
            and not healthy.meta_reasoner.order_submission_enabled
            and not healthy.skeptic.order_submission_enabled
            and _governance_has_no_execution_import()
        ),
        "skeptic_uses_independent_prompt_and_model_revision": (
            healthy.meta_reasoner.prompt_sha256 != healthy.skeptic.prompt_sha256
            and healthy.meta_reasoner.model_revision_sha256 != healthy.skeptic.model_revision_sha256
            and healthy.meta_reasoner.prompt_sha256 == healthy.context.meta_reasoner_prompt_sha256
            and healthy.meta_reasoner.model_revision_sha256
            == healthy.context.meta_reasoner_model_revision_sha256
            and healthy.skeptic.prompt_sha256 == healthy.context.skeptic_prompt_sha256
            and healthy.skeptic.model_revision_sha256
            == healthy.context.skeptic_model_revision_sha256
            and not healthy.skeptic.shared_final_prompt
        ),
        "dynamic_stacking_uses_only_statistical_evidence_and_smoothing": (
            selected is not None
            and selected.weights == {"baseline": Decimal("0.45"), "supervised": Decimal("0.55")}
            and {binding.source for binding in healthy.regime_route.proposal.evidence_bindings}
            == {
                WeightEvidenceSource.VALIDATION,
                WeightEvidenceSource.CALIBRATION,
            }
            and not healthy.regime_route.proposal.final_holdout_used
        ),
        "regime_router_is_pit_and_ood_abstains": (
            healthy.regime_route.snapshot.available_at
            <= healthy.regime_route.snapshot.decision_time
            and not healthy.regime_route.should_abstain
            and ood.should_abstain
            and "OUT_OF_DISTRIBUTION" in ood.reason_codes
        ),
        "disagreement_is_recomputed_and_abstains": (
            high_disagreement.should_abstain
            and "MODEL_DIRECTION_CONFLICT" in high_disagreement.reason_codes
            and "MODEL_DISAGREEMENT_RANGE_EXCEEDED" in high_disagreement.reason_codes
        ),
        "adaptive_distribution_aware_coverage_is_monitored": (
            healthy.calibration.observed_coverage == Decimal("0.8")
            and healthy.calibration.action.value == "NONE"
            and healthy.calibration.distribution_scale_normalized
            and healthy.calibration.recommended_scale_multiplier == Decimal("1.5")
            and not healthy.calibration.exchangeability_assumed
            and not healthy.calibration.real_world_coverage_claimed
        ),
        "calibration_drift_has_fail_closed_action": (
            calibration_drift.should_abstain
            and "CALIBRATION_ABSTAIN" in calibration_drift.reason_codes
            and "INTERVAL_UNDERCOVERAGE_CRITICAL" in calibration_drift.reason_codes
        ),
        "all_rejection_paths_propagate_to_governance": all(
            report.should_abstain
            for report in (
                high_disagreement,
                ood,
                calibration_drift,
                skeptic_block,
                meta_abstain,
            )
        ),
        "development_evidence_cannot_promote_or_order": (
            not healthy.alpha_promotion_eligible
            and not healthy.final_holdout_opened
            and not healthy.order_submission_enabled
            and healthy.live_trading_locked
        ),
    }
    return {
        "schema_version": "1.0.0",
        "phase": "V5-P09",
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "real_world_forecast_accuracy_claimed": False,
        "real_world_interval_coverage_claimed": False,
        "forward_evidence_present": False,
        "final_holdout_opened": False,
        "order_submission_enabled": False,
        "live_trading_locked": True,
        "checks": checks,
        "negative_controls": negative_controls,
        "healthy_governance": healthy.model_dump(mode="json"),
        "abstention_examples": {
            "disagreement": high_disagreement.model_dump(mode="json"),
            "ood": ood.model_dump(mode="json"),
            "calibration_drift": calibration_drift.model_dump(mode="json"),
            "skeptic_block": skeptic_block.model_dump(mode="json"),
            "meta_abstain": meta_abstain.model_dump(mode="json"),
        },
        "acceptance_traceability": {
            "llm_cannot_order": [
                "tests/v5_p09/test_meta_reasoner_skeptic.py::test_meta_reasoner_is_structured_advice_and_cannot_order",
                "tests/v5_p09/test_meta_reasoner_skeptic.py::test_boundary_revalidates_a_model_construct_order_capability_forgery",
            ],
            "independent_skeptic": [
                "tests/v5_p09/test_meta_reasoner_skeptic.py::test_reasoning_context_requires_distinct_reviewer_prompt_and_model_paths",
                "tests/v5_p09/test_meta_reasoner_skeptic.py::test_reasoning_context_binds_exact_reviewer_prompt_and_model_revisions",
            ],
            "disagreement_handling": [
                "tests/v5_p09/test_dynamic_stacking.py::test_disagreement_is_recomputed_and_direction_conflict_abstains",
            ],
            "ood_abstention": [
                "tests/v5_p09/test_dynamic_stacking.py::test_regime_router_abstains_on_unsafe_context",
            ],
            "calibration_drift_action": [
                "tests/v5_p09/test_adaptive_conformal.py::test_critical_undercoverage_forces_abstention",
            ],
            "interval_coverage_monitoring": [
                "tests/v5_p09/test_adaptive_conformal.py::test_distribution_aware_coverage_is_monitored_per_cell",
                "tests/v5_p09/test_adaptive_conformal.py::test_distribution_aware_interval_scales_with_forecast_uncertainty",
                "tests/v5_p09/test_adaptive_conformal.py::test_coverage_metrics_are_recomputed_instead_of_trusting_callers",
            ],
        },
        "limitations": [
            "All P09 forecasts, weights, coverage windows, and actions are deterministic DEVELOPMENT fixtures.",
            "No real public data, Final Holdout, Paper, Shadow, Testnet, or forward accuracy evidence is present.",
            "Content hashes prove payload integrity and cross-binding, not external dataset or prediction authenticity.",
            "P09 governance is not yet an execution authorization input; P10 must bind forecast, cost, portfolio, and independent risk without a bypass.",
            "A healthy fixture may avoid abstention but still cannot promote Alpha or submit an order.",
        ],
        "result": "PASS_WITH_RECORDED_NEGATIVE_RESULTS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"V5-P09 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P09 forecast governance evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P09 forecast governance evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
