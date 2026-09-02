"""OOS, cost, license, negative-result, and one-primary procurement gates."""

from decimal import Decimal

import pytest

from aegisquant.data.models import ProviderStatus
from aegisquant.domain.identifiers import ProviderId
from aegisquant.research.provider_bakeoff.evaluation import (
    enforce_primary_source_limit,
    evaluate_candidate,
)
from aegisquant.research.provider_bakeoff.models import (
    EvidenceState,
    PriceDisclosure,
    ProcurementDecision,
    ProviderCandidate,
    ProviderClass,
    ProviderDecisionRecord,
    TrialBudget,
    TrialCriteria,
    TrialMeasurement,
    TrialPlan,
)


def candidate(provider_id: str = "fixture_alpha") -> ProviderCandidate:
    return ProviderCandidate(
        provider_id=ProviderId(provider_id),
        provider_name=provider_id,
        provider_class=ProviderClass.MARKET_HISTORY,
        comparison_group="fixture_market",
        official_sources=("https://example.invalid/official-contract",),
        credentials_required=True,
        price_disclosure=PriceDisclosure.CONTACT_SALES,
        license_review_complete=True,
        evidence_state=EvidenceState.TRIAL_COMPLETE,
        status=ProviderStatus.TRIAL,
        runtime_dependency=False,
        official_fact_authority=False,
        desk_review_facts=("fixture-only contract",),
        unresolved_questions=(),
    )


def plan(*provider_ids: str) -> TrialPlan:
    return TrialPlan(
        trial_id="fixture_market_trial",
        provider_ids=tuple(ProviderId(item) for item in provider_ids),
        hypothesis="fixture-only deterministic scoring contract",
        datasets=("fixture",),
        asset_scope=("fixture",),
        equal_research_budget=True,
        official_crosscheck_sources=("fixture_official",),
        budget=TrialBudget(
            proposed_max_cost_usd=Decimal("10"),
            approved_max_cost_usd=Decimal("10"),
            user_budget_approved=True,
            approval_reference="fixture-approval",
            max_calls=100,
            max_storage_gb=Decimal("1"),
            max_duration_days=2,
        ),
        criteria=TrialCriteria(
            min_oos_observations=100,
            min_official_match_rate=Decimal("0.99"),
            min_completeness_rate=Decimal("0.99"),
            max_gap_rate=Decimal("0.01"),
            max_p95_latency_ms=Decimal("1000"),
            min_net_incremental_bps=Decimal("2"),
            max_adjusted_p_value=Decimal("0.05"),
            max_operations_minutes_per_day=Decimal("10"),
        ),
        activated=True,
        stop_conditions=("fixture stop",),
    )


def measurement(provider_id: str = "fixture_alpha") -> TrialMeasurement:
    return TrialMeasurement(
        provider_id=ProviderId(provider_id),
        oos_observations=1000,
        official_match_rate=Decimal("0.999"),
        completeness_rate=Decimal("0.999"),
        gap_rate=Decimal("0.001"),
        p95_latency_ms=Decimal("100"),
        baseline_net_bps=Decimal("10"),
        augmented_net_bps=Decimal("18"),
        incremental_data_cost_bps=Decimal("1"),
        incremental_operations_cost_bps=Decimal("1"),
        incremental_trading_cost_bps=Decimal("1"),
        adjusted_p_value=Decimal("0.01"),
        operations_minutes_per_day=Decimal("2"),
        total_cost_usd=Decimal("8"),
        license_approved=True,
        point_in_time_verified=True,
        negative_result_retained=True,
    )


def test_complete_trial_can_approve_only_after_net_costs_and_oos_gates() -> None:
    item = candidate()
    result = evaluate_candidate(
        candidate=item,
        plan=plan(str(item.provider_id)),
        measurement=measurement(),
    )
    assert result.decision is ProcurementDecision.APPROVE
    assert result.net_incremental_bps == Decimal("5")
    assert result.selected_as_primary is True


def test_budget_significance_and_negative_result_failures_are_all_retained() -> None:
    item = candidate()
    failed = measurement().model_copy(
        update={
            "adjusted_p_value": Decimal("0.2"),
            "total_cost_usd": Decimal("11"),
            "negative_result_retained": False,
        }
    )
    result = evaluate_candidate(
        candidate=item,
        plan=plan(str(item.provider_id)),
        measurement=failed,
    )
    assert result.decision is ProcurementDecision.REJECT
    assert set(result.reason_codes) >= {
        "AQ-P17-MULTIPLE-TESTING-FAILED",
        "AQ-P17-BUDGET-EXCEEDED",
        "AQ-P17-NEGATIVE-RESULT-MISSING",
    }


def test_unactivated_or_conditional_trial_never_approves() -> None:
    item = candidate()
    inactive = plan(str(item.provider_id)).model_copy(
        update={
            "activated": False,
            "budget": TrialBudget(
                proposed_max_cost_usd=Decimal("10"),
                approved_max_cost_usd=Decimal("0"),
                user_budget_approved=False,
                max_calls=100,
                max_storage_gb=Decimal("1"),
                max_duration_days=2,
            ),
        }
    )
    deferred = evaluate_candidate(candidate=item, plan=inactive, measurement=None)
    conditional = evaluate_candidate(
        candidate=item,
        plan=inactive,
        measurement=None,
        condition_satisfied=False,
    )
    assert deferred.decision is ProcurementDecision.DEFER
    assert "AQ-P17-BUDGET-NOT-APPROVED" in deferred.reason_codes
    assert conditional.decision is ProcurementDecision.NOT_APPLICABLE


def test_comparison_group_cannot_have_two_primary_sources() -> None:
    records = tuple(
        ProviderDecisionRecord(
            provider_id=ProviderId(provider_id),
            comparison_group="same_group",
            decision=ProcurementDecision.APPROVE,
            evidence_state=EvidenceState.TRIAL_COMPLETE,
            reason_codes=("AQ-P17-ALL-GATES-PASSED",),
            net_incremental_bps=Decimal("5"),
            selected_as_primary=True,
        )
        for provider_id in ("fixture_alpha", "fixture_beta")
    )
    with pytest.raises(ValueError, match="multiple primary providers"):
        enforce_primary_source_limit(records)
