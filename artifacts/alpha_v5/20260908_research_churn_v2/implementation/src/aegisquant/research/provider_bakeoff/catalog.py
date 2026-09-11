"""Strict JSON catalog loading for P17 provider candidates and trial plans."""

from pathlib import Path

from aegisquant.research.provider_bakeoff.models import (
    ProviderCandidateCatalog,
    TrialPlanDocument,
)


def load_candidate_catalog(path: Path) -> ProviderCandidateCatalog:
    return ProviderCandidateCatalog.model_validate_json(path.read_bytes())


def load_trial_plans(path: Path) -> TrialPlanDocument:
    return TrialPlanDocument.model_validate_json(path.read_bytes())
