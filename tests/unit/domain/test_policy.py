"""Source policy boundary decisions are executable and fail closed."""

import pytest
from pydantic import ValidationError

from aegisquant.domain.errors import DomainError
from aegisquant.domain.identifiers import ProviderId, SourcePolicyId
from aegisquant.domain.policy import (
    AccessMethod,
    CloudInferenceMode,
    DerivedStorageMode,
    DisplayMode,
    FineTuningMode,
    PiiMode,
    PolicyBoundary,
    PolicyStatus,
    RawStorageMode,
    RedistributionMode,
    SourceProcessingPolicy,
)
from tests.factories import NOW, approved_policy


def test_approved_policy_checks_every_processing_boundary() -> None:
    policy = approved_policy()
    assert policy.require(PolicyBoundary.COLLECTION).allowed
    assert policy.require(PolicyBoundary.CLOUD_INFERENCE).allowed
    assert policy.require(PolicyBoundary.DISPLAY).allowed
    deletion = policy.require(PolicyBoundary.DELETION)
    assert deletion.required_actions == ("SYNC_DELETION_AND_APPEND_TOMBSTONE",)
    with pytest.raises(DomainError) as error:
        policy.require(PolicyBoundary.TRAINING)
    assert error.value.code == "AQ-PROVIDER-BOUNDARY-DENIED"


def test_denied_policy_cannot_hide_an_allowed_capability() -> None:
    with pytest.raises(ValidationError, match="deny every"):
        SourceProcessingPolicy(
            source_policy_id=SourcePolicyId("denied-policy"),
            provider_id=ProviderId("source"),
            policy_status=PolicyStatus.DENIED,
            access_method=AccessMethod.OFFICIAL_API,
            approved_use_case="none",
            content_scope="none",
            raw_storage=RawStorageMode.PROHIBITED,
            derived_storage=DerivedStorageMode.PROHIBITED,
            cloud_inference=CloudInferenceMode.PROHIBITED,
            fine_tuning=FineTuningMode.PROHIBITED,
            display_mode=DisplayMode.NONE,
            deletion_sync_required=True,
            revision_sync_required=True,
            redistribution=RedistributionMode.PROHIBITED,
            retention_days=0,
            pii_mode=PiiMode.PROHIBITED,
            policy_checked_at=NOW,
        )
