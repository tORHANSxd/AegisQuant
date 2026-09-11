"""Strict P14/P15 Read Model envelopes and projection payload schemas."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import Field, JsonValue, model_validator

from aegisquant.data.hashing import (
    canonical_json_bytes,
    canonical_sha256,
    ensure_sha256,
    safe_relative_path,
)
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, NonNegativeDecimal, UnitInterval

SCHEMA_VERSION: Final = "1.0.0"
SENSITIVE_KEY_PARTS: Final = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "one_time_code",
    "otp",
    "password",
    "secret",
    "session_id",
    "token",
    "verification_code",
)


class ProjectionKind(StrEnum):
    ACCOUNT_OVERVIEW = "rm_account_overview"
    DAILY_PNL = "rm_daily_pnl"
    POSITIONS_CURRENT = "rm_positions_current"
    RISK_SUMMARY = "rm_risk_summary"
    STRATEGIES = "rm_strategies"
    MODELS = "rm_models"
    ORDERS = "rm_orders"
    DATA_HEALTH = "rm_data_health"
    EVENT_CLUSTERS = "rm_event_clusters"
    EVENT_CLAIMS = "rm_event_claims"
    NARRATIVE_STATES = "rm_narrative_states"
    SOURCE_POLICY_STATUS = "rm_source_policy_status"
    PNL_ATTRIBUTION = "rm_pnl_attribution"
    RISK_LIMITS = "rm_risk_limits"
    MODEL_METRICS = "rm_model_metrics"
    SIGNALS = "rm_signals"
    FILLS = "rm_fills"
    EXECUTION_QUALITY = "rm_execution_quality"
    MARKET_STATE = "rm_market_state"
    RESEARCH_RUNS = "rm_research_runs"
    INCIDENTS = "rm_incidents"
    SYSTEM_HEALTH = "rm_system_health"
    RECONCILIATION_STATUS = "rm_reconciliation_status"
    ORDER_TRACES = "rm_order_traces"


class QualityState(StrEnum):
    LIVE = "LIVE"
    STALE = "STALE"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"
    ESTIMATED = "ESTIMATED"


class TimeValuePoint(DomainModel):
    time: UtcDateTime
    value: FiniteDecimal


class AccountOverviewPayload(DomainModel):
    account_id: str = Field(min_length=1, max_length=128)
    environment: Literal["RESEARCH", "PAPER", "SHADOW"]
    reporting_asset_id: str = Field(min_length=1, max_length=32)
    equity: FiniteDecimal
    cash: FiniteDecimal
    gross_exposure: NonNegativeDecimal
    net_exposure: FiniteDecimal
    leverage: NonNegativeDecimal
    margin_utilization: UnitInterval
    open_order_count: int = Field(ge=0)
    unknown_order_count: int = Field(ge=0)
    last_reconciliation_at: UtcDateTime
    live_trading_locked: Literal[True]
    equity_curve: tuple[TimeValuePoint, ...] = Field(min_length=1)
    source_scope: str = Field(min_length=1, max_length=128)


class DailyPnLPayload(DomainModel):
    account_id: str = Field(min_length=1, max_length=128)
    business_date: date
    reporting_asset_id: str = Field(min_length=1, max_length=32)
    realized: FiniteDecimal
    unrealized: FiniteDecimal
    fees: NonNegativeDecimal
    funding: FiniteDecimal
    net: FiniteDecimal
    pnl_curve: tuple[TimeValuePoint, ...] = Field(min_length=1)
    source_scope: str = Field(min_length=1, max_length=128)


class PositionPayload(DomainModel):
    position_id: str = Field(min_length=1, max_length=255)
    account_id: str = Field(min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=255)
    strategy_id: str = Field(min_length=1, max_length=128)
    quantity: FiniteDecimal
    average_entry_price: FiniteDecimal | None
    mark_price: FiniteDecimal
    unrealized_pnl: FiniteDecimal
    reporting_asset_id: str = Field(min_length=1, max_length=32)
    source_scope: str = Field(min_length=1, max_length=128)


class RiskSummaryPayload(DomainModel):
    account_id: str = Field(min_length=1, max_length=128)
    state: Literal["NORMAL", "CAUTION", "REDUCE_ONLY", "HALTED"]
    daily_pnl_fraction: FiniteDecimal
    drawdown_fraction: NonNegativeDecimal
    gross_weight: NonNegativeDecimal
    margin_utilization: UnitInterval
    liquidity_score: UnitInterval
    new_risk_allowed: bool
    ledger_reconciled: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)
    source_snapshot_sha256: str

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        ensure_sha256(self.source_snapshot_sha256, field_name="source_snapshot_sha256")
        if self.state != "NORMAL" and self.new_risk_allowed:
            raise ValueError("non-normal risk state cannot allow new risk")
        return self


class StrategyPayload(DomainModel):
    strategy_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    status: Literal["RESEARCH", "PAPER", "SHADOW", "RETIRED"]
    reporting_asset_id: str = Field(min_length=1, max_length=32)
    net_pnl: FiniteDecimal
    maximum_drawdown: NonNegativeDecimal
    turnover: NonNegativeDecimal
    current_signal: FiniteDecimal
    model_id: str = Field(min_length=1, max_length=128)
    production_alpha_claimed: Literal[False]


class ModelPayload(DomainModel):
    model_id: str = Field(min_length=1, max_length=128)
    family: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    status: Literal["BASELINE", "CHALLENGER", "CHAMPION", "RETIRED"]
    metric_name: str = Field(min_length=1, max_length=64)
    metric_value: FiniteDecimal
    observations: int = Field(ge=0)
    modality: str = Field(min_length=1, max_length=64)
    final_holdout_opened: Literal[False]
    live_calibration_claimed: Literal[False]


class OrderPayload(DomainModel):
    order_id: str = Field(min_length=1, max_length=255)
    account_id: str = Field(min_length=1, max_length=128)
    strategy_id: str = Field(min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=255)
    venue_id: str = Field(min_length=1, max_length=64)
    side: Literal["BUY", "SELL"]
    order_type: str = Field(min_length=1, max_length=32)
    quantity: NonNegativeDecimal
    filled_quantity: NonNegativeDecimal
    average_fill_price: FiniteDecimal | None
    status: str = Field(min_length=1, max_length=64)
    submitted_at: UtcDateTime
    completed_at: UtcDateTime | None
    virtual: Literal[True]

    @model_validator(mode="after")
    def no_overfill(self) -> Self:
        if self.filled_quantity > self.quantity:
            raise ValueError("read-model order cannot overfill")
        return self


class DataHealthPayload(DomainModel):
    provider_id: str = Field(min_length=1, max_length=128)
    state: Literal["READY", "STALE", "DEGRADED", "DISCONNECTED", "ERROR"]
    last_success_at: UtcDateTime | None
    latency_ms: int | None = Field(default=None, ge=0)
    gap_count: int = Field(ge=0)
    policy_status: str = Field(min_length=1, max_length=64)
    reason_codes: tuple[str, ...] = Field(min_length=1)


class EventImpactPayload(DomainModel):
    event_cluster_id: str = Field(min_length=1, max_length=255)
    status: Literal["FORMING", "CONFIRMED", "REFUTED", "RESOLVED"]
    confidence: UnitInterval
    impact_score: FiniteDecimal
    independent_family_count: int = Field(ge=0)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    affected_assets: tuple[str, ...] = Field(min_length=1)
    price_led_event: bool
    risk_action: Literal["INFO", "WATCH", "CAUTION", "REDUCE", "HALT"]
    impact_5m: FiniteDecimal
    impact_30m: FiniteDecimal
    impact_4h: FiniteDecimal
    impact_1d: FiniteDecimal
    impact_7d: FiniteDecimal


class ClaimEvidencePayload(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=255)
    event_cluster_id: str = Field(min_length=1, max_length=255)
    claim_id: str = Field(min_length=1, max_length=255)
    relation: Literal["SUPPORTS", "REFUTES"]
    source_family_id: str = Field(min_length=1, max_length=255)
    policy_id: str = Field(min_length=1, max_length=255)
    model_version: str = Field(min_length=1, max_length=128)
    available_at: UtcDateTime
    lawful_excerpt_available: bool


class NarrativePayload(DomainModel):
    narrative_id: str = Field(min_length=1, max_length=255)
    topic: str = Field(min_length=1, max_length=512)
    propagation_stage: str = Field(min_length=1, max_length=64)
    independent_author_count: int = Field(ge=0)
    coordination_risk: UnitInterval
    velocity: FiniteDecimal | None
    attention_half_life_minutes: int | None = Field(default=None, ge=0)


class SourcePolicyPayload(DomainModel):
    source_id: str = Field(min_length=1, max_length=128)
    runtime_state: str = Field(min_length=1, max_length=64)
    disposition: str = Field(min_length=1, max_length=64)
    policy_status: str = Field(min_length=1, max_length=64)
    last_success_at: UtcDateTime | None
    gap_count: int = Field(ge=0)
    reason_codes: tuple[str, ...] = Field(min_length=1)


class PnLAttributionPayload(DomainModel):
    account_id: str = Field(min_length=1, max_length=128)
    reporting_asset_id: str = Field(min_length=1, max_length=32)
    gross_trading_pnl: FiniteDecimal
    trading_fees: NonNegativeDecimal
    spread_cost: NonNegativeDecimal
    slippage_cost: NonNegativeDecimal
    impact_cost: NonNegativeDecimal
    funding: FiniteDecimal
    borrow_interest: NonNegativeDecimal
    net_pnl: FiniteDecimal
    formula: Literal[
        "gross_trading_pnl - trading_fees - spread_cost - slippage_cost - impact_cost "
        "+ funding - borrow_interest"
    ]
    source_scope: str = Field(min_length=1, max_length=128)


class RiskLimitPayload(DomainModel):
    limit_id: str = Field(min_length=1, max_length=128)
    policy_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    current_value: FiniteDecimal
    limit_value: NonNegativeDecimal
    headroom: FiniteDecimal
    unit: Literal["fraction", "score"]
    breached: bool
    example_values_only: Literal[True]
    live_editable: Literal[False]


class ModelMetricPayload(DomainModel):
    model_id: str = Field(min_length=1, max_length=128)
    family: str = Field(min_length=1, max_length=128)
    modality: str = Field(min_length=1, max_length=64)
    metric_name: str = Field(min_length=1, max_length=64)
    metric_value: FiniteDecimal
    evaluation_state: str = Field(min_length=1, max_length=64)
    selected: bool
    train_seconds: NonNegativeDecimal
    peak_memory_mb: NonNegativeDecimal
    abstain_or_failure_reason: str | None = Field(default=None, max_length=512)
    final_holdout_opened: Literal[False]
    alpha_claimed: Literal[False]


class SignalPayload(DomainModel):
    signal_id: str = Field(min_length=1, max_length=255)
    proposal_id: str = Field(min_length=1, max_length=255)
    strategy_id: str = Field(min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=255)
    normalized_signal: FiniteDecimal
    current_weight: FiniteDecimal
    target_weight: FiniteDecimal
    delta_weight: FiniteDecimal
    expected_return_contribution: FiniteDecimal
    estimated_impact_bps: NonNegativeDecimal
    valid_until: UtcDateTime
    environment_stage: Literal["PAPER"]
    order_capability: Literal[False]


class FillPayload(DomainModel):
    fill_id: str = Field(min_length=1, max_length=255)
    order_id: str = Field(min_length=1, max_length=255)
    order_intent_id: str = Field(min_length=1, max_length=255)
    instrument_id: str = Field(min_length=1, max_length=255)
    side: Literal["BUY", "SELL"]
    quantity: NonNegativeDecimal
    reference_price: FiniteDecimal
    execution_price: FiniteDecimal
    fee: NonNegativeDecimal
    fee_asset_id: str = Field(min_length=1, max_length=32)
    liquidity_role: str = Field(min_length=1, max_length=64)
    event_time: UtcDateTime
    available_at: UtcDateTime
    ingest_time: UtcDateTime
    latency_ns: int = Field(ge=0)
    virtual: Literal[True]


class ExecutionQualityPayload(DomainModel):
    strategy_id: str = Field(min_length=1, max_length=128)
    observation_count: int = Field(ge=0)
    fill_rate: UnitInterval
    mean_adverse_slippage_bps: FiniteDecimal
    p95_adverse_slippage_bps: FiniteDecimal
    reconciliation_difference_count: int = Field(ge=0)
    rejection_count: int = Field(ge=0)
    restart_count: int = Field(ge=0)
    degraded_cycle_count: int = Field(ge=0)
    production_capacity_claimed: Literal[False]
    testnet_pnl_included: Literal[False]


class CandlePoint(DomainModel):
    time: UtcDateTime
    open: FiniteDecimal
    high: FiniteDecimal
    low: FiniteDecimal
    close: FiniteDecimal
    volume: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_prices(self) -> Self:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("candle OHLC bounds are inconsistent")
        if self.high < self.low:
            raise ValueError("candle high cannot be below low")
        return self


class ReplayMarker(DomainModel):
    time: UtcDateTime
    marker_type: Literal["EVENT", "DECISION", "FILL", "EVALUATION"]
    entity_id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=256)
    price: FiniteDecimal
    source_artifact: str
    synthetic: Literal[False]

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        safe_relative_path(self.source_artifact)
        return self


class MarketStatePayload(DomainModel):
    market_id: str = Field(min_length=1, max_length=255)
    instrument_id: str = Field(min_length=1, max_length=255)
    venue_id: str = Field(min_length=1, max_length=64)
    data_kind: Literal["HISTORICAL_REPLAY", "NORMALIZED_QUOTE_REPLAY", "PUBLIC_FIXTURE"]
    bar_semantics: Literal["OHLC", "QUOTE_ENVELOPE"]
    mark_price: FiniteDecimal | None = None
    index_price: FiniteDecimal | None = None
    basis: FiniteDecimal | None = None
    funding_rate: FiniteDecimal | None = None
    open_interest: NonNegativeDecimal | None = None
    candles: tuple[CandlePoint, ...]
    replay_markers: tuple[ReplayMarker, ...]
    recommendation_provided: Literal[False]


class ResearchMetric(DomainModel):
    name: str = Field(min_length=1, max_length=128)
    value: FiniteDecimal


class ResearchRunPayload(DomainModel):
    run_id: str = Field(min_length=1, max_length=255)
    model_id: str = Field(min_length=1, max_length=128)
    status: Literal["SUCCEEDED", "FAILED", "ERROR", "PRUNED"]
    started_at: UtcDateTime
    finished_at: UtcDateTime
    metrics: tuple[ResearchMetric, ...]
    failure_reason: str | None = Field(default=None, max_length=512)
    promotion_decision: str = Field(min_length=1, max_length=64)
    code_commit: str = Field(min_length=40, max_length=64)
    dataset_sha256: str
    split_sha256: str
    ai_proposed: bool
    final_holdout_opened: Literal[False]

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        ensure_sha256(self.dataset_sha256, field_name="dataset_sha256")
        ensure_sha256(self.split_sha256, field_name="split_sha256")
        return self


class IncidentTimelinePoint(DomainModel):
    sequence: int = Field(ge=1)
    occurred_at: UtcDateTime
    event_type: str = Field(min_length=1, max_length=64)
    state: str = Field(min_length=1, max_length=64)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    operator_action_required: bool


class IncidentPayload(DomainModel):
    incident_id: str = Field(min_length=1, max_length=255)
    severity: Literal["SEV0", "SEV1", "SEV2", "SEV3"]
    fault_kind: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=64)
    risk_state: str = Field(min_length=1, max_length=64)
    reason_code: str = Field(min_length=1, max_length=128)
    runbook_path: str
    new_risk_allowed: Literal[False]
    real_funds_impacted: Literal[False]
    postmortem_required: bool
    checkpoint_verified: bool
    reconciliation_clear: bool
    duplicate_fill_count: int = Field(ge=0)
    duplicate_order_count: int = Field(ge=0)
    timeline: tuple[IncidentTimelinePoint, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_runbook(self) -> Self:
        safe_relative_path(self.runbook_path)
        sequences = tuple(item.sequence for item in self.timeline)
        if sequences != tuple(range(1, len(sequences) + 1)):
            raise ValueError("incident timeline sequence must be contiguous")
        return self


class SystemHealthPayload(DomainModel):
    service_id: str = Field(min_length=1, max_length=128)
    status: Literal["READY", "DEGRADED", "ERROR"]
    version: str = Field(min_length=1, max_length=64)
    checked_at: UtcDateTime
    check_name: str = Field(min_length=1, max_length=128)
    detail: str = Field(min_length=1, max_length=512)
    historical_check: Literal[True]
    live_trading_locked: Literal[True]


class ReconciliationPayload(DomainModel):
    account_id: str = Field(min_length=1, max_length=128)
    venue_id: str = Field(min_length=1, max_length=64)
    state: str = Field(min_length=1, max_length=64)
    applied: bool
    last_sequence: int = Field(ge=0)
    sequence_gap: bool
    unknown_local_fill_count: int = Field(ge=0)
    unknown_local_order_count: int = Field(ge=0)
    unknown_venue_fill_count: int = Field(ge=0)
    unknown_venue_order_count: int = Field(ge=0)
    captured_at: UtcDateTime
    reason_codes: tuple[str, ...] = Field(min_length=1)


TraceStageName = Literal[
    "SIGNAL",
    "EVENT_EVIDENCE",
    "MODEL",
    "RISK",
    "ORDER",
    "FILL",
    "LEDGER",
]


class OrderTraceStage(DomainModel):
    sequence: int = Field(ge=1, le=7)
    stage: TraceStageName
    status: Literal["VERIFIED", "NOT_APPLICABLE", "NOT_AVAILABLE"]
    entity_id: str | None = Field(default=None, max_length=255)
    source_artifact: str
    explanation: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        safe_relative_path(self.source_artifact)
        if self.status == "VERIFIED" and self.entity_id is None:
            raise ValueError("verified trace stage requires an entity id")
        return self


class OrderTracePayload(DomainModel):
    order_id: str = Field(min_length=1, max_length=255)
    account_id: str = Field(min_length=1, max_length=128)
    strategy_id: str = Field(min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=255)
    decision_time: UtcDateTime
    stages: tuple[OrderTraceStage, ...] = Field(min_length=7, max_length=7)
    complete: bool
    causal_link_overclaimed: Literal[False]

    @model_validator(mode="after")
    def validate_trace(self) -> Self:
        expected = (
            "SIGNAL",
            "EVENT_EVIDENCE",
            "MODEL",
            "RISK",
            "ORDER",
            "FILL",
            "LEDGER",
        )
        if tuple(item.stage for item in self.stages) != expected:
            raise ValueError("order trace stages must use the canonical order")
        if tuple(item.sequence for item in self.stages) != tuple(range(1, 8)):
            raise ValueError("order trace sequence must be contiguous")
        expected_complete = all(item.status != "NOT_AVAILABLE" for item in self.stages)
        if self.complete != expected_complete:
            raise ValueError("order trace completeness does not match stage availability")
        return self


PayloadModel = (
    AccountOverviewPayload
    | DailyPnLPayload
    | PositionPayload
    | RiskSummaryPayload
    | StrategyPayload
    | ModelPayload
    | OrderPayload
    | DataHealthPayload
    | EventImpactPayload
    | ClaimEvidencePayload
    | NarrativePayload
    | SourcePolicyPayload
    | PnLAttributionPayload
    | RiskLimitPayload
    | ModelMetricPayload
    | SignalPayload
    | FillPayload
    | ExecutionQualityPayload
    | MarketStatePayload
    | ResearchRunPayload
    | IncidentPayload
    | SystemHealthPayload
    | ReconciliationPayload
    | OrderTracePayload
)

PAYLOAD_MODELS: Final[dict[ProjectionKind, type[DomainModel]]] = {
    ProjectionKind.ACCOUNT_OVERVIEW: AccountOverviewPayload,
    ProjectionKind.DAILY_PNL: DailyPnLPayload,
    ProjectionKind.POSITIONS_CURRENT: PositionPayload,
    ProjectionKind.RISK_SUMMARY: RiskSummaryPayload,
    ProjectionKind.STRATEGIES: StrategyPayload,
    ProjectionKind.MODELS: ModelPayload,
    ProjectionKind.ORDERS: OrderPayload,
    ProjectionKind.DATA_HEALTH: DataHealthPayload,
    ProjectionKind.EVENT_CLUSTERS: EventImpactPayload,
    ProjectionKind.EVENT_CLAIMS: ClaimEvidencePayload,
    ProjectionKind.NARRATIVE_STATES: NarrativePayload,
    ProjectionKind.SOURCE_POLICY_STATUS: SourcePolicyPayload,
    ProjectionKind.PNL_ATTRIBUTION: PnLAttributionPayload,
    ProjectionKind.RISK_LIMITS: RiskLimitPayload,
    ProjectionKind.MODEL_METRICS: ModelMetricPayload,
    ProjectionKind.SIGNALS: SignalPayload,
    ProjectionKind.FILLS: FillPayload,
    ProjectionKind.EXECUTION_QUALITY: ExecutionQualityPayload,
    ProjectionKind.MARKET_STATE: MarketStatePayload,
    ProjectionKind.RESEARCH_RUNS: ResearchRunPayload,
    ProjectionKind.INCIDENTS: IncidentPayload,
    ProjectionKind.SYSTEM_HEALTH: SystemHealthPayload,
    ProjectionKind.RECONCILIATION_STATUS: ReconciliationPayload,
    ProjectionKind.ORDER_TRACES: OrderTracePayload,
}


def validate_safe_json(value: JsonValue, *, path: str = "payload") -> None:
    """Reject floats and secret-shaped keys at the Read Model trust boundary."""
    if isinstance(value, float):
        raise ValueError(f"AQ-READMODEL-FLOAT-FORBIDDEN: {path}")
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = key.casefold().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                raise ValueError(f"AQ-READMODEL-SENSITIVE-FIELD: {path}.{key}")
            validate_safe_json(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            validate_safe_json(nested, path=f"{path}[{index}]")


class ProjectionEvent(DomainModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=255)
    sequence: int = Field(ge=1)
    projection: ProjectionKind
    entity_id: str = Field(min_length=1, max_length=255)
    as_of_time: UtcDateTime
    available_at: UtcDateTime
    quality_state: QualityState
    authoritative: bool
    estimated: bool
    source_artifact: str
    source_sha256: str
    payload: dict[str, JsonValue]
    payload_sha256: str

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.available_at < self.as_of_time:
            raise ValueError("projection event cannot be available before its as-of time")
        safe_relative_path(self.source_artifact)
        ensure_sha256(self.source_sha256, field_name="source_sha256")
        ensure_sha256(self.payload_sha256, field_name="payload_sha256")
        validate_safe_json(self.payload)
        PAYLOAD_MODELS[self.projection].model_validate_json(canonical_json_bytes(self.payload))
        if canonical_sha256(self.payload) != self.payload_sha256:
            raise ValueError("AQ-READMODEL-PAYLOAD-HASH-MISMATCH")
        if self.authoritative and self.estimated:
            raise ValueError("authoritative Read Model payload cannot also be estimated")
        return self


class ReadModelRecord(DomainModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    projection: ProjectionKind
    entity_id: str = Field(min_length=1, max_length=255)
    source_sequence: int = Field(ge=1)
    as_of_time: UtcDateTime
    projected_at: UtcDateTime
    source_watermark: str = Field(min_length=66, max_length=96)
    quality_state: QualityState
    authoritative: bool
    estimated: bool
    source_artifact: str
    source_sha256: str
    payload: dict[str, JsonValue]
    content_sha256: str

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.projected_at < self.as_of_time:
            raise ValueError("projection time cannot precede as-of time")
        safe_relative_path(self.source_artifact)
        ensure_sha256(self.source_sha256, field_name="source_sha256")
        ensure_sha256(self.content_sha256, field_name="content_sha256")
        validate_safe_json(self.payload)
        PAYLOAD_MODELS[self.projection].model_validate_json(canonical_json_bytes(self.payload))
        expected = canonical_sha256(self.hash_payload())
        if expected != self.content_sha256:
            raise ValueError("AQ-READMODEL-RECORD-HASH-MISMATCH")
        return self

    def hash_payload(self) -> dict[str, JsonValue]:
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        return {str(key): value for key, value in payload.items()}


class ProjectionCheckpoint(DomainModel):
    projection: ProjectionKind
    last_sequence: int = Field(ge=1)
    source_watermark: str = Field(min_length=66, max_length=96)
    projected_at: UtcDateTime
    record_count: int = Field(ge=0)
    state_sha256: str

    @model_validator(mode="after")
    def validate_state_hash(self) -> Self:
        ensure_sha256(self.state_sha256, field_name="state_sha256")
        return self


class ProjectionSnapshot(DomainModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    rebuild_id: str = Field(min_length=1, max_length=255)
    rebuilt_at: UtcDateTime
    source_event_count: int = Field(ge=1)
    records: tuple[ReadModelRecord, ...] = Field(min_length=1)
    checkpoints: tuple[ProjectionCheckpoint, ...] = Field(min_length=1)
    content_sha256: str

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        ensure_sha256(self.content_sha256, field_name="content_sha256")
        record_keys = {(item.projection, item.entity_id) for item in self.records}
        if len(record_keys) != len(self.records):
            raise ValueError("Read Model snapshot contains duplicate record keys")
        projections = {item.projection for item in self.records}
        if projections != {item.projection for item in self.checkpoints}:
            raise ValueError("Read Model checkpoint set does not match record projections")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_sha256(payload) != self.content_sha256:
            raise ValueError("AQ-READMODEL-SNAPSHOT-HASH-MISMATCH")
        return self
