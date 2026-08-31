"""Committed Binance public fixture helpers."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from aegisquant.data.provider_registry import ProviderRegistry, SourcePolicyRegistry
from aegisquant.domain.identifiers import SourcePolicyId
from aegisquant.domain.policy import SourceProcessingPolicy

OBSERVED = datetime(2026, 8, 31, 14, 30, tzinfo=UTC)
REQUEST_HASH = "1" * 64


def fixture(project_root: Path, relative: str) -> object:
    path = project_root / "tests/fixtures/binance" / relative
    return cast(object, json.loads(path.read_text(encoding="utf-8")))


def registries(
    project_root: Path,
) -> tuple[ProviderRegistry, SourcePolicyRegistry, SourceProcessingPolicy]:
    providers = ProviderRegistry.from_yaml(project_root / "data/catalogs/provider_registry.yaml")
    policies = SourcePolicyRegistry.from_yaml(
        project_root / "data/catalogs/source_policy_registry.yaml"
    )
    policy = policies.get(SourcePolicyId("binance_public_v1"))
    return providers, policies, policy
