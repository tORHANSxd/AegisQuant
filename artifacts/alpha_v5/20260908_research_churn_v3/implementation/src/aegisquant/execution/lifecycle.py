"""Fail-closed execution startup, quiesce, and crash-recovery lifecycle."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from aegisquant.domain.base import DomainModel
from aegisquant.execution.accounts import AccountSynchronizer
from aegisquant.execution.adapter import ExecutionAdapter
from aegisquant.execution.commands import SubmitOrderCommand
from aegisquant.execution.models import AdapterHealthState, SubmitDisposition, SubmitResult


class ExecutionEngineState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RECONCILING = "RECONCILING"
    RUNNING = "RUNNING"
    QUIESCING = "QUIESCING"
    HALTED = "HALTED"


class LifecycleOutcome(DomainModel):
    state: ExecutionEngineState
    new_submissions_allowed: bool
    unresolved_client_order_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)


class ExecutionLifecycle:
    def __init__(self, *, adapter: ExecutionAdapter) -> None:
        self.adapter = adapter
        self.state = ExecutionEngineState.STOPPED
        self.synchronizer = AccountSynchronizer(venue_id=adapter.venue_id)
        self._unknown_submits: set[str] = set()

    async def start(
        self,
        *,
        local_open_order_ids: tuple[str, ...],
        local_fill_ids: tuple[str, ...] = (),
    ) -> LifecycleOutcome:
        self.state = ExecutionEngineState.STARTING
        health = await self.adapter.health()
        if health.state is not AdapterHealthState.READY:
            self.state = ExecutionEngineState.HALTED
            return self._outcome("AQ-EXEC-START-ADAPTER-NOT-READY")
        self.state = ExecutionEngineState.RECONCILING
        snapshot = await self.adapter.account_snapshot()
        reconciled = self.synchronizer.reconcile(
            snapshot,
            local_open_order_ids=local_open_order_ids,
            local_fill_ids=local_fill_ids,
        )
        unresolved = {
            *reconciled.unknown_local_order_ids,
            *reconciled.unknown_venue_order_ids,
            *reconciled.unknown_local_fill_ids,
            *reconciled.unknown_venue_fill_ids,
        }
        if unresolved:
            self._unknown_submits.update(unresolved)
            self.state = ExecutionEngineState.HALTED
            return self._outcome("AQ-EXEC-START-ORDER-RECONCILIATION-MISMATCH")
        self.state = ExecutionEngineState.RUNNING
        return self._outcome("AQ-EXEC-START-RECONCILED")

    async def submit(self, command: SubmitOrderCommand) -> SubmitResult:
        if self.state is not ExecutionEngineState.RUNNING:
            raise RuntimeError("AQ-EXEC-NEW-SUBMISSION-BLOCKED")
        client_id = str(command.command.client_order_id)
        if client_id in self._unknown_submits:
            raise RuntimeError("AQ-EXEC-UNKNOWN-ORDER-MUST-RECOVER")
        result = await self.adapter.submit(command)
        if result.disposition is SubmitDisposition.UNKNOWN:
            self._unknown_submits.add(client_id)
        return result

    def mark_recovered(self, *, client_order_id: str) -> None:
        self._unknown_submits.discard(client_order_id)

    def quiesce(self) -> LifecycleOutcome:
        if self.state not in {
            ExecutionEngineState.RUNNING,
            ExecutionEngineState.HALTED,
        }:
            raise RuntimeError("AQ-EXEC-QUIESCE-ILLEGAL-STATE")
        self.state = ExecutionEngineState.QUIESCING
        return self._outcome("AQ-EXEC-QUIESCE-NO-NEW-SUBMISSIONS")

    def stop(self) -> LifecycleOutcome:
        if self.state is not ExecutionEngineState.QUIESCING:
            raise RuntimeError("AQ-EXEC-STOP-REQUIRES-QUIESCE")
        self.state = ExecutionEngineState.STOPPED
        self.synchronizer.disconnected()
        return self._outcome("AQ-EXEC-STOPPED")

    async def crash_recover(
        self,
        *,
        local_open_order_ids: tuple[str, ...],
        local_fill_ids: tuple[str, ...] = (),
    ) -> LifecycleOutcome:
        self.state = ExecutionEngineState.STOPPED
        return await self.start(
            local_open_order_ids=local_open_order_ids,
            local_fill_ids=local_fill_ids,
        )

    def _outcome(self, reason: str) -> LifecycleOutcome:
        return LifecycleOutcome(
            state=self.state,
            new_submissions_allowed=self.state is ExecutionEngineState.RUNNING,
            unresolved_client_order_ids=tuple(sorted(self._unknown_submits)),
            reason_codes=(reason,),
        )
