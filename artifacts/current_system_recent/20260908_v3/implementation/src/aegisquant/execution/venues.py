"""Explicitly non-sending execution contracts for secondary venues."""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import Fill, VenueOrder
from aegisquant.domain.identifiers import VenueId
from aegisquant.execution.accounts import AccountStreamEvent, VenueAccountSnapshot
from aegisquant.execution.commands import AmendOrderCommand, CancelOrderCommand, SubmitOrderCommand
from aegisquant.execution.models import (
    AdapterHealth,
    AdapterHealthState,
    AmendResult,
    CancelResult,
    ExecutionEnvironment,
    SubmitResult,
)
from aegisquant.execution.rules import InstrumentRuleSnapshot


class VenueContract(DomainModel):
    venue_id: VenueId
    environment: ExecutionEnvironment
    market_rules_supported: bool
    account_snapshot_supported: bool
    send_enabled: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)


class ContractOnlySendBlocked(RuntimeError):
    pass


class ContractOnlyExecutionAdapter:
    """Queryable contract fixture whose mutation methods always fail closed."""

    environment = ExecutionEnvironment.SIMULATED

    def __init__(
        self,
        *,
        venue_id: VenueId,
        rules: tuple[InstrumentRuleSnapshot, ...],
        account: VenueAccountSnapshot,
    ) -> None:
        if account.venue_id != venue_id or any(rule.venue_id != venue_id for rule in rules):
            raise ValueError("contract-only adapter fixture venue mismatch")
        self.venue_id = venue_id
        self._rules = rules
        self._account = account

    async def instruments(self) -> tuple[InstrumentRuleSnapshot, ...]:
        return self._rules

    async def account_snapshot(self) -> VenueAccountSnapshot:
        return self._account

    async def open_orders(self) -> tuple[VenueOrder, ...]:
        return self._account.open_orders

    async def recent_orders(self) -> tuple[VenueOrder, ...]:
        return self._account.open_orders

    async def recent_fills(self) -> tuple[Fill, ...]:
        return ()

    async def submit(self, command: SubmitOrderCommand) -> SubmitResult:
        del command
        raise ContractOnlySendBlocked("AQ-EXEC-CONTRACT-ONLY-SUBMIT-BLOCKED")

    async def cancel(self, command: CancelOrderCommand) -> CancelResult:
        del command
        raise ContractOnlySendBlocked("AQ-EXEC-CONTRACT-ONLY-CANCEL-BLOCKED")

    async def amend(self, command: AmendOrderCommand) -> AmendResult:
        del command
        raise ContractOnlySendBlocked("AQ-EXEC-CONTRACT-ONLY-AMEND-BLOCKED")

    def stream_account(self) -> AsyncIterator[AccountStreamEvent]:
        async def iterator() -> AsyncIterator[AccountStreamEvent]:
            if False:
                yield  # pragma: no cover - declares an empty async iterator

        return iterator()

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            venue_id=self.venue_id,
            environment=self.environment,
            state=AdapterHealthState.CONTRACT_ONLY,
            checked_at=self._account.captured_at,
            sequence_healthy=True,
            reconciliation_required=False,
            reason_codes=("AQ-EXEC-CONTRACT-ONLY-NO-SEND",),
        )

    def contract(self) -> VenueContract:
        return VenueContract(
            venue_id=self.venue_id,
            environment=self.environment,
            market_rules_supported=True,
            account_snapshot_supported=True,
            send_enabled=False,
            reason_codes=("AQ-EXEC-CONTRACT-ONLY-NO-SEND",),
        )


SECONDARY_VENUE_IDS = (
    VenueId("OKX-TEST-CONTRACT"),
    VenueId("BYBIT-TEST-CONTRACT"),
    VenueId("DERIBIT-TEST-CONTRACT"),
)
