"""Fail-closed paid-provider bake-off and procurement contracts."""

from aegisquant.research.provider_bakeoff.catalog import load_candidate_catalog, load_trial_plans
from aegisquant.research.provider_bakeoff.evaluation import (
    calculate_news_metrics,
    enforce_primary_source_limit,
    evaluate_candidate,
    fallback_to_free_baseline,
    require_official_trading_fact,
)

__all__ = [
    "calculate_news_metrics",
    "enforce_primary_source_limit",
    "evaluate_candidate",
    "fallback_to_free_baseline",
    "load_candidate_catalog",
    "load_trial_plans",
    "require_official_trading_fact",
]
