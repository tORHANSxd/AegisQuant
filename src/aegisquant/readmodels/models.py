"""Strict P14 Read Model envelopes and projection payload schemas."""

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
