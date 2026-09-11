"""Shared P12 execution enums and immutable result contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import ClientOrderId, VenueId, VenueOrderId
from aegisquant.domain.time import UtcDateTime


class ExecutionEnvironment(StrEnum):
    """P12 deliberately has no Live member."""

    SIMULATED = "SIMULATED"
    TESTNET = "TESTNET"


class CredentialReferenceState(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    AWAITING_CREDENTIAL_REFERENCE = "AWAITING_CREDENTIAL_REFERENCE"
    REFERENCE_CONFIGURED = "REFERENCE_CONFIGURED"


class AdapterHealthState(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    CONTRACT_ONLY = "CONTRACT_ONLY"
    BLOCKED = "BLOCKED"


class AdapterHealth(DomainModel):
    venue_id: VenueId
    environment: ExecutionEnvironment
    state: AdapterHealthState
    checked_at: UtcDateTime
    sequence_healthy: bool
    reconciliation_required: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)


class SubmitDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class SubmitResult(DomainModel):
    client_order_id: ClientOrderId
    venue_order_id: VenueOrderId | None = None
    disposition: SubmitDisposition
    occurred_at: UtcDateTime
    reason_code: str
    economic_order_created: bool

    @model_validator(mode="after")
    def require_venue_order_for_acceptance(self) -> SubmitResult:
        if (
            self.disposition
            in {
                SubmitDisposition.ACCEPTED,
                SubmitDisposition.IDEMPOTENT_REPLAY,
            }
            and self.venue_order_id is None
        ):
            raise ValueError("accepted submit result requires venue order evidence")
        if self.disposition is SubmitDisposition.IDEMPOTENT_REPLAY and self.economic_order_created:
            raise ValueError("idempotent replay cannot create another economic order")
        return self


class CancelDisposition(StrEnum):
    CANCELED = "CANCELED"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class CancelResult(DomainModel):
    client_order_id: ClientOrderId
    disposition: CancelDisposition
    occurred_at: UtcDateTime
    reason_code: str


class AmendDisposition(StrEnum):
    AMENDED = "AMENDED"
    REJECTED = "REJECTED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class AmendResult(DomainModel):
    client_order_id: ClientOrderId
    disposition: AmendDisposition
    occurred_at: UtcDateTime
    reason_code: str


class TestnetCapabilityState(StrEnum):
    SIMULATED_VERIFIED = "SIMULATED_VERIFIED"
    AWAITING_CREDENTIAL_REFERENCE = "AWAITING_CREDENTIAL_REFERENCE"
    TESTNET_VERIFIED = "TESTNET_VERIFIED"


class TestnetCapability(DomainModel):
    venue_id: VenueId
    state: TestnetCapabilityState
    credential_reference_state: CredentialReferenceState
    credential_reference_name: str | None = None
    network_requests_performed: int = Field(ge=0)
    real_account_access_performed: bool
    live_domain_available: bool
    live_credentials_available: bool
    withdrawal_capability: bool

    @model_validator(mode="after")
    def fail_closed_without_reference(self) -> TestnetCapability:
        configured = (
            self.credential_reference_state is CredentialReferenceState.REFERENCE_CONFIGURED
        )
        if configured != (self.credential_reference_name is not None):
            raise ValueError("credential reference name must match configured state")
        if self.state is TestnetCapabilityState.TESTNET_VERIFIED and not configured:
            raise ValueError("real Testnet verification requires a configured secret reference")
        if (
            self.real_account_access_performed
            or self.live_domain_available
            or self.live_credentials_available
            or self.withdrawal_capability
        ):
            raise ValueError("P12 capability cannot expose real or Live account access")
        return self
