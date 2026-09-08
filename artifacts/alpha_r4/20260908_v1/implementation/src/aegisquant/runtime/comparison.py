"""Cross-mode semantic comparison and execution-error scorecards."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.values import FiniteDecimal, UnitInterval, canonical_result
from aegisquant.runtime.models import ExecutionErrorPoint, ModeExecutionTrace, RuntimeMode


class SemanticComparison(DomainModel):
    modes: tuple[RuntimeMode, ...] = Field(min_length=3, max_length=3)
    semantic_identity_equal: bool
    identity_fields: tuple[str, ...] = Field(min_length=1)
    permitted_difference_fields: tuple[str, ...] = Field(min_length=1)
    mismatch_fields: tuple[str, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_comparison(self) -> SemanticComparison:
        if len(set(self.modes)) != 3 or set(self.modes) != set(RuntimeMode):
            raise ValueError("comparison requires exactly all three runtime modes")
        if self.semantic_identity_equal == bool(self.mismatch_fields):
            raise ValueError("comparison equality must agree with mismatch fields")
        return self


class RuntimeScorecard(DomainModel):
    strategy_id: str = Field(min_length=1)
    observation_count: int = Field(ge=1)
    fill_rate: UnitInterval
    mean_adverse_slippage_bps: FiniteDecimal | None
    p95_adverse_slippage_bps: FiniteDecimal | None
    rejection_count: int = Field(ge=0)
    degraded_cycle_count: int = Field(ge=0)
    restart_count: int = Field(ge=0)
    reconciliation_difference_count: int = Field(ge=0)
    testnet_pnl_included: bool = False
    production_capacity_claimed: bool = False
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def forbid_unsupported_claims(self) -> RuntimeScorecard:
        if self.testnet_pnl_included or self.production_capacity_claimed:
            raise ValueError("runtime scorecard cannot claim Testnet PnL or production capacity")
        return self


IDENTITY_FIELDS = (
    "prediction_id",
    "strategy_id",
    "model_version_id",
    "risk_decision_id",
    "instrument_id",
    "client_order_id",
    "economic_idempotency_key",
    "command_sha256",
    "side",
    "target_quantity",
    "requested_quantity",
    "expected_price",
)

PERMITTED_DIFFERENCE_FIELDS = (
    "mode",
    "trace_id",
    "market_available_at",
    "executable_price",
    "fill_price",
    "filled_quantity",
    "fee",
    "status",
    "reason_codes",
    "hypothetical",
)


def compare_mode_semantics(traces: tuple[ModeExecutionTrace, ...]) -> SemanticComparison:
    """Prove that three modes preserve one risk-bound economic identity."""
    if len(traces) != 3:
        raise ValueError("exactly three traces are required")
    ordered = tuple(sorted(traces, key=lambda item: item.mode.value))
    mismatches = tuple(
        field
        for field in IDENTITY_FIELDS
        if len({repr(getattr(item, field)) for item in ordered}) != 1
    )
    equal = not mismatches
    return SemanticComparison(
        modes=tuple(item.mode for item in ordered),
        semantic_identity_equal=equal,
        identity_fields=IDENTITY_FIELDS,
        permitted_difference_fields=PERMITTED_DIFFERENCE_FIELDS,
        mismatch_fields=mismatches,
        reason_codes=("AQ-RUNTIME-SEMANTICS-EQUAL" if equal else "AQ-RUNTIME-SEMANTICS-MISMATCH",),
    )


def execution_error_point(trace: ModeExecutionTrace) -> ExecutionErrorPoint:
    """Measure target/order, quote/fill, latency, fill ratio, and fees for one trace."""
    target_gap = canonical_result(trace.requested_quantity.amount - trace.target_quantity.amount)
    expected_to_executable = _adverse_bps(
        expected=trace.expected_price.amount,
        actual=trace.executable_price.amount if trace.executable_price is not None else None,
        side=trace.side,
    )
    executable_to_fill = _adverse_bps(
        expected=trace.executable_price.amount if trace.executable_price is not None else None,
        actual=trace.fill_price.amount if trace.fill_price is not None else None,
        side=trace.side,
    )
    ratio = canonical_result(trace.filled_quantity.amount / trace.requested_quantity.amount)
    latency_ms = int((trace.market_available_at - trace.decision_time).total_seconds() * 1000)
    return ExecutionErrorPoint(
        trace_id=trace.trace_id,
        target_order_gap=target_gap,
        expected_to_executable_bps=expected_to_executable,
        executable_to_fill_bps=executable_to_fill,
        decision_latency_ms=latency_ms,
        fill_ratio=ratio,
        fee_amount=trace.fee.amount,
        reason_codes=("AQ-RUNTIME-EXECUTION-ERROR-MEASURED",),
    )


def build_scorecard(
    traces: tuple[ModeExecutionTrace, ...],
    *,
    degraded_cycle_count: int = 0,
    restart_count: int = 0,
    reconciliation_difference_count: int = 0,
) -> RuntimeScorecard:
    if not traces:
        raise ValueError("scorecard requires at least one trace")
    strategies = {str(item.strategy_id) for item in traces}
    if len(strategies) != 1:
        raise ValueError("scorecard traces must belong to one strategy")
    slippages = sorted(
        value
        for item in traces
        if (value := execution_error_point(item).executable_to_fill_bps) is not None
    )
    filled = sum(item.filled_quantity.amount > 0 for item in traces)
    rejections = sum(item.status in {"REJECTED", "CANCELED", "EXPIRED"} for item in traces)
    mean = (
        canonical_result(sum(slippages, start=Decimal("0")) / Decimal(len(slippages)))
        if slippages
        else None
    )
    p95 = slippages[_nearest_rank_index(len(slippages), Decimal("0.95"))] if slippages else None
    return RuntimeScorecard(
        strategy_id=next(iter(strategies)),
        observation_count=len(traces),
        fill_rate=Decimal(filled) / Decimal(len(traces)),
        mean_adverse_slippage_bps=mean,
        p95_adverse_slippage_bps=p95,
        rejection_count=rejections,
        degraded_cycle_count=degraded_cycle_count,
        restart_count=restart_count,
        reconciliation_difference_count=reconciliation_difference_count,
        testnet_pnl_included=False,
        production_capacity_claimed=False,
        reason_codes=("AQ-RUNTIME-SCORECARD-NONPRODUCTION",),
    )


def _adverse_bps(
    *, expected: Decimal | None, actual: Decimal | None, side: OrderSide
) -> Decimal | None:
    if expected is None or actual is None:
        return None
    direction = Decimal("1") if side is OrderSide.BUY else Decimal("-1")
    return canonical_result((actual - expected) / expected * Decimal("10000") * direction)


def _nearest_rank_index(count: int, quantile: Decimal) -> int:
    rank = int((Decimal(count) * quantile).to_integral_value(rounding="ROUND_CEILING"))
    return max(0, min(count - 1, rank - 1))
