"""Versioned P14/P15 HTTP response contracts generated into the web client."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.readmodels.models import (
    AccountOverviewPayload,
    CandlePoint,
    ClaimEvidencePayload,
    DailyPnLPayload,
    DataHealthPayload,
    EventImpactPayload,
    ExecutionQualityPayload,
    FillPayload,
    IncidentPayload,
    MarketStatePayload,
    ModelMetricPayload,
    ModelPayload,
    NarrativePayload,
    OrderPayload,
    OrderTracePayload,
    PnLAttributionPayload,
    PositionPayload,
    ProjectionKind,
    QualityState,
    ReconciliationPayload,
    ResearchRunPayload,
    RiskLimitPayload,
    RiskSummaryPayload,
    SignalPayload,
    SourcePolicyPayload,
    StrategyPayload,
    SystemHealthPayload,
    TimeValuePoint,
)


class ErrorBody(DomainModel):
    code: str = Field(pattern=r"^AQ-API-[A-Z0-9-]+$")
    message: str = Field(min_length=1, max_length=512)
    correlation_id: str = Field(min_length=1, max_length=128)


class ErrorResponse(DomainModel):
    error: ErrorBody


class PageMeta(DomainModel):
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    next_cursor: str | None = None


class RecordMetadata(DomainModel):
    schema_version: Literal["1.0.0"]
    projection: ProjectionKind
    entity_id: str
    source_sequence: int = Field(ge=1)
    as_of_time: UtcDateTime
    projected_at: UtcDateTime
    source_watermark: str
    quality_state: QualityState
    authoritative: bool
    estimated: bool
    source_artifact: str
    source_sha256: str
    content_sha256: str


class AccountRecord(RecordMetadata):
    payload: AccountOverviewPayload


class PnLRecord(RecordMetadata):
    payload: DailyPnLPayload


class PositionRecord(RecordMetadata):
    payload: PositionPayload


class RiskRecord(RecordMetadata):
    payload: RiskSummaryPayload


class StrategyRecord(RecordMetadata):
    payload: StrategyPayload


class ModelRecord(RecordMetadata):
    payload: ModelPayload


class OrderRecord(RecordMetadata):
    payload: OrderPayload


class DataHealthRecord(RecordMetadata):
    payload: DataHealthPayload


class EventRecord(RecordMetadata):
    payload: EventImpactPayload


class ClaimRecord(RecordMetadata):
    payload: ClaimEvidencePayload


class NarrativeRecord(RecordMetadata):
    payload: NarrativePayload


class SourceRecord(RecordMetadata):
    payload: SourcePolicyPayload


class PnLAttributionRecord(RecordMetadata):
    payload: PnLAttributionPayload


class RiskLimitRecord(RecordMetadata):
    payload: RiskLimitPayload


class ModelMetricRecord(RecordMetadata):
    payload: ModelMetricPayload


class SignalRecord(RecordMetadata):
    payload: SignalPayload


class FillRecord(RecordMetadata):
    payload: FillPayload


class ExecutionQualityRecord(RecordMetadata):
    payload: ExecutionQualityPayload


class MarketStateRecord(RecordMetadata):
    payload: MarketStatePayload


class ResearchRunRecord(RecordMetadata):
    payload: ResearchRunPayload


class IncidentRecord(RecordMetadata):
    payload: IncidentPayload


class SystemHealthRecord(RecordMetadata):
    payload: SystemHealthPayload


class ReconciliationRecord(RecordMetadata):
    payload: ReconciliationPayload


class OrderTraceRecord(RecordMetadata):
    payload: OrderTracePayload


class AccountPage(DomainModel):
    items: tuple[AccountRecord, ...]
    page: PageMeta


class PositionPage(DomainModel):
    items: tuple[PositionRecord, ...]
    page: PageMeta


class StrategyPage(DomainModel):
    items: tuple[StrategyRecord, ...]
    page: PageMeta


class ModelPage(DomainModel):
    items: tuple[ModelRecord, ...]
    page: PageMeta


class OrderPage(DomainModel):
    items: tuple[OrderRecord, ...]
    page: PageMeta


class DataHealthPage(DomainModel):
    items: tuple[DataHealthRecord, ...]
    page: PageMeta


class EventPage(DomainModel):
    items: tuple[EventRecord, ...]
    page: PageMeta


class NarrativePage(DomainModel):
    items: tuple[NarrativeRecord, ...]
    page: PageMeta


class SourcePage(DomainModel):
    items: tuple[SourceRecord, ...]
    page: PageMeta


class SignalPage(DomainModel):
    items: tuple[SignalRecord, ...]
    page: PageMeta


class FillPage(DomainModel):
    items: tuple[FillRecord, ...]
    page: PageMeta


class MarketStatePage(DomainModel):
    items: tuple[MarketStateRecord, ...]
    page: PageMeta


class ResearchRunPage(DomainModel):
    items: tuple[ResearchRunRecord, ...]
    page: PageMeta


class IncidentPage(DomainModel):
    items: tuple[IncidentRecord, ...]
    page: PageMeta


class SystemHealthPage(DomainModel):
    items: tuple[SystemHealthRecord, ...]
    page: PageMeta


class WorkbenchCapabilities(DomainModel):
    read_only: Literal[True]
    trading_write: Literal[False]
    real_account_connection: Literal[False]
    risk_limit_edit: Literal[False]
    model_publish: Literal[False]
    live_unlock: Literal[False]


class WorkbenchResponse(DomainModel):
    account: AccountRecord
    pnl: PnLRecord
    pnl_attribution: PnLAttributionRecord
    positions: tuple[PositionRecord, ...]
    risk: RiskRecord
    risk_limits: tuple[RiskLimitRecord, ...]
    strategies: tuple[StrategyRecord, ...]
    models: tuple[ModelRecord, ...]
    model_metrics: tuple[ModelMetricRecord, ...]
    signals: tuple[SignalRecord, ...]
    orders: tuple[OrderRecord, ...]
    fills: tuple[FillRecord, ...]
    execution_quality: tuple[ExecutionQualityRecord, ...]
    market: tuple[MarketStateRecord, ...]
    events: tuple[EventRecord, ...]
    claims: tuple[ClaimRecord, ...]
    narratives: tuple[NarrativeRecord, ...]
    sources: tuple[SourceRecord, ...]
    data_health: tuple[DataHealthRecord, ...]
    research_runs: tuple[ResearchRunRecord, ...]
    incidents: tuple[IncidentRecord, ...]
    system_health: tuple[SystemHealthRecord, ...]
    reconciliation: ReconciliationRecord
    order_traces: tuple[OrderTraceRecord, ...]
    snapshot_sha256: str
    capabilities: WorkbenchCapabilities
    live_trading_locked: Literal[True]


class TimeSeriesResponse(DomainModel):
    series_id: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=64)
    original_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    downsampled: bool
    algorithm: Literal["none", "min-max-bucket-v1"]
    points: tuple[TimeValuePoint, ...]
    source_sha256: str


class CandleSeriesResponse(DomainModel):
    market_id: str = Field(min_length=1, max_length=255)
    original_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    downsampled: bool
    algorithm: Literal["none", "min-max-bucket-v1"]
    candles: tuple[CandlePoint, ...]
    source_sha256: str


class OverviewResponse(DomainModel):
    account: AccountRecord
    pnl: PnLRecord
    positions: tuple[PositionRecord, ...]
    risk: RiskRecord
    strategies: tuple[StrategyRecord, ...]
    models: tuple[ModelRecord, ...]
    orders: tuple[OrderRecord, ...]
    data_health: tuple[DataHealthRecord, ...]
    snapshot_sha256: str
    live_trading_locked: Literal[True]


class IntelligenceResponse(DomainModel):
    events: tuple[EventRecord, ...]
    claims: tuple[ClaimRecord, ...]
    narratives: tuple[NarrativeRecord, ...]
    sources: tuple[SourceRecord, ...]
    snapshot_sha256: str
    live_trading_locked: Literal[True]


class HealthResponse(DomainModel):
    status: Literal["ok", "degraded"]
    service: Literal["aegisquant-read-api"]
    version: Literal["3.1.0.dev0"]
    read_model_records: int = Field(ge=0)
    read_model_snapshot_sha256: str
    live_trading_locked: Literal[True]
    real_account_connected: Literal[False]
    trading_write_capability: Literal[False]


class StreamSubscribe(DomainModel):
    action: Literal["subscribe"]
    schema_version: Literal["1"]
    topics: tuple[str, ...] = Field(min_length=1, max_length=16)


class StreamEvent(DomainModel):
    schema_version: Literal["1"] = "1"
    message_type: Literal["snapshot", "increment", "heartbeat"]
    topic: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=255)
    event_time: UtcDateTime
    server_time: UtcDateTime
    sequence: int = Field(ge=0)
    payload: dict[str, JsonValue]


class StreamSnapshotResponse(DomainModel):
    schema_version: Literal["1"] = "1"
    messages: tuple[StreamEvent, ...]
    recovery_required: Literal[False] = False
