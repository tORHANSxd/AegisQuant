"""Risk-bound OrderIntent translation into venue-specific execution commands."""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_core import to_jsonable_python

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import (
    OrderCommand,
    OrderCommandType,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
)
from aegisquant.domain.identifiers import (
    ClientOrderId,
    IdempotencyKey,
    InstrumentId,
    OrderIntentId,
    RiskDecisionId,
    StrategyId,
    VenueId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import PositiveDecimal, Price, Quantity
from aegisquant.execution.models import ExecutionEnvironment
from aegisquant.execution.rules import (
    InstrumentRuleSnapshot,
    QuantizedOrderValues,
    quantize_order_values,
)
from aegisquant.risk.models import RiskDecision, RiskDecisionStatus


class ClientOrderIdentity(DomainModel):
    client_order_id: ClientOrderId
    strategy_id: StrategyId
    release_id: str = Field(min_length=1, max_length=64)
    order_intent_id: OrderIntentId
    slice_sequence: int = Field(ge=0)
    retry_generation: int = Field(ge=0)
    economic_idempotency_key: IdempotencyKey
    checksum: str = Field(pattern=r"^[0-9a-f]{5}$")


def client_order_identity(
    *,
    strategy_id: StrategyId,
    release_id: str,
    intent: OrderIntent,
    slice_sequence: int,
    retry_generation: int,
) -> ClientOrderIdentity:
    if slice_sequence < 0 or retry_generation < 0:
        raise ValueError("client order identity sequences must be nonnegative")
    payload = {
        "strategy_id": str(strategy_id),
        "release_id": release_id,
        "order_intent_id": str(intent.order_intent_id),
        "slice_sequence": slice_sequence,
        "retry_generation": retry_generation,
        "economic_idempotency_key": str(intent.idempotency_key),
    }
    digest = canonical_sha256(payload)
    checksum = digest[-5:]
    return ClientOrderIdentity(
        client_order_id=ClientOrderId(f"aq-{digest[:26]}-{checksum}"),
        strategy_id=strategy_id,
        release_id=release_id,
        order_intent_id=intent.order_intent_id,
        slice_sequence=slice_sequence,
        retry_generation=retry_generation,
        economic_idempotency_key=intent.idempotency_key,
        checksum=checksum,
    )


class SubmitOrderCommand(DomainModel):
    command: OrderCommand
    identity: ClientOrderIdentity
    risk_decision_id: RiskDecisionId
    environment: ExecutionEnvironment
    instrument_id: InstrumentId
    side: OrderSide
    order_type: OrderType
    quantity: Quantity
    limit_price: Price | None
    reference_price: Price
    time_in_force: TimeInForce
    reduce_only: bool
    rule_version: str
    notional: PositiveDecimal
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_submit(self) -> SubmitOrderCommand:
        if self.command.command_type is not OrderCommandType.PLACE:
            raise ValueError("submit wrapper requires a PLACE command")
        if self.command.client_order_id != self.identity.client_order_id:
            raise ValueError("submit command client order identity mismatch")
        if self.command.order_intent_id != self.identity.order_intent_id:
            raise ValueError("submit command order intent identity mismatch")
        if self.command.idempotency_key != self.identity.economic_idempotency_key:
            raise ValueError("submit command economic idempotency mismatch")
        expected = command_content_sha256(self, include_hash=False)
        if self.content_sha256 != expected:
            raise ValueError("submit command content hash mismatch")
        return self


class CancelOrderCommand(DomainModel):
    client_order_id: ClientOrderId
    order_intent_id: OrderIntentId
    venue_id: VenueId
    issued_at: UtcDateTime
    idempotency_key: IdempotencyKey
    reason_code: str = Field(min_length=1)


class AmendOrderCommand(DomainModel):
    client_order_id: ClientOrderId
    replaces_client_order_id: ClientOrderId
    order_intent_id: OrderIntentId
    venue_id: VenueId
    issued_at: UtcDateTime
    idempotency_key: IdempotencyKey
    quantity: Quantity
    limit_price: Price
    rule_version: str


def command_content_sha256(
    command: SubmitOrderCommand | dict[str, object], *, include_hash: bool = True
) -> str:
    if isinstance(command, SubmitOrderCommand):
        payload = command.model_dump(mode="json")
    else:
        payload = dict(command)
    if not include_hash:
        payload.pop("content_sha256", None)
    return canonical_sha256(to_jsonable_python(payload, serialize_unknown=True))


def _risk_gate(intent: OrderIntent, decision: RiskDecision, issued_at: UtcDateTime) -> None:
    if issued_at < intent.created_at:
        raise ValueError("AQ-EXEC-COMMAND-PRECEDES-INTENT")
    if issued_at > intent.valid_until or issued_at > decision.valid_until:
        raise ValueError("AQ-EXEC-INTENT-OR-RISK-EXPIRED")
    if intent.risk_decision_id != decision.risk_decision_id:
        raise ValueError("AQ-EXEC-RISK-DECISION-MISMATCH")
    if decision.status not in {RiskDecisionStatus.APPROVED, RiskDecisionStatus.REDUCE_ONLY}:
        raise ValueError("AQ-EXEC-RISK-DECISION-NOT-ACTIONABLE")
    target = next(
        (item for item in decision.approved_targets if item.instrument_id == intent.instrument_id),
        None,
    )
    if target is None or target.approved_delta_weight == 0:
        raise ValueError("AQ-EXEC-INSTRUMENT-NOT-RISK-APPROVED")
    expected_side = OrderSide.BUY if target.approved_delta_weight > 0 else OrderSide.SELL
    if intent.side is not expected_side:
        raise ValueError("AQ-EXEC-DIRECTION-DIFFERS-FROM-RISK")
    if decision.status is RiskDecisionStatus.REDUCE_ONLY and not intent.reduce_only:
        raise ValueError("AQ-EXEC-REDUCE-ONLY-FLAG-MISSING")


def translate_order_intent(
    *,
    intent: OrderIntent,
    decision: RiskDecision,
    strategy_id: StrategyId,
    release_id: str,
    venue_id: VenueId,
    environment: ExecutionEnvironment,
    rules: InstrumentRuleSnapshot,
    reference_price: Price,
    issued_at: UtcDateTime,
    slice_sequence: int = 0,
    retry_generation: int = 0,
) -> SubmitOrderCommand:
    """Create a content-addressed command only after every risk and rule gate passes."""
    _risk_gate(intent, decision, issued_at)
    if rules.venue_id != venue_id:
        raise ValueError("AQ-EXEC-RULE-VENUE-MISMATCH")
    values: QuantizedOrderValues = quantize_order_values(
        intent=intent,
        rules=rules,
        reference_price=reference_price,
        decision_time=issued_at,
    )
    identity = client_order_identity(
        strategy_id=strategy_id,
        release_id=release_id,
        intent=intent,
        slice_sequence=slice_sequence,
        retry_generation=retry_generation,
    )
    base = OrderCommand(
        client_order_id=identity.client_order_id,
        order_intent_id=intent.order_intent_id,
        venue_id=venue_id,
        command_type=OrderCommandType.PLACE,
        issued_at=issued_at,
        idempotency_key=intent.idempotency_key,
    )
    unverified = SubmitOrderCommand.model_construct(
        command=base,
        identity=identity,
        risk_decision_id=decision.risk_decision_id,
        environment=environment,
        instrument_id=intent.instrument_id,
        side=intent.side,
        order_type=intent.order_type,
        quantity=values.quantity,
        limit_price=values.limit_price,
        reference_price=values.reference_price,
        time_in_force=intent.time_in_force,
        reduce_only=intent.reduce_only,
        rule_version=values.rule_version,
        notional=values.notional,
        content_sha256="0" * 64,
    )
    return SubmitOrderCommand(
        command=base,
        identity=identity,
        risk_decision_id=decision.risk_decision_id,
        environment=environment,
        instrument_id=intent.instrument_id,
        side=intent.side,
        order_type=intent.order_type,
        quantity=values.quantity,
        limit_price=values.limit_price,
        reference_price=values.reference_price,
        time_in_force=intent.time_in_force,
        reduce_only=intent.reduce_only,
        rule_version=values.rule_version,
        notional=values.notional,
        content_sha256=command_content_sha256(unverified, include_hash=False),
    )
