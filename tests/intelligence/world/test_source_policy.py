from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisquant.data.provider_registry import ProviderRegistry, SourcePolicyRegistry
from aegisquant.domain.errors import DomainError
from aegisquant.domain.identifiers import ProviderId, SourcePolicyId
from aegisquant.domain.intelligence import RightsState
from aegisquant.intelligence.world.models import (
    SourceUsePolicy,
    UsePermission,
    WorldSource,
)
from aegisquant.intelligence.world.sources import default_social_catalog, official_source_catalog

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_unknown_rights_fail_closed_for_sensitive_uses() -> None:
    with pytest.raises(ValidationError, match="unknown or prohibited rights"):
        SourceUsePolicy(
            policy_id="unknown-source",
            source=WorldSource.X,
            rights_state=RightsState.UNKNOWN,
            raw_local_storage=UsePermission.LOCAL_ONLY,
            cloud_inference=UsePermission.ALLOWED,
            embedding=UsePermission.PROHIBITED,
            training=UsePermission.PROHIBITED,
            fine_tuning=UsePermission.PROHIBITED,
            display=UsePermission.PROHIBITED,
            export=UsePermission.PROHIBITED,
            deletion_sync_required=True,
            revision_sync_required=True,
            retention_days=1,
            approved_scopes=(),
            checked_at=NOW,
        )


def test_policy_distinguishes_local_and_cloud_use() -> None:
    policy = SourceUsePolicy(
        policy_id="limited-local",
        source=WorldSource.BLUESKY,
        rights_state=RightsState.LIMITED,
        raw_local_storage=UsePermission.LOCAL_ONLY,
        cloud_inference=UsePermission.PROHIBITED,
        embedding=UsePermission.LOCAL_ONLY,
        training=UsePermission.PROHIBITED,
        fine_tuning=UsePermission.PROHIBITED,
        display=UsePermission.PROHIBITED,
        export=UsePermission.PROHIBITED,
        deletion_sync_required=True,
        revision_sync_required=True,
        retention_days=30,
        approved_scopes=("public_post_metadata",),
        checked_at=NOW,
    )
    assert policy.allows("embedding") is True
    assert policy.allows("embedding", cloud=True) is False
    assert policy.allows("cloud_inference") is False
    with pytest.raises(ValueError, match="unknown source use"):
        policy.allows("execute")


def test_reddit_and_discord_are_disabled_by_default() -> None:
    catalog = {item.source: item for item in default_social_catalog()}
    assert catalog[WorldSource.REDDIT].runtime_state.value == "DISABLED_BY_POLICY"
    assert catalog[WorldSource.DISCORD].approved_capabilities == ()
    assert catalog[WorldSource.X].runtime_state.value == "AWAITING_CREDENTIALS"
    assert catalog[WorldSource.BLUESKY].runtime_state.value == "READY"


def test_official_catalog_covers_required_authority_classes() -> None:
    catalog = official_source_catalog(checked_at=NOW)
    authority_types = {item.authority_type for item in catalog}
    assert {
        "central_bank",
        "regulator",
        "court",
        "exchange",
        "project",
        "etf_issuer",
    } <= authority_types
    assert all(item.credentials_required is False for item in catalog)


def test_machine_registry_enables_public_sources_and_blocks_unconfigured_sources(
    project_root: Path,
) -> None:
    providers = ProviderRegistry.from_yaml(project_root / "data/catalogs/provider_registry.yaml")
    policies = SourcePolicyRegistry.from_yaml(
        project_root / "data/catalogs/source_policy_registry.yaml"
    )
    public_cases = (
        ("coin_metrics_community", "coin_metrics_community_v1"),
        ("defillama_public", "defillama_public_v1"),
        ("official_web_catalog", "official_web_catalog_v1"),
    )
    for provider_id, policy_id in public_cases:
        policy = policies.get(SourcePolicyId(policy_id))
        assert (
            providers.require_collection(ProviderId(provider_id), policy).access_state.value
            == "ready"
        )
    with pytest.raises(DomainError, match="AWAITING_CREDENTIALS"):
        providers.require_collection(
            ProviderId("fred_alfred"),
            policies.get(SourcePolicyId("fred_alfred_restricted_v1")),
        )
    with pytest.raises(DomainError, match="DISABLED"):
        providers.require_collection(
            ProviderId("reddit_disabled"),
            policies.get(SourcePolicyId("reddit_unknown_deny_v1")),
        )
