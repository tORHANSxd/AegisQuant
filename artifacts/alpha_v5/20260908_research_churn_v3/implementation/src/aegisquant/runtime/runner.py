"""One risk-bound command bundle executed under three non-funded modes."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.values import Money, Quantity
from aegisquant.execution.commands import SubmitOrderCommand
from aegisquant.runtime.models import (
    MarketObservation,
    ModeExecutionTrace,
    PredictionTrace,
    RuntimeMode,
    RuntimeReadModelEvent,
)
from aegisquant.runtime.paper import PaperEngine, PaperFill, PaperFillPolicy
from aegisquant.runtime.shadow import ShadowRuntime


class RuntimeCommandBundle(DomainModel):
    bundle_id: str = Field(min_length=1, max_length=255)
    prediction: PredictionTrace
    command: SubmitOrderCommand

    @model_validator(mode="after")
    def validate_binding(self) -> RuntimeCommandBundle:
        if self.prediction.risk_decision_id != self.command.risk_decision_id:
            raise ValueError("runtime bundle risk decision mismatch")
        if self.prediction.instrument_id != self.command.instrument_id:
            raise ValueError("runtime bundle instrument mismatch")
        if self.prediction.side is not self.command.side:
            raise ValueError("runtime bundle direction mismatch")
        if self.prediction.target_quantity != self.command.quantity:
            raise ValueError("runtime bundle target/command quantity mismatch")
        return self


class ModeRunResult(DomainModel):
    mode: RuntimeMode
    trace: ModeExecutionTrace
    fills: tuple[PaperFill, ...]
    read_model_events: tuple[RuntimeReadModelEvent, ...] = Field(min_length=1)
    venue_network_requests_performed: int = Field(default=0, ge=0)
    real_account_access_performed: bool = False

    @model_validator(mode="after")
    def validate_nonfunded(self) -> ModeRunResult:
        if self.mode is RuntimeMode.SHADOW and self.fills:
            raise ValueError("Shadow result cannot contain fills")
        if self.venue_network_requests_performed or self.real_account_access_performed:
            raise ValueError("P13 mode runner cannot access a venue or real account")
        return self


def run_runtime_mode(
    *,
    mode: RuntimeMode,
    bundle: RuntimeCommandBundle,
    market: MarketObservation,
    paper_policy: PaperFillPolicy,
) -> ModeRunResult:
    if market.available_at < bundle.prediction.generated_at:
        raise ValueError("AQ-RUNTIME-MARKET-NOT-AVAILABLE-AT-DECISION")
    if mode is RuntimeMode.SHADOW:
        trace = ShadowRuntime().evaluate(
            prediction=bundle.prediction,
            command=bundle.command,
            market=market,
        )
        fills: tuple[PaperFill, ...] = ()
    else:
        engine = PaperEngine(mode=mode, policy=paper_policy)
        engine.submit(bundle.command)
        fills = engine.process(market)
        state = engine.orders[0]
        fill = fills[0] if fills else None
        executable = market.ask_price if bundle.command.side is OrderSide.BUY else market.bid_price
        zero = Quantity(amount=Decimal("0"), asset_id=bundle.command.quantity.asset_id)
        trace_identity = canonical_sha256({"bundle": bundle.bundle_id, "market": market.event_id})
        trace = ModeExecutionTrace(
            mode=mode,
            trace_id=f"{mode.value.lower()}-{trace_identity[:24]}",
            prediction_id=bundle.prediction.prediction_id,
            strategy_id=bundle.prediction.strategy_id,
            model_version_id=bundle.prediction.model_version_id,
            risk_decision_id=bundle.prediction.risk_decision_id,
            instrument_id=bundle.prediction.instrument_id,
            client_order_id=bundle.command.command.client_order_id,
            economic_idempotency_key=bundle.command.command.idempotency_key,
            command_sha256=bundle.command.content_sha256,
            side=bundle.command.side,
            target_quantity=bundle.prediction.target_quantity,
            requested_quantity=bundle.command.quantity,
            expected_price=bundle.prediction.expected_price,
            executable_price=fill.executable_price if fill is not None else executable,
            fill_price=fill.fill_price if fill is not None else None,
            filled_quantity=fill.quantity if fill is not None else zero,
            fee=(
                fill.fee
                if fill is not None
                else Money(amount=Decimal("0"), asset_id=executable.quote_asset_id)
            ),
            decision_time=bundle.prediction.generated_at,
            market_available_at=market.available_at,
            status=state.status.value,
            reason_codes=(
                "AQ-RUNTIME-PAPER-VIRTUAL-FILL" if fill is not None else "AQ-RUNTIME-PAPER-NO-FILL",
            ),
            hypothetical=False,
            write_attempted=False,
        )
    payload_sha = canonical_sha256(trace.model_dump(mode="json"))
    read_event = RuntimeReadModelEvent(
        event_id=f"runtime-read-{payload_sha[:24]}",
        sequence=1,
        mode=mode,
        event_type="MODE_EXECUTION_TRACE",
        entity_id=trace.trace_id,
        occurred_at=market.event_time,
        available_at=market.received_at,
        payload_sha256=payload_sha,
        source_event_ids=(market.event_id,),
    )
    return ModeRunResult(
        mode=mode,
        trace=trace,
        fills=fills,
        read_model_events=(read_event,),
        venue_network_requests_performed=0,
        real_account_access_performed=False,
    )


def run_all_modes(
    *,
    bundle: RuntimeCommandBundle,
    market: MarketObservation,
    paper_policy: PaperFillPolicy,
) -> tuple[ModeRunResult, ...]:
    return tuple(
        run_runtime_mode(
            mode=mode,
            bundle=bundle,
            market=market,
            paper_policy=paper_policy,
        )
        for mode in (
            RuntimeMode.HISTORICAL_REPLAY,
            RuntimeMode.PAPER,
            RuntimeMode.SHADOW,
        )
    )
