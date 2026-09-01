"""Read-only P14 REST and WebSocket routes over one immutable snapshot."""
# pyright: reportUnusedFunction=false

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final, cast

from fastapi import APIRouter, Query, WebSocket

from aegisquant.api.models import (
    AccountPage,
    AccountRecord,
    ClaimRecord,
    DataHealthPage,
    DataHealthRecord,
    EventPage,
    EventRecord,
    HealthResponse,
    IntelligenceResponse,
    ModelPage,
    ModelRecord,
    NarrativePage,
    NarrativeRecord,
    OrderPage,
    OrderRecord,
    OverviewResponse,
    PageMeta,
    PnLRecord,
    PositionPage,
    PositionRecord,
    RecordMetadata,
    RiskRecord,
    SourcePage,
    SourceRecord,
    StrategyPage,
    StrategyRecord,
    StreamSnapshotResponse,
)
from aegisquant.api.stream import TOPIC_PROJECTIONS, SequencedStream, websocket_session
from aegisquant.readmodels.engine import ReadModelQuery
from aegisquant.readmodels.models import ProjectionKind, QualityState, ReadModelRecord

DEFAULT_STREAM_TOPICS: Final = tuple(TOPIC_PROJECTIONS)


class APIContractError(Exception):
    """Expected client-facing failure with a stable code and HTTP status."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _as_record(record: ReadModelRecord, model: type[RecordMetadata]) -> RecordMetadata:
    return model.model_validate_json(record.model_dump_json())


def _required(query: ReadModelQuery, projection: ProjectionKind, entity_id: str) -> ReadModelRecord:
    record = query.get(projection, entity_id)
    if record is None:
        raise APIContractError(404, "AQ-API-NOT-FOUND", "The requested read model was not found.")
    return record


def _first(query: ReadModelQuery, projection: ProjectionKind) -> ReadModelRecord:
    records, _, _ = query.page(projection, limit=1)
    if not records:
        raise APIContractError(
            503, "AQ-API-PROJECTION-UNAVAILABLE", "The required projection is unavailable."
        )
    return records[0]


def _page(
    query: ReadModelQuery,
    projection: ProjectionKind,
    *,
    limit: int,
    cursor: str | None,
    filters: dict[str, str] | None = None,
    quality_state: QualityState | None = None,
) -> tuple[tuple[ReadModelRecord, ...], PageMeta]:
    try:
        records, next_cursor, total = query.page(
            projection,
            limit=limit,
            cursor=cursor,
            filters=filters,
            quality_state=quality_state,
        )
    except ValueError as error:
        code = str(error)
        if not code.startswith("AQ-API-"):
            code = "AQ-API-INVALID-QUERY"
        raise APIContractError(400, code, "The pagination or filter query is invalid.") from error
    return records, PageMeta(limit=limit, total=total, next_cursor=next_cursor)


def create_router(query: ReadModelQuery, stream: SequencedStream) -> APIRouter:
    """Bind routes to a prevalidated immutable snapshot."""
    router = APIRouter(prefix="/api/v1")

    @router.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        degraded = any(
            record.quality_state is not QualityState.LIVE for record in query.snapshot.records
        )
        return HealthResponse(
            status="degraded" if degraded else "ok",
            service="aegisquant-read-api",
            version="3.1.0.dev0",
            read_model_records=len(query.snapshot.records),
            read_model_snapshot_sha256=query.snapshot.content_sha256,
            live_trading_locked=True,
            real_account_connected=False,
            trading_write_capability=False,
        )

    @router.get("/overview", response_model=OverviewResponse, tags=["dashboard"])
    async def overview() -> OverviewResponse:
        account = cast(
            "AccountRecord",
            _as_record(_first(query, ProjectionKind.ACCOUNT_OVERVIEW), AccountRecord),
        )
        pnl = cast("PnLRecord", _as_record(_first(query, ProjectionKind.DAILY_PNL), PnLRecord))
        risk = cast(
            "RiskRecord", _as_record(_first(query, ProjectionKind.RISK_SUMMARY), RiskRecord)
        )
        positions = tuple(
            cast("PositionRecord", _as_record(item, PositionRecord))
            for item in query.page(ProjectionKind.POSITIONS_CURRENT, limit=100)[0]
        )
        strategies = tuple(
            cast("StrategyRecord", _as_record(item, StrategyRecord))
            for item in query.page(ProjectionKind.STRATEGIES, limit=100)[0]
        )
        models = tuple(
            cast("ModelRecord", _as_record(item, ModelRecord))
            for item in query.page(ProjectionKind.MODELS, limit=100)[0]
        )
        orders = tuple(
            cast("OrderRecord", _as_record(item, OrderRecord))
            for item in query.page(ProjectionKind.ORDERS, limit=100)[0]
        )
        data_health = tuple(
            cast("DataHealthRecord", _as_record(item, DataHealthRecord))
            for item in query.page(ProjectionKind.DATA_HEALTH, limit=100)[0]
        )
        return OverviewResponse(
            account=account,
            pnl=pnl,
            positions=positions,
            risk=risk,
            strategies=strategies,
            models=models,
            orders=orders,
            data_health=data_health,
            snapshot_sha256=query.snapshot.content_sha256,
            live_trading_locked=True,
        )

    @router.get("/accounts", response_model=AccountPage, tags=["account"])
    async def accounts(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        quality_state: QualityState | None = None,
    ) -> AccountPage:
        records, page = _page(
            query,
            ProjectionKind.ACCOUNT_OVERVIEW,
            limit=limit,
            cursor=cursor,
            quality_state=quality_state,
        )
        return AccountPage(
            items=tuple(cast("AccountRecord", _as_record(item, AccountRecord)) for item in records),
            page=page,
        )

    @router.get("/accounts/{account_id}", response_model=AccountRecord, tags=["account"])
    async def account(account_id: str) -> AccountRecord:
        return cast(
            "AccountRecord",
            _as_record(
                _required(query, ProjectionKind.ACCOUNT_OVERVIEW, account_id), AccountRecord
            ),
        )

    @router.get("/accounts/{account_id}/pnl", response_model=PnLRecord, tags=["account"])
    async def account_pnl(account_id: str) -> PnLRecord:
        records, _, _ = query.page(
            ProjectionKind.DAILY_PNL, limit=100, filters={"account_id": account_id}
        )
        if not records:
            raise APIContractError(404, "AQ-API-NOT-FOUND", "Account PnL was not found.")
        return cast("PnLRecord", _as_record(records[-1], PnLRecord))

    @router.get("/positions", response_model=PositionPage, tags=["portfolio"])
    async def positions(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        account_id: str | None = None,
        instrument_id: str | None = None,
        strategy_id: str | None = None,
        quality_state: QualityState | None = None,
    ) -> PositionPage:
        filters = {
            key: value
            for key, value in {
                "account_id": account_id,
                "instrument_id": instrument_id,
                "strategy_id": strategy_id,
            }.items()
            if value is not None
        }
        records, page = _page(
            query,
            ProjectionKind.POSITIONS_CURRENT,
            limit=limit,
            cursor=cursor,
            filters=filters,
            quality_state=quality_state,
        )
        return PositionPage(
            items=tuple(
                cast("PositionRecord", _as_record(item, PositionRecord)) for item in records
            ),
            page=page,
        )

    @router.get("/risk/summary", response_model=RiskRecord, tags=["risk"])
    async def risk_summary(account_id: str | None = None) -> RiskRecord:
        record = (
            _required(query, ProjectionKind.RISK_SUMMARY, account_id)
            if account_id is not None
            else _first(query, ProjectionKind.RISK_SUMMARY)
        )
        return cast("RiskRecord", _as_record(record, RiskRecord))

    @router.get("/strategies", response_model=StrategyPage, tags=["research"])
    async def strategies(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        status: str | None = None,
        quality_state: QualityState | None = None,
    ) -> StrategyPage:
        filters = {"status": status} if status is not None else None
        records, page = _page(
            query,
            ProjectionKind.STRATEGIES,
            limit=limit,
            cursor=cursor,
            filters=filters,
            quality_state=quality_state,
        )
        return StrategyPage(
            items=tuple(
                cast("StrategyRecord", _as_record(item, StrategyRecord)) for item in records
            ),
            page=page,
        )

    @router.get("/models", response_model=ModelPage, tags=["research"])
    async def models(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        status: str | None = None,
        quality_state: QualityState | None = None,
    ) -> ModelPage:
        filters = {"status": status} if status is not None else None
        records, page = _page(
            query,
            ProjectionKind.MODELS,
            limit=limit,
            cursor=cursor,
            filters=filters,
            quality_state=quality_state,
        )
        return ModelPage(
            items=tuple(cast("ModelRecord", _as_record(item, ModelRecord)) for item in records),
            page=page,
        )

    @router.get("/orders", response_model=OrderPage, tags=["execution"])
    async def orders(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        account_id: str | None = None,
        strategy_id: str | None = None,
        status: str | None = None,
        quality_state: QualityState | None = None,
    ) -> OrderPage:
        filters = {
            key: value
            for key, value in {
                "account_id": account_id,
                "strategy_id": strategy_id,
                "status": status,
            }.items()
            if value is not None
        }
        records, page = _page(
            query,
            ProjectionKind.ORDERS,
            limit=limit,
            cursor=cursor,
            filters=filters,
            quality_state=quality_state,
        )
        return OrderPage(
            items=tuple(cast("OrderRecord", _as_record(item, OrderRecord)) for item in records),
            page=page,
        )

    @router.get("/data/health", response_model=DataHealthPage, tags=["data"])
    async def data_health(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        state: str | None = None,
        quality_state: QualityState | None = None,
    ) -> DataHealthPage:
        filters = {"state": state} if state is not None else None
        records, page = _page(
            query,
            ProjectionKind.DATA_HEALTH,
            limit=limit,
            cursor=cursor,
            filters=filters,
            quality_state=quality_state,
        )
        return DataHealthPage(
            items=tuple(
                cast("DataHealthRecord", _as_record(item, DataHealthRecord)) for item in records
            ),
            page=page,
        )

    @router.get(
        "/intelligence/overview", response_model=IntelligenceResponse, tags=["intelligence"]
    )
    async def intelligence_overview() -> IntelligenceResponse:
        return IntelligenceResponse(
            events=tuple(
                cast("EventRecord", _as_record(item, EventRecord))
                for item in query.page(ProjectionKind.EVENT_CLUSTERS, limit=100)[0]
            ),
            claims=tuple(
                cast("ClaimRecord", _as_record(item, ClaimRecord))
                for item in query.page(ProjectionKind.EVENT_CLAIMS, limit=100)[0]
            ),
            narratives=tuple(
                cast("NarrativeRecord", _as_record(item, NarrativeRecord))
                for item in query.page(ProjectionKind.NARRATIVE_STATES, limit=100)[0]
            ),
            sources=tuple(
                cast("SourceRecord", _as_record(item, SourceRecord))
                for item in query.page(ProjectionKind.SOURCE_POLICY_STATUS, limit=100)[0]
            ),
            snapshot_sha256=query.snapshot.content_sha256,
            live_trading_locked=True,
        )

    @router.get("/intelligence/events", response_model=EventPage, tags=["intelligence"])
    async def events(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        status: str | None = None,
        quality_state: QualityState | None = None,
    ) -> EventPage:
        filters = {"status": status} if status is not None else None
        records, page = _page(
            query,
            ProjectionKind.EVENT_CLUSTERS,
            limit=limit,
            cursor=cursor,
            filters=filters,
            quality_state=quality_state,
        )
        return EventPage(
            items=tuple(cast("EventRecord", _as_record(item, EventRecord)) for item in records),
            page=page,
        )

    @router.get(
        "/intelligence/events/{event_cluster_id}",
        response_model=EventRecord,
        tags=["intelligence"],
    )
    async def event(event_cluster_id: str) -> EventRecord:
        return cast(
            "EventRecord",
            _as_record(
                _required(query, ProjectionKind.EVENT_CLUSTERS, event_cluster_id), EventRecord
            ),
        )

    @router.get(
        "/intelligence/events/{event_cluster_id}/evidence",
        response_model=tuple[ClaimRecord, ...],
        tags=["intelligence"],
    )
    async def event_evidence(event_cluster_id: str) -> tuple[ClaimRecord, ...]:
        if query.get(ProjectionKind.EVENT_CLUSTERS, event_cluster_id) is None:
            raise APIContractError(404, "AQ-API-NOT-FOUND", "Event cluster was not found.")
        records, _, _ = query.page(
            ProjectionKind.EVENT_CLAIMS,
            limit=100,
            filters={"event_cluster_id": event_cluster_id},
        )
        return tuple(cast("ClaimRecord", _as_record(item, ClaimRecord)) for item in records)

    @router.get("/intelligence/narratives", response_model=NarrativePage, tags=["intelligence"])
    async def narratives(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        quality_state: QualityState | None = None,
    ) -> NarrativePage:
        records, page = _page(
            query,
            ProjectionKind.NARRATIVE_STATES,
            limit=limit,
            cursor=cursor,
            quality_state=quality_state,
        )
        return NarrativePage(
            items=tuple(
                cast("NarrativeRecord", _as_record(item, NarrativeRecord)) for item in records
            ),
            page=page,
        )

    @router.get("/intelligence/sources", response_model=SourcePage, tags=["intelligence"])
    async def sources(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        quality_state: QualityState | None = None,
    ) -> SourcePage:
        records, page = _page(
            query,
            ProjectionKind.SOURCE_POLICY_STATUS,
            limit=limit,
            cursor=cursor,
            quality_state=quality_state,
        )
        return SourcePage(
            items=tuple(cast("SourceRecord", _as_record(item, SourceRecord)) for item in records),
            page=page,
        )

    @router.get("/stream/snapshot", response_model=StreamSnapshotResponse, tags=["stream"])
    async def stream_snapshot(
        topics: Annotated[
            str | None,
            Query(description="Comma-separated stream topics; omitted returns every topic."),
        ] = None,
    ) -> StreamSnapshotResponse:
        try:
            selected = (
                DEFAULT_STREAM_TOPICS
                if not topics
                else tuple(item.strip() for item in topics.split(",") if item.strip())
            )
            return stream.snapshots(selected, server_time=datetime.now(UTC))
        except ValueError as error:
            raise APIContractError(
                400, "AQ-API-INVALID-TOPIC", "One or more stream topics are invalid."
            ) from error

    return router


def create_websocket_router(stream: SequencedStream) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/v1/stream")
    async def websocket_stream(websocket: WebSocket) -> None:
        await websocket_session(websocket, stream)

    return router
