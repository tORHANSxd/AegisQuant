"""Strictly read-only Shadow observation with no trading adapter surface."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import VenueId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Money, Quantity
from aegisquant.execution.accounts import AccountBalance
from aegisquant.execution.commands import SubmitOrderCommand
from aegisquant.execution.models import ExecutionEnvironment
from aegisquant.runtime.models import (
    MarketObservation,
    ModeExecutionTrace,
    PredictionTrace,
    RuntimeMode,
)


class ReadOnlyAccountObservation(DomainModel):
    snapshot_id: str = Field(min_length=1, max_length=255)
    venue_id: VenueId
    observed_at: UtcDateTime
    balances: tuple[AccountBalance, ...]
    open_order_ids: tuple[str, ...]
    write_permissions: bool = False
    credential_values_accessed: bool = False

    @model_validator(mode="after")
    def validate_read_only(self) -> ReadOnlyAccountObservation:
        if self.write_permissions or self.credential_values_accessed:
            raise ValueError("AQ-RUNTIME-SHADOW-ACCOUNT-MUST-BE-READ-ONLY")
        return self


class ShadowRuntime:
    """Record hypothetical decisions; deliberately has no order-write method."""

    def __init__(self) -> None:
        self._records: dict[str, ModeExecutionTrace] = {}
        self._account_observations: list[ReadOnlyAccountObservation] = []

    @property
    def write_capability(self) -> bool:
        return False

    @property
    def records(self) -> tuple[ModeExecutionTrace, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    @property
    def account_observations(self) -> tuple[ReadOnlyAccountObservation, ...]:
        return tuple(self._account_observations)

    def observe_account(self, snapshot: ReadOnlyAccountObservation) -> None:
        self._account_observations.append(snapshot)

    def evaluate(
        self,
        *,
        prediction: PredictionTrace,
        command: SubmitOrderCommand,
        market: MarketObservation,
    ) -> ModeExecutionTrace:
        if command.environment is not ExecutionEnvironment.SIMULATED:
            raise ValueError("AQ-RUNTIME-SHADOW-REQUIRES-SIMULATED-COMMAND")
        if prediction.risk_decision_id != command.risk_decision_id:
            raise ValueError("AQ-RUNTIME-SHADOW-RISK-DECISION-MISMATCH")
        if prediction.instrument_id != command.instrument_id:
            raise ValueError("AQ-RUNTIME-SHADOW-INSTRUMENT-MISMATCH")
        if market.instrument_id != command.instrument_id:
            raise ValueError("AQ-RUNTIME-SHADOW-MARKET-INSTRUMENT-MISMATCH")
        if market.available_at < prediction.generated_at:
            raise ValueError("AQ-RUNTIME-SHADOW-FUTURE-AVAILABILITY-VIOLATION")
        record_key = canonical_sha256(
            {
                "prediction_id": prediction.prediction_id,
                "command_sha256": command.content_sha256,
                "market_event_id": market.event_id,
            }
        )
        existing = self._records.get(record_key)
        if existing is not None:
            return existing
        executable = market.ask_price if command.side is OrderSide.BUY else market.bid_price
        zero_quantity = Quantity(amount=Decimal("0"), asset_id=command.quantity.asset_id)
        zero_fee = Money(amount=Decimal("0"), asset_id=executable.quote_asset_id)
        trace = ModeExecutionTrace(
            mode=RuntimeMode.SHADOW,
            trace_id=f"shadow-{record_key[:24]}",
            prediction_id=prediction.prediction_id,
            strategy_id=prediction.strategy_id,
            model_version_id=prediction.model_version_id,
            risk_decision_id=prediction.risk_decision_id,
            instrument_id=prediction.instrument_id,
            client_order_id=command.command.client_order_id,
            economic_idempotency_key=command.command.idempotency_key,
            command_sha256=command.content_sha256,
            side=command.side,
            target_quantity=prediction.target_quantity,
            requested_quantity=command.quantity,
            expected_price=prediction.expected_price,
            executable_price=executable,
            fill_price=None,
            filled_quantity=zero_quantity,
            fee=zero_fee,
            decision_time=prediction.generated_at,
            market_available_at=market.available_at,
            status="HYPOTHETICAL_ONLY",
            reason_codes=("AQ-RUNTIME-SHADOW-NO-WRITE",),
            hypothetical=True,
            write_attempted=False,
        )
        self._records[record_key] = trace
        return trace


def empty_read_only_account(
    *, venue_id: VenueId, observed_at: UtcDateTime
) -> ReadOnlyAccountObservation:
    return ReadOnlyAccountObservation(
        snapshot_id="shadow-empty-account",
        venue_id=venue_id,
        observed_at=observed_at,
        balances=(),
        open_order_ids=(),
        write_permissions=False,
        credential_values_accessed=False,
    )
