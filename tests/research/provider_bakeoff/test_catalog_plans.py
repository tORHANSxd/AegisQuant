"""Candidate catalog and fail-closed trial-plan contracts."""

from decimal import Decimal
from pathlib import Path

from aegisquant.data.models import ProviderStatus
from aegisquant.research.provider_bakeoff.catalog import (
    load_candidate_catalog,
    load_trial_plans,
)
from aegisquant.research.provider_bakeoff.models import EvidenceState


def test_real_candidates_are_desk_review_only_and_not_runtime_dependencies(
    project_root: Path,
) -> None:
    catalog = load_candidate_catalog(project_root / "configs/provider_bakeoff/candidates.json")
    assert len(catalog.candidates) == 13
    assert {item.comparison_group for item in catalog.candidates} == {
        "market_tick",
        "derivatives_aggregate",
        "onchain_metrics",
        "cross_asset_cme",
        "news_personal",
        "news_institutional",
        "x_social",
    }
    assert all(item.status is ProviderStatus.CANDIDATE for item in catalog.candidates)
    assert all(
        item.evidence_state is not EvidenceState.TRIAL_COMPLETE for item in catalog.candidates
    )
    assert all(not item.runtime_dependency for item in catalog.candidates)
    assert all(not item.official_fact_authority for item in catalog.candidates)
    assert all(not item.license_review_complete for item in catalog.candidates)


def test_trial_requests_define_equal_budget_and_zero_authorized_spend(
    project_root: Path,
) -> None:
    document = load_trial_plans(project_root / "configs/provider_bakeoff/trial_plans.json")
    assert len(document.plans) == 7
    assert all(plan.equal_research_budget for plan in document.plans)
    assert all(not plan.activated for plan in document.plans)
    assert all(not plan.budget.user_budget_approved for plan in document.plans)
    assert all(plan.budget.approved_max_cost_usd == Decimal("0") for plan in document.plans)
    assert all(not plan.budget.overage_allowed for plan in document.plans)
    assert all(not plan.budget.automatic_renewal_allowed for plan in document.plans)
    assert sum(plan.budget.max_calls for plan in document.plans) == 75000


def test_databento_is_explicitly_conditional_and_has_zero_calls(project_root: Path) -> None:
    catalog = load_candidate_catalog(project_root / "configs/provider_bakeoff/candidates.json")
    plans = load_trial_plans(project_root / "configs/provider_bakeoff/trial_plans.json")
    databento = next(item for item in catalog.candidates if str(item.provider_id) == "databento")
    plan = next(item for item in plans.plans if item.trial_id == "conditional_databento_cme")
    assert databento.condition == plan.condition
    assert plan.budget.max_calls == 0
    assert plan.activated is False
