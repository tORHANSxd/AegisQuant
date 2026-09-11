"""Deterministic real-time Paper order and virtual fill engine."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide, OrderType, TimeInForce, VenueOrderStatus
from aegisquant.domain.identifiers import AssetId, ClientOrderId, IdempotencyKey
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Money, Price, Quantity, UnitInterval, canonical_result
from aegisquant.execution.commands import SubmitOrderCommand
from aegisquant.execution.models import ExecutionEnvironment, SubmitDisposition
from aegisquant.runtime.models import MarketObservation, RuntimeMode


class PaperFillPolicy(DomainModel):
    acknowledgement_latency_ms: int = Field(ge=0, le=60_000)
    participation_rate: UnitInterval
    taker_slippage_bps: Decimal = Field(ge=Decimal("0"), le=Decimal("1000"))
    fee_bps: Decimal = Field(ge=Decimal("0"), le=Decimal("1000"))


class PaperFill(DomainModel):
    fill_id: str = Field(min_length=1, max_length=255)
    client_order_id: ClientOrderId
    economic_idempotency_key: IdempotencyKey
    source_event_id: str
    quantity: Quantity
    executable_price: Price
    fill_price: Price
    fee: Money
    event_time: UtcDateTime
    available_at: UtcDateTime
    ingest_time: UtcDateTime

    @model_validator(mode="after")
    def validate_fill(self) -> PaperFill:
        if self.quantity.amount <= 0:
            raise ValueError("Paper fill quantity must be positive")
        if not self.event_time <= self.available_at <= self.ingest_time:
            raise ValueError("Paper fill times must be monotonic")
        if self.quantity.asset_id != self.fill_price.base_asset_id:
            raise ValueError("Paper fill quantity must use the price base asset")
        if (
            self.executable_price.base_asset_id != self.fill_price.base_asset_id
            or self.executable_price.quote_asset_id != self.fill_price.quote_asset_id
        ):
            raise ValueError("Paper fill prices must share units")
        if self.fee.asset_id != self.fill_price.quote_asset_id or self.fee.amount < 0:
            raise ValueError("Paper fill fee must be nonnegative quote asset money")
        return self


class PaperOrderState(DomainModel):
    command: SubmitOrderCommand
    status: VenueOrderStatus
    cumulative_quantity: Quantity
    remaining_quantity: Quantity
    submitted_at: UtcDateTime
    eligible_at: UtcDateTime
    processed_event_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_order(self) -> PaperOrderState:
        quantities = (self.command.quantity, self.cumulative_quantity, self.remaining_quantity)
        if len({item.asset_id for item in quantities}) != 1:
            raise ValueError("Paper order quantities must share one asset")
        if min(self.cumulative_quantity.amount, self.remaining_quantity.amount) < 0:
            raise ValueError("Paper order quantities cannot be negative")
        if (
            self.cumulative_quantity.amount + self.remaining_quantity.amount
            != self.command.quantity.amount
        ):
            raise ValueError("Paper order quantity conservation failed")
        if len(set(self.processed_event_ids)) != len(self.processed_event_ids):
            raise ValueError("Paper order processed events must be unique")
        return self


class PaperSubmitResult(DomainModel):
    client_order_id: ClientOrderId
    disposition: SubmitDisposition
    economic_order_created: bool
    reason_code: str = Field(min_length=1)


class PaperCheckpointPayload(DomainModel):
    schema_version: str = "p13-paper-checkpoint-v1"
    mode: RuntimeMode
    sequence: int = Field(ge=0)
    orders: tuple[PaperOrderState, ...]
    fills: tuple[PaperFill, ...]


class PaperCheckpoint(DomainModel):
    payload: PaperCheckpointPayload
    payload_sha256: str

    @model_validator(mode="after")
    def validate_checkpoint(self) -> PaperCheckpoint:
        ensure_sha256(self.payload_sha256, field_name="payload_sha256")
        expected = canonical_sha256(self.payload.model_dump(mode="json"))
        if expected != self.payload_sha256:
            raise ValueError("AQ-RUNTIME-PAPER-CHECKPOINT-HASH-MISMATCH")
        return self


class PaperEngine:
    """Process risk-bound commands without any venue network capability."""

    def __init__(self, *, mode: RuntimeMode, policy: PaperFillPolicy) -> None:
        if mode not in {RuntimeMode.PAPER, RuntimeMode.HISTORICAL_REPLAY}:
            raise ValueError("Paper engine only supports Paper or historical replay")
        self.mode = mode
        self.policy = policy
        self._orders: dict[str, PaperOrderState] = {}
        self._economic_orders: dict[str, str] = {}
        self._fills: list[PaperFill] = []
        self._sequence = 0

    @property
    def orders(self) -> tuple[PaperOrderState, ...]:
        return tuple(self._orders[key] for key in sorted(self._orders))

    @property
    def fills(self) -> tuple[PaperFill, ...]:
        return tuple(self._fills)

    @property
    def economic_order_count(self) -> int:
        return len(self._economic_orders)

    def submit(self, command: SubmitOrderCommand) -> PaperSubmitResult:
        if command.environment is not ExecutionEnvironment.SIMULATED:
            raise ValueError("AQ-RUNTIME-PAPER-REQUIRES-SIMULATED-COMMAND")
        key = str(command.command.client_order_id)
        economic_key = str(command.command.idempotency_key)
        bound = self._economic_orders.get(economic_key)
        if bound is not None:
            return PaperSubmitResult(
                client_order_id=self._orders[bound].command.command.client_order_id,
                disposition=SubmitDisposition.IDEMPOTENT_REPLAY,
                economic_order_created=False,
                reason_code="AQ-RUNTIME-PAPER-ECONOMIC-REPLAY",
            )
        if key in self._orders:
            raise ValueError("AQ-RUNTIME-PAPER-CLIENT-ID-CONFLICT")
        eligible = command.command.issued_at + timedelta(
            milliseconds=self.policy.acknowledgement_latency_ms
        )
        zero = Quantity(amount=Decimal("0"), asset_id=command.quantity.asset_id)
        self._orders[key] = PaperOrderState(
            command=command,
            status=VenueOrderStatus.ACCEPTED,
            cumulative_quantity=zero,
            remaining_quantity=command.quantity,
            submitted_at=command.command.issued_at,
            eligible_at=eligible,
            processed_event_ids=(),
        )
        self._economic_orders[economic_key] = key
        self._sequence += 1
        return PaperSubmitResult(
            client_order_id=command.command.client_order_id,
            disposition=SubmitDisposition.ACCEPTED,
            economic_order_created=True,
            reason_code="AQ-RUNTIME-PAPER-ACCEPTED",
        )

    def process(self, observation: MarketObservation) -> tuple[PaperFill, ...]:
        created: list[PaperFill] = []
        for key in sorted(self._orders):
            state = self._orders[key]
            if state.command.instrument_id != observation.instrument_id:
                continue
            if state.command.command.venue_id != observation.venue_id:
                continue
            if state.status not in {
                VenueOrderStatus.ACCEPTED,
                VenueOrderStatus.PARTIALLY_FILLED,
            }:
                continue
            if observation.event_id in state.processed_event_ids:
                continue
            state = _replace_order(
                state,
                processed_event_ids=(*state.processed_event_ids, observation.event_id),
            )
            self._orders[key] = state
            if observation.available_at < state.eligible_at:
                continue
            fill = self._decide_fill(state, observation)
            if fill is None:
                if state.command.time_in_force in {
                    TimeInForce.IMMEDIATE_OR_CANCEL,
                    TimeInForce.FILL_OR_KILL,
                }:
                    self._orders[key] = _replace_order(
                        state,
                        status=VenueOrderStatus.CANCELED,
                    )
                continue
            cumulative_amount = state.cumulative_quantity.amount + fill.quantity.amount
            remaining_amount = state.command.quantity.amount - cumulative_amount
            status = (
                VenueOrderStatus.FILLED
                if remaining_amount == 0
                else VenueOrderStatus.PARTIALLY_FILLED
            )
            if (
                state.command.time_in_force is TimeInForce.IMMEDIATE_OR_CANCEL
                and remaining_amount > 0
            ):
                status = VenueOrderStatus.CANCELED
            self._orders[key] = _replace_order(
                state,
                status=status,
                cumulative_quantity=Quantity(
                    amount=cumulative_amount,
                    asset_id=state.command.quantity.asset_id,
                ),
                remaining_quantity=Quantity(
                    amount=remaining_amount,
                    asset_id=state.command.quantity.asset_id,
                ),
            )
            self._fills.append(fill)
            self._sequence += 1
            created.append(fill)
        return tuple(created)

    def _decide_fill(
        self, state: PaperOrderState, observation: MarketObservation
    ) -> PaperFill | None:
        command = state.command
        is_buy = command.side is OrderSide.BUY
        executable = observation.ask_price if is_buy else observation.bid_price
        available = observation.ask_quantity if is_buy else observation.bid_quantity
        passive_touched = False
        if command.order_type is OrderType.LIMIT:
            if command.limit_price is None:
                raise RuntimeError("validated limit command has no limit price")
            crosses = (
                executable.amount <= command.limit_price.amount
                if is_buy
                else executable.amount >= command.limit_price.amount
            )
            passive_touched = not crosses and (
                observation.last_price.amount <= command.limit_price.amount
                if is_buy
                else observation.last_price.amount >= command.limit_price.amount
            )
            if not crosses and not passive_touched:
                return None
            if passive_touched and not crosses:
                executable = command.limit_price
        quantity_amount = min(
            state.remaining_quantity.amount,
            canonical_result(available.amount * self.policy.participation_rate),
        )
        if quantity_amount <= 0:
            return None
        if (
            command.time_in_force is TimeInForce.FILL_OR_KILL
            and quantity_amount < state.remaining_quantity.amount
        ):
            return None
        slippage = Decimal("0") if passive_touched else self.policy.taker_slippage_bps
        multiplier = Decimal("1") + (
            slippage / Decimal("10000") if is_buy else -slippage / Decimal("10000")
        )
        fill_amount = canonical_result(executable.amount * multiplier)
        if command.limit_price is not None:
            fill_amount = (
                min(fill_amount, command.limit_price.amount)
                if is_buy
                else max(fill_amount, command.limit_price.amount)
            )
        fill_price = Price(
            amount=fill_amount,
            base_asset_id=executable.base_asset_id,
            quote_asset_id=executable.quote_asset_id,
        )
        quantity = Quantity(amount=quantity_amount, asset_id=command.quantity.asset_id)
        fee_amount = canonical_result(
            quantity.amount * fill_price.amount * self.policy.fee_bps / Decimal("10000")
        )
        identity = {
            "client_order_id": str(command.command.client_order_id),
            "source_event_id": observation.event_id,
            "sequence": len(self._fills) + 1,
            "quantity": str(quantity.amount),
            "price": str(fill_price.amount),
        }
        return PaperFill(
            fill_id=f"paper-fill-{canonical_sha256(identity)[:24]}",
            client_order_id=command.command.client_order_id,
            economic_idempotency_key=command.command.idempotency_key,
            source_event_id=observation.event_id,
            quantity=quantity,
            executable_price=executable,
            fill_price=fill_price,
            fee=Money(amount=fee_amount, asset_id=fill_price.quote_asset_id),
            event_time=observation.event_time,
            available_at=observation.available_at,
            ingest_time=observation.received_at,
        )

    def checkpoint(self) -> PaperCheckpoint:
        payload = PaperCheckpointPayload(
            mode=self.mode,
            sequence=self._sequence,
            orders=self.orders,
            fills=self.fills,
        )
        return PaperCheckpoint(
            payload=payload,
            payload_sha256=canonical_sha256(payload.model_dump(mode="json")),
        )

    @classmethod
    def restore(cls, checkpoint: PaperCheckpoint, *, policy: PaperFillPolicy) -> PaperEngine:
        engine = cls(mode=checkpoint.payload.mode, policy=policy)
        for order in checkpoint.payload.orders:
            key = str(order.command.command.client_order_id)
            economic_key = str(order.command.command.idempotency_key)
            if key in engine._orders or economic_key in engine._economic_orders:
                raise ValueError("AQ-RUNTIME-PAPER-CHECKPOINT-DUPLICATE-ORDER")
            engine._orders[key] = order
            engine._economic_orders[economic_key] = key
        fill_ids = [item.fill_id for item in checkpoint.payload.fills]
        if len(fill_ids) != len(set(fill_ids)):
            raise ValueError("AQ-RUNTIME-PAPER-CHECKPOINT-DUPLICATE-FILL")
        engine._fills = list(checkpoint.payload.fills)
        engine._sequence = checkpoint.payload.sequence
        return engine


def zero_money(asset_id: AssetId) -> Money:
    return Money(amount=Decimal("0"), asset_id=asset_id)


def _replace_order(
    state: PaperOrderState,
    *,
    status: VenueOrderStatus | None = None,
    cumulative_quantity: Quantity | None = None,
    remaining_quantity: Quantity | None = None,
    processed_event_ids: tuple[str, ...] | None = None,
) -> PaperOrderState:
    return PaperOrderState(
        command=state.command,
        status=status if status is not None else state.status,
        cumulative_quantity=(
            cumulative_quantity if cumulative_quantity is not None else state.cumulative_quantity
        ),
        remaining_quantity=(
            remaining_quantity if remaining_quantity is not None else state.remaining_quantity
        ),
        submitted_at=state.submitted_at,
        eligible_at=state.eligible_at,
        processed_event_ids=(
            processed_event_ids if processed_event_ids is not None else state.processed_event_ids
        ),
    )
