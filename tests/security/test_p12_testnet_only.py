"""P12 cannot expose production domains, credentials, or send capabilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from aegisquant.execution.models import (
    CredentialReferenceState,
    ExecutionEnvironment,
)
from aegisquant.execution.models import (
    TestnetCapability as Capability,
)
from aegisquant.execution.models import (
    TestnetCapabilityState as CapabilityState,
)
from tests.p12_helpers import adapter


def test_execution_environment_has_no_production_member() -> None:
    assert {item.value for item in ExecutionEnvironment} == {"SIMULATED", "TESTNET"}


def test_absent_secret_reference_is_explicitly_blocked() -> None:
    capability = Capability(
        venue_id=adapter().venue_id,
        state=CapabilityState.AWAITING_CREDENTIAL_REFERENCE,
        credential_reference_state=CredentialReferenceState.AWAITING_CREDENTIAL_REFERENCE,
        network_requests_performed=0,
        real_account_access_performed=False,
        live_domain_available=False,
        live_credentials_available=False,
        withdrawal_capability=False,
    )
    assert capability.state is CapabilityState.AWAITING_CREDENTIAL_REFERENCE
    assert capability.network_requests_performed == 0


def test_execution_source_contains_no_exchange_endpoint_or_environment_read(
    project_root: Path,
) -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (project_root / "src/aegisquant/execution").glob("*.py")
    ).lower()
    assert "https://" not in source
    assert "os.environ" not in source
    assert "getenv(" not in source


def test_real_account_capability_is_structurally_rejected() -> None:
    with pytest.raises(ValueError, match="real or Live"):
        Capability(
            venue_id=adapter().venue_id,
            state=CapabilityState.SIMULATED_VERIFIED,
            credential_reference_state=CredentialReferenceState.NOT_REQUIRED,
            network_requests_performed=0,
            real_account_access_performed=True,
            live_domain_available=False,
            live_credentials_available=False,
            withdrawal_capability=False,
        )


def test_production_domain_capability_is_structurally_rejected() -> None:
    with pytest.raises(ValueError, match="real or Live"):
        Capability(
            venue_id=adapter().venue_id,
            state=CapabilityState.SIMULATED_VERIFIED,
            credential_reference_state=CredentialReferenceState.NOT_REQUIRED,
            network_requests_performed=0,
            real_account_access_performed=False,
            live_domain_available=True,
            live_credentials_available=False,
            withdrawal_capability=False,
        )
