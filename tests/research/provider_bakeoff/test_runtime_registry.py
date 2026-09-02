"""Paid candidates stay outside the approved runtime Provider Registry."""

from pathlib import Path

from aegisquant.data.models import ProviderStatus
from aegisquant.data.provider_registry import ProviderRegistry
from aegisquant.research.provider_bakeoff.catalog import load_candidate_catalog


def test_no_p17_paid_candidate_is_approved_or_required_by_runtime(project_root: Path) -> None:
    candidates = load_candidate_catalog(project_root / "configs/provider_bakeoff/candidates.json")
    runtime = ProviderRegistry.from_yaml(project_root / "data/catalogs/provider_registry.yaml")
    paid_ids = {str(item.provider_id) for item in candidates.candidates}
    registered = {
        str(item.provider_id): item.status
        for item in runtime.document.providers
        if str(item.provider_id) in paid_ids
    }
    assert registered == {}
    assert all(item.status is not ProviderStatus.APPROVED for item in candidates.candidates)
