"""Execution adapter protocol and deterministic Binance Testnet simulator."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from aegisquant.domain.execution import Fill, VenueOrder, VenueOrderStatus
from aegisquant.domain.identifiers import FillId, VenueId, VenueOrderId
from aegisquant.domain.values import Money, Price, Quantity
from aegisquant.execution.accounts import (
    AccountBalance,
    AccountEventType,
    AccountStreamEvent,
    VenueAccountSnapshot,
)
from aegisquant.execution.commands import AmendOrderCommand, CancelOrderCommand, SubmitOrderCommand
from aegisquant.execution.models import (
    AdapterHealth,
    AdapterHealthState,
    AmendDisposition,
    AmendResult,
    CancelDisposition,
    CancelResult,
    ExecutionEnvironment,
    SubmitDisposition,
    SubmitResult,
)
from aegisquant.execution.rules import InstrumentRuleSnapshot


@runtime_checkable
class ExecutionAdapter(Protocol):
    venue_id: VenueId
    environment: ExecutionEnvironment

    async def instruments(self) -> tuple[InstrumentRuleSnapshot, ...]: ...

    async def account_snapshot(self) -> VenueAccountSnapshot: ...

    async def open_orders(self) -> tuple[VenueOrder, ...]: ...

    async def recent_orders(self) -> tuple[VenueOrder, ...]: ...

    async def recent_fills(self) -> tuple[Fill, ...]: ...

    async def submit(self, command: SubmitOrderCommand) -> SubmitResult: ...

    async def cancel(self, command: CancelOrderCommand) -> CancelResult: ...

    async def amend(self, command: AmendOrderCommand) -> AmendResult: ...

    def stream_account(self) -> AsyncIterator[AccountStreamEvent]: ...

    async def health(self) -> AdapterHealth: ...


class SimulatorFault(StrEnum):
    SUBMIT_TIMEOUT_AFTER_ACCEPT = "SUBMIT_TIMEOUT_AFTER_ACCEPT"
    CANCEL_TIMEOUT_AFTER_CANCEL = "CANCEL_TIMEOUT_AFTER_CANCEL"
    DISCONNECTED = "DISCONNECTED"


class SimulatedBinanceTestnetAdapter:
    """Stateful Testnet-semantic simulator; never performs a network request."""

    venue_id = VenueId("BINANCE-TESTNET")
    environment = ExecutionEnvironment.SIMULATED

    def __init__(
        self,
        *,
        rules: tuple[InstrumentRuleSnapshot, ...],
        balances: tuple[AccountBalance, ...],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if any(rule.venue_id != self.venue_id for rule in rules):
            raise ValueError("simulator rule venue mismatch")
        self._rules = rules
        self._balances = balances
        self._clock = clock or (lambda: datetime.now(UTC))
        self._orders: dict[str, VenueOrder] = {}
        self._submitted_commands: dict[str, SubmitOrderCommand] = {}
        self._command_hashes: dict[str, str] = {}
        self._economic_client_ids: dict[str, str] = {}
        self._fills: list[Fill] = []
        self._events: list[AccountStreamEvent] = []
        self._sequence = 0
        self._connected = True
        self._faults: set[str] = set()

    def inject_fault(self, fault: str) -> None:
        if fault not in {
            SimulatorFault.SUBMIT_TIMEOUT_AFTER_ACCEPT,
            SimulatorFault.CANCEL_TIMEOUT_AFTER_CANCEL,
            SimulatorFault.DISCONNECTED,
        }:
            raise ValueError("unsupported simulator fault")
        self._faults.add(fault)
        if fault == SimulatorFault.DISCONNECTED:
            self._connected = False

    def clear_fault(self, fault: str) -> None:
        self._faults.discard(fault)

    def reconnect(self) -> None:
        self._faults.discard(SimulatorFault.DISCONNECTED)
        self._connected = True

    async def instruments(self) -> tuple[InstrumentRuleSnapshot, ...]:
        return self._rules

    async def account_snapshot(self) -> VenueAccountSnapshot:
        self._require_connected()
        now = self._clock()
        return VenueAccountSnapshot(
            snapshot_id=f"sim-account-{self._sequence}",
            venue_id=self.venue_id,
            sequence=self._sequence,
            captured_at=now,
            balances=self._balances,
            open_orders=await self.open_orders(),
            recent_fill_ids=tuple(item.fill_id for item in self._fills),
        )

    async def open_orders(self) -> tuple[VenueOrder, ...]:
        self._require_connected()
        terminal = {
            VenueOrderStatus.FILLED,
            VenueOrderStatus.CANCELED,
            VenueOrderStatus.REJECTED,
            VenueOrderStatus.EXPIRED,
        }
        return tuple(item for item in self._orders.values() if item.status not in terminal)

    async def recent_orders(self) -> tuple[VenueOrder, ...]:
        self._require_connected()
        return tuple(self._orders.values())

    async def recent_fills(self) -> tuple[Fill, ...]:
        self._require_connected()
        return tuple(self._fills)

    async def submit(self, command: SubmitOrderCommand) -> SubmitResult:
        self._require_connected()
        if command.environment is not ExecutionEnvironment.SIMULATED:
            raise ValueError("AQ-EXEC-SIMULATOR-ENVIRONMENT-MISMATCH")
        key = str(command.command.client_order_id)
        economic_key = str(command.command.idempotency_key)
        bound_client_id = self._economic_client_ids.get(economic_key)
        if bound_client_id is not None and bound_client_id != key:
            bound = self._orders[bound_client_id]
            return SubmitResult(
                client_order_id=command.command.client_order_id,
                venue_order_id=bound.venue_order_id,
                disposition=SubmitDisposition.IDEMPOTENT_REPLAY,
                occurred_at=self._clock(),
                reason_code="AQ-EXEC-ECONOMIC-IDEMPOTENCY-REPLAY",
                economic_order_created=False,
            )
        existing = self._orders.get(key)
        if existing is not None:
            if self._command_hashes[key] != command.content_sha256:
                raise ValueError("AQ-EXEC-CLIENT-ID-CONTENT-CONFLICT")
            return SubmitResult(
                client_order_id=command.command.client_order_id,
                venue_order_id=existing.venue_order_id,
                disposition=SubmitDisposition.IDEMPOTENT_REPLAY,
                occurred_at=self._clock(),
                reason_code="AQ-EXEC-SUBMIT-IDEMPOTENT-REPLAY",
                economic_order_created=False,
            )
        now = self._clock()
        venue_order_id = VenueOrderId(f"sim-{command.content_sha256[:20]}")
        order = VenueOrder(
            venue_order_id=venue_order_id,
            client_order_id=command.command.client_order_id,
            order_intent_id=command.command.order_intent_id,
            venue_id=self.venue_id,
            status=VenueOrderStatus.ACCEPTED,
            locally_sent_at=now,
            venue_accepted_at=now,
            last_venue_update_at=now,
            cumulative_filled_quantity=Quantity(
                amount=Decimal("0"), asset_id=command.quantity.asset_id
            ),
        )
        self._orders[key] = order
        self._submitted_commands[key] = command
        self._command_hashes[key] = command.content_sha256
        self._economic_client_ids[economic_key] = key
        self._emit(AccountEventType.ORDER, f"accepted:{key}")
        if SimulatorFault.SUBMIT_TIMEOUT_AFTER_ACCEPT in self._faults:
            self._faults.remove(SimulatorFault.SUBMIT_TIMEOUT_AFTER_ACCEPT)
            return SubmitResult(
                client_order_id=command.command.client_order_id,
                disposition=SubmitDisposition.UNKNOWN,
                occurred_at=now,
                reason_code="AQ-EXEC-SUBMIT-RESPONSE-TIMEOUT",
                economic_order_created=True,
            )
        return SubmitResult(
            client_order_id=command.command.client_order_id,
            venue_order_id=venue_order_id,
            disposition=SubmitDisposition.ACCEPTED,
            occurred_at=now,
            reason_code="AQ-EXEC-SUBMIT-ACCEPTED",
            economic_order_created=True,
        )

    async def cancel(self, command: CancelOrderCommand) -> CancelResult:
        self._require_connected()
        key = str(command.client_order_id)
        order = self._orders.get(key)
        if order is None:
            return CancelResult(
                client_order_id=command.client_order_id,
                disposition=CancelDisposition.NOT_FOUND,
                occurred_at=self._clock(),
                reason_code="AQ-EXEC-CANCEL-NOT-FOUND",
            )
        if order.status in {VenueOrderStatus.FILLED, VenueOrderStatus.CANCELED}:
            return CancelResult(
                client_order_id=command.client_order_id,
                disposition=CancelDisposition.ALREADY_TERMINAL,
                occurred_at=self._clock(),
                reason_code="AQ-EXEC-CANCEL-ALREADY-TERMINAL",
            )
        now = self._clock()
        self._orders[key] = order.model_copy(
            update={"status": VenueOrderStatus.CANCELED, "last_venue_update_at": now}
        )
        self._emit(AccountEventType.ORDER, f"canceled:{key}")
        if SimulatorFault.CANCEL_TIMEOUT_AFTER_CANCEL in self._faults:
            self._faults.remove(SimulatorFault.CANCEL_TIMEOUT_AFTER_CANCEL)
            return CancelResult(
                client_order_id=command.client_order_id,
                disposition=CancelDisposition.UNKNOWN,
                occurred_at=now,
                reason_code="AQ-EXEC-CANCEL-RESPONSE-TIMEOUT",
            )
        return CancelResult(
            client_order_id=command.client_order_id,
            disposition=CancelDisposition.CANCELED,
            occurred_at=now,
            reason_code="AQ-EXEC-CANCEL-CONFIRMED",
        )

    async def amend(self, command: AmendOrderCommand) -> AmendResult:
        self._require_connected()
        key = str(command.replaces_client_order_id)
        order = self._orders.get(key)
        if order is None:
            disposition = AmendDisposition.NOT_FOUND
            reason = "AQ-EXEC-AMEND-NOT-FOUND"
        elif order.status not in {VenueOrderStatus.ACCEPTED, VenueOrderStatus.PARTIALLY_FILLED}:
            disposition = AmendDisposition.REJECTED
            reason = "AQ-EXEC-AMEND-TERMINAL"
        else:
            disposition = AmendDisposition.AMENDED
            reason = "AQ-EXEC-AMEND-CONFIRMED"
            self._emit(AccountEventType.ORDER, f"amended:{key}")
        return AmendResult(
            client_order_id=command.client_order_id,
            disposition=disposition,
            occurred_at=self._clock(),
            reason_code=reason,
        )

    async def simulate_fill(
        self,
        *,
        client_order_id: str,
        quantity: Quantity,
        price: Price,
        fee: Money,
    ) -> Fill:
        self._require_connected()
        order = self._orders.get(client_order_id)
        if order is None or order.venue_order_id is None:
            raise ValueError("AQ-EXEC-SIMULATED-FILL-ORDER-NOT-FOUND")
        if order.status in {VenueOrderStatus.CANCELED, VenueOrderStatus.FILLED}:
            raise ValueError("AQ-EXEC-SIMULATED-FILL-ORDER-TERMINAL")
        submitted = self._submitted_commands[client_order_id]
        if quantity.amount <= 0:
            raise ValueError("AQ-EXEC-SIMULATED-FILL-NONPOSITIVE")
        if (
            price.base_asset_id != submitted.reference_price.base_asset_id
            or price.quote_asset_id != submitted.reference_price.quote_asset_id
        ):
            raise ValueError("AQ-EXEC-SIMULATED-FILL-PRICE-UNIT-MISMATCH")
        cumulative = order.cumulative_filled_quantity.amount + quantity.amount
        original_asset = order.cumulative_filled_quantity.asset_id
        if quantity.asset_id != original_asset:
            raise ValueError("AQ-EXEC-SIMULATED-FILL-ASSET-MISMATCH")
        command_hash = self._command_hashes[client_order_id]
        submit_quantity = self._submitted_quantity(client_order_id)
        if cumulative > submit_quantity:
            raise ValueError("AQ-EXEC-SIMULATED-OVERFILL")
        now = self._clock()
        status = (
            VenueOrderStatus.FILLED
            if cumulative == submit_quantity
            else VenueOrderStatus.PARTIALLY_FILLED
        )
        self._orders[client_order_id] = order.model_copy(
            update={
                "status": status,
                "last_venue_update_at": now,
                "cumulative_filled_quantity": Quantity(amount=cumulative, asset_id=original_asset),
            }
        )
        fill = Fill(
            fill_id=FillId(f"sim-fill-{len(self._fills) + 1}-{command_hash[:10]}"),
            venue_order_id=order.venue_order_id,
            client_order_id=order.client_order_id,
            order_intent_id=order.order_intent_id,
            instrument_id=submitted.instrument_id,
            side=submitted.side,
            quantity=quantity,
            price=price,
            fee=fee,
            event_time=now,
            available_time=now,
            ingest_time=now,
            idempotency_key=submitted.command.idempotency_key.__class__(
                f"fill:{order.venue_order_id}:{len(self._fills) + 1}"
            ),
        )
        self._fills.append(fill)
        self._emit(AccountEventType.FILL, f"fill:{fill.fill_id}")
        return fill

    def stream_account(self) -> AsyncIterator[AccountStreamEvent]:
        async def iterator() -> AsyncIterator[AccountStreamEvent]:
            self._require_connected()
            while self._events:
                yield self._events.pop(0)

        return iterator()

    async def health(self) -> AdapterHealth:
        connected = self._connected and SimulatorFault.DISCONNECTED not in self._faults
        return AdapterHealth(
            venue_id=self.venue_id,
            environment=self.environment,
            state=AdapterHealthState.READY if connected else AdapterHealthState.DISCONNECTED,
            checked_at=self._clock(),
            sequence_healthy=connected,
            reconciliation_required=not connected,
            reason_codes=(
                "AQ-EXEC-SIMULATOR-READY" if connected else "AQ-EXEC-SIMULATOR-DISCONNECTED",
            ),
        )

    @property
    def economic_order_count(self) -> int:
        return len(self._orders)

    def _submitted_quantity(self, client_order_id: str) -> Decimal:
        return self._submitted_commands[client_order_id].quantity.amount

    def _emit(self, event_type: AccountEventType, evidence: str) -> None:
        self._sequence += 1
        now = self._clock()
        self._events.append(
            AccountStreamEvent(
                event_id=f"sim-account-event-{self._sequence}",
                venue_id=self.venue_id,
                sequence=self._sequence,
                event_type=event_type,
                observed_at=now,
                available_at=now,
                evidence_ids=(evidence,),
            )
        )

    def _require_connected(self) -> None:
        if not self._connected or SimulatorFault.DISCONNECTED in self._faults:
            raise ConnectionError("AQ-EXEC-SIMULATOR-DISCONNECTED")
