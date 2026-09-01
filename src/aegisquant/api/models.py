"""Versioned P14 HTTP response contracts generated into the web client."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.readmodels.models import (
    AccountOverviewPayload,
    ClaimEvidencePayload,
    DailyPnLPayload,
    DataHealthPayload,
    EventImpactPayload,
    ModelPayload,
    NarrativePayload,
    OrderPayload,
    PositionPayload,
    ProjectionKind,
    QualityState,
    RiskSummaryPayload,
    SourcePolicyPayload,
    StrategyPayload,
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
