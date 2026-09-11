"""Deterministic P12 execution scenario runner."""

from __future__ import annotations

from pydantic import Field

from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import VenueOrderStatus
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Money, Price, Quantity
from aegisquant.execution.adapter import SimulatedBinanceTestnetAdapter, SimulatorFault
from aegisquant.execution.commands import CancelOrderCommand, SubmitOrderCommand
from aegisquant.execution.models import CancelDisposition, SubmitDisposition
from aegisquant.execution.recovery import RecoveryDisposition, recover_submit_unknown


class SimulationResult(DomainModel):
    submit_disposition: SubmitDisposition
    recovery_disposition: RecoveryDisposition
    fill_count: int = Field(ge=0)
    final_status: VenueOrderStatus
    cancel_disposition: CancelDisposition
    economic_order_count: int = Field(ge=0)
    duplicate_economic_orders: int = Field(ge=0)
    network_requests_performed: int = Field(ge=0)


async def run_timeout_partial_cancel_scenario(
    *,
    adapter: SimulatedBinanceTestnetAdapter,
    command: SubmitOrderCommand,
    partial_quantity: Quantity,
    price: Price,
    fee: Money,
    checked_at: UtcDateTime,
) -> SimulationResult:
    adapter.inject_fault(SimulatorFault.SUBMIT_TIMEOUT_AFTER_ACCEPT)
    submitted = await adapter.submit(command)
    recovered = await recover_submit_unknown(
        adapter=adapter, command=command, checked_at=checked_at
    )
    await adapter.simulate_fill(
        client_order_id=str(command.command.client_order_id),
        quantity=partial_quantity,
        price=price,
        fee=fee,
    )
    cancel = await adapter.cancel(
        CancelOrderCommand(
            client_order_id=command.command.client_order_id,
            order_intent_id=command.command.order_intent_id,
            venue_id=adapter.venue_id,
            issued_at=checked_at,
            idempotency_key=command.command.idempotency_key.__class__(
                f"cancel-{command.command.idempotency_key}"
            ),
            reason_code="AQ-EXEC-SIMULATION-CANCEL",
        )
    )
    final = next(
        item
        for item in await adapter.recent_orders()
        if item.client_order_id == command.command.client_order_id
    )
    return SimulationResult(
        submit_disposition=submitted.disposition,
        recovery_disposition=recovered.disposition,
        fill_count=len(await adapter.recent_fills()),
        final_status=final.status,
        cancel_disposition=cancel.disposition,
        economic_order_count=adapter.economic_order_count,
        duplicate_economic_orders=max(0, adapter.economic_order_count - 1),
        network_requests_performed=0,
    )
