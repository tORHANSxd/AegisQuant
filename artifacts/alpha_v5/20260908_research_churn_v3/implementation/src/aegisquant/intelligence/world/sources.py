"""Allow-listed P10 macro, on-chain, SQL, official, and social source contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Final, cast
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from aegisquant.config.models import SECRET_KEY_RE
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.values import FiniteDecimal
from aegisquant.intelligence.world.models import (
    RuntimeSourceState,
    SourceCatalogEntry,
    SourceTier,
    WorldSource,
)


class EndpointTransport(StrEnum):
    HTTPS = "HTTPS"
    WEBSOCKET = "WEBSOCKET"


class EndpointContract(DomainModel):
    capability: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    path_template: str = Field(min_length=1)
    transport: EndpointTransport
    allowed_parameters: frozenset[str]
    required_parameters: frozenset[str] = frozenset()
    credentials_required: bool
    quota_cost: int = Field(ge=0)
    api_version: str | None = None

    @model_validator(mode="after")
    def official_transport_only(self) -> EndpointContract:
        parsed = urlsplit(self.base_url)
        expected = "https" if self.transport is EndpointTransport.HTTPS else "wss"
        if parsed.scheme != expected or parsed.username or parsed.password or parsed.query:
            raise ValueError("source endpoint must use an official credential-free base URL")
        return self


def _endpoint(
    capability: str,
    base_url: str,
    path: str,
    allowed: set[str],
    *,
    required: set[str] | None = None,
    credentials: bool = False,
    quota_cost: int = 1,
    api_version: str | None = None,
    transport: EndpointTransport = EndpointTransport.HTTPS,
) -> EndpointContract:
    return EndpointContract(
        capability=capability,
        base_url=base_url,
        path_template=path,
        transport=transport,
        allowed_parameters=frozenset(allowed),
        required_parameters=frozenset(required or set()),
        credentials_required=credentials,
        quota_cost=quota_cost,
        api_version=api_version,
    )


WORLD_ENDPOINTS: Final = MappingProxyType(
    {
        WorldSource.FRED_ALFRED: MappingProxyType(
            {
                "series_observations": _endpoint(
                    "series_observations",
                    "https://api.stlouisfed.org",
                    "/fred/series/observations",
                    {
                        "series_id",
                        "file_type",
                        "observation_start",
                        "observation_end",
                        "realtime_start",
                        "realtime_end",
                        "vintage_dates",
                        "output_type",
                        "units",
                        "frequency",
                    },
                    required={"series_id", "file_type"},
                    credentials=True,
                ),
                "series_vintage_dates": _endpoint(
                    "series_vintage_dates",
                    "https://api.stlouisfed.org",
                    "/fred/series/vintagedates",
                    {"series_id", "file_type", "realtime_start", "realtime_end"},
                    required={"series_id", "file_type"},
                    credentials=True,
                ),
            }
        ),
        WorldSource.COIN_METRICS: MappingProxyType(
            {
                "asset_metrics": _endpoint(
                    "asset_metrics",
                    "https://community-api.coinmetrics.io",
                    "/v4/timeseries/asset-metrics",
                    {"assets", "metrics", "start_time", "end_time", "frequency", "page_size"},
                    required={"assets", "metrics"},
                    api_version="v4",
                ),
                "catalog_assets": _endpoint(
                    "catalog_assets",
                    "https://community-api.coinmetrics.io",
                    "/v4/catalog/assets",
                    {"assets", "page_size"},
                    api_version="v4",
                ),
            }
        ),
        WorldSource.DUNE: MappingProxyType(
            {
                "execute_saved_query": _endpoint(
                    "execute_saved_query",
                    "https://api.dune.com",
                    "/api/v1/query/{query_id}/execute",
                    {"query_id", "performance", "query_parameters"},
                    required={"query_id"},
                    credentials=True,
                    api_version="v1",
                ),
                "execution_status": _endpoint(
                    "execution_status",
                    "https://api.dune.com",
                    "/api/v1/execution/{execution_id}/status",
                    {"execution_id"},
                    required={"execution_id"},
                    credentials=True,
                    api_version="v1",
                ),
                "execution_results": _endpoint(
                    "execution_results",
                    "https://api.dune.com",
                    "/api/v1/execution/{execution_id}/results",
                    {"execution_id", "limit", "offset"},
                    required={"execution_id"},
                    credentials=True,
                    api_version="v1",
                ),
            }
        ),
        WorldSource.DEFILLAMA: MappingProxyType(
            {
                "protocols": _endpoint("protocols", "https://api.llama.fi", "/protocols", set()),
                "protocol": _endpoint(
                    "protocol",
                    "https://api.llama.fi",
                    "/protocol/{protocol}",
                    {"protocol"},
                    required={"protocol"},
                ),
                "chain_tvl": _endpoint(
                    "chain_tvl",
                    "https://api.llama.fi",
                    "/v2/historicalChainTvl/{chain}",
                    {"chain"},
                    required={"chain"},
                ),
                "chains": _endpoint("chains", "https://api.llama.fi", "/v2/chains", set()),
            }
        ),
        WorldSource.GDELT: MappingProxyType(
            {
                "document_discovery": _endpoint(
                    "document_discovery",
                    "https://api.gdeltproject.org",
                    "/api/v2/doc/doc",
                    {
                        "query",
                        "mode",
                        "format",
                        "maxrecords",
                        "startdatetime",
                        "enddatetime",
                        "sort",
                    },
                    required={"query", "mode", "format"},
                )
            }
        ),
        WorldSource.X: MappingProxyType(
            {
                "filtered_stream": _endpoint(
                    "filtered_stream",
                    "https://api.x.com",
                    "/2/tweets/search/stream",
                    {"tweet.fields", "expansions", "user.fields", "backfill_minutes"},
                    credentials=True,
                    api_version="2",
                )
            }
        ),
        WorldSource.TELEGRAM: MappingProxyType(
            {
                "updates": _endpoint(
                    "updates",
                    "https://api.telegram.org",
                    "/bot{credential}/getUpdates",
                    {"offset", "limit", "timeout", "allowed_updates"},
                    credentials=True,
                )
            }
        ),
        WorldSource.BLUESKY: MappingProxyType(
            {
                "jetstream_v2": _endpoint(
                    "jetstream_v2",
                    "wss://jetstream2.us-east.bsky.network",
                    "/xrpc/network.bsky.jetstream.subscribeEvents",
                    {"kinds", "dids", "collections", "cursor", "maxMessageSizeBytes"},
                    transport=EndpointTransport.WEBSOCKET,
                    api_version="v2",
                ),
                "jetstream_v1_legacy": _endpoint(
                    "jetstream_v1_legacy",
                    "wss://jetstream2.us-east.bsky.network",
                    "/subscribe",
                    {"wantedCollections", "wantedDids", "cursor", "compress"},
                    transport=EndpointTransport.WEBSOCKET,
                    api_version="v1-legacy",
                ),
            }
        ),
        WorldSource.YOUTUBE: MappingProxyType(
            {
                "videos": _endpoint(
                    "videos",
                    "https://www.googleapis.com",
                    "/youtube/v3/videos",
                    {"part", "id", "chart", "regionCode", "maxResults", "pageToken"},
                    required={"part"},
                    credentials=True,
                    quota_cost=1,
                    api_version="v3",
                )
            }
        ),
        WorldSource.GITHUB: MappingProxyType(
            {
                "releases": _endpoint(
                    "releases",
                    "https://api.github.com",
                    "/repos/{owner}/{repo}/releases",
                    {"owner", "repo", "per_page", "page"},
                    required={"owner", "repo"},
                    api_version="2026-03-10",
                )
            }
        ),
    }
)


class WorldSourceRequest(DomainModel):
    source: WorldSource
    capability: str
    base_url: str
    path_template: str
    parameters: dict[str, str | int]
    headers: dict[str, str]
    quota_cost: int = Field(ge=0)
    runtime_state: RuntimeSourceState
    executable: bool
    request_hash: str


def build_world_request(
    source: WorldSource,
    capability: str,
    parameters: Mapping[str, str | int] | None = None,
    *,
    secret_key_name: str | None = None,
    user_approved: bool = True,
) -> WorldSourceRequest:
    endpoints = WORLD_ENDPOINTS.get(source)
    endpoint = endpoints.get(capability) if endpoints is not None else None
    if endpoint is None:
        raise ValueError("AQ-WORLD-SOURCE-CAPABILITY-DENIED")
    normalized = dict(parameters or {})
    forbidden = {"key", "api_key", "apikey", "token", "secret", "cookie", "authorization"}
    if any(key.casefold() in forbidden for key in normalized):
        raise ValueError("AQ-WORLD-PLAINTEXT-CREDENTIAL-DENIED")
    unknown = sorted(set(normalized) - endpoint.allowed_parameters)
    missing = sorted(endpoint.required_parameters - set(normalized))
    if unknown or missing:
        raise ValueError(f"AQ-WORLD-SOURCE-PARAMETERS: unknown={unknown}, missing={missing}")
    if secret_key_name is not None and SECRET_KEY_RE.fullmatch(secret_key_name) is None:
        raise ValueError("secret_key_name must be an environment secret reference name")
    if endpoint.credentials_required and secret_key_name is None:
        state = RuntimeSourceState.AWAITING_CREDENTIALS
    elif not user_approved:
        state = RuntimeSourceState.AWAITING_USER_APPROVAL
    else:
        state = RuntimeSourceState.READY
    headers: dict[str, str] = {}
    if source is WorldSource.GITHUB and endpoint.api_version is not None:
        headers["X-GitHub-Api-Version"] = endpoint.api_version
    request_hash = canonical_sha256(
        {
            "source": source.value,
            "capability": capability,
            "base_url": endpoint.base_url,
            "path_template": endpoint.path_template,
            "parameters": normalized,
            "api_version": endpoint.api_version,
            "secret_reference_configured": secret_key_name is not None,
            "user_approved": user_approved,
        }
    )
    return WorldSourceRequest(
        source=source,
        capability=capability,
        base_url=endpoint.base_url,
        path_template=endpoint.path_template,
        parameters=normalized,
        headers=headers,
        quota_cost=endpoint.quota_cost,
        runtime_state=state,
        executable=state is RuntimeSourceState.READY,
        request_hash=request_hash,
    )


class VintageObservation(DomainModel):
    series_id: str = Field(min_length=1)
    observation_date: date
    realtime_start: date
    realtime_end: date
    available_at: UtcDateTime
    value: FiniteDecimal | None
    is_missing: bool
    source_hash: str

    @model_validator(mode="after")
    def validate_missing_value(self) -> VintageObservation:
        if self.is_missing != (self.value is None):
            raise ValueError("ALFRED missing-value flag and value disagree")
        if len(self.source_hash) != 64:
            raise ValueError("ALFRED source hash must be SHA-256")
        return self


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object with text keys")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{field} must be an object with text keys")
    return {cast(str, key): item for key, item in raw.items()}


def _objects(value: object, field: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return tuple(_object(item, field) for item in cast(list[object], value))


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(_required_text(value, field))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def parse_alfred_observations(
    payload: Mapping[str, object],
    *,
    series_id: str,
    vintage_available_at: Mapping[date, datetime],
) -> tuple[VintageObservation, ...]:
    if not series_id:
        raise ValueError("series_id is required")
    observations = _objects(payload.get("observations"), "observations")
    parsed: list[VintageObservation] = []
    for row in observations:
        realtime_start = _date(row.get("realtime_start"), "realtime_start")
        realtime_end = _date(row.get("realtime_end"), "realtime_end")
        available = vintage_available_at.get(realtime_start)
        if available is None:
            raise ValueError("AQ-ALFRED-VINTAGE-AVAILABLE-TIME-REQUIRED")
        raw_value = _required_text(row.get("value"), "value")
        missing = raw_value == "."
        try:
            value = None if missing else Decimal(raw_value)
        except InvalidOperation as exc:
            raise ValueError("ALFRED value must be finite decimal or '.'") from exc
        if value is not None and not value.is_finite():
            raise ValueError("ALFRED value must be finite")
        identity = {
            "series_id": series_id,
            "date": _required_text(row.get("date"), "date"),
            "realtime_start": realtime_start.isoformat(),
            "realtime_end": realtime_end.isoformat(),
            "value": raw_value,
        }
        parsed.append(
            VintageObservation(
                series_id=series_id,
                observation_date=_date(row.get("date"), "date"),
                realtime_start=realtime_start,
                realtime_end=realtime_end,
                available_at=ensure_utc(available),
                value=value,
                is_missing=missing,
                source_hash=canonical_sha256(identity),
            )
        )
    return tuple(sorted(parsed, key=lambda item: (item.observation_date, item.available_at)))


def select_alfred_vintage(
    observations: Sequence[VintageObservation], *, as_of_time: datetime
) -> tuple[VintageObservation, ...]:
    as_of = ensure_utc(as_of_time)
    selected: dict[tuple[str, date], VintageObservation] = {}
    for item in observations:
        if item.available_at > as_of:
            continue
        key = (item.series_id, item.observation_date)
        current = selected.get(key)
        if current is None or current.available_at < item.available_at:
            selected[key] = item
    return tuple(
        sorted(selected.values(), key=lambda item: (item.series_id, item.observation_date))
    )


class MetricObservation(DomainModel):
    source: WorldSource
    asset_or_protocol: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    event_time: UtcDateTime
    available_at: UtcDateTime
    value: FiniteDecimal
    quality_status: str
    source_hash: str

    @model_validator(mode="after")
    def validate_metric_time(self) -> MetricObservation:
        if self.event_time > self.available_at:
            raise ValueError("metric cannot be available before event time")
        if len(self.source_hash) != 64:
            raise ValueError("metric source hash must be SHA-256")
        return self


def parse_coin_metrics(
    payload: Mapping[str, object], *, metric_names: tuple[str, ...], available_at: datetime
) -> tuple[MetricObservation, ...]:
    available = ensure_utc(available_at)
    results: list[MetricObservation] = []
    for row in _objects(payload.get("data"), "data"):
        asset = _required_text(row.get("asset"), "asset")
        event_time = ensure_utc(
            datetime.fromisoformat(_required_text(row.get("time"), "time").replace("Z", "+00:00"))
        )
        status = str(row.get("status") or "unknown")
        for metric in metric_names:
            raw = row.get(metric)
            if raw is None:
                continue
            try:
                value = Decimal(str(raw))
            except InvalidOperation as exc:
                raise ValueError("Coin Metrics value must be decimal") from exc
            identity = {
                "asset": asset,
                "metric": metric,
                "time": event_time.isoformat(),
                "value": str(raw),
            }
            results.append(
                MetricObservation(
                    source=WorldSource.COIN_METRICS,
                    asset_or_protocol=asset,
                    metric=metric,
                    event_time=event_time,
                    available_at=available,
                    value=value,
                    quality_status=status,
                    source_hash=canonical_sha256(identity),
                )
            )
    return tuple(results)


def parse_defillama_chain_tvl(
    payload: Sequence[Mapping[str, object]], *, chain: str, available_at: datetime
) -> tuple[MetricObservation, ...]:
    available = ensure_utc(available_at)
    results: list[MetricObservation] = []
    for raw_row in payload:
        row = dict(raw_row)
        raw_timestamp = row.get("date")
        if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, int):
            raise ValueError("DeFiLlama date must be Unix seconds")
        event_time = datetime.fromtimestamp(raw_timestamp, tz=UTC)
        try:
            value = Decimal(str(row.get("tvl")))
        except InvalidOperation as exc:
            raise ValueError("DeFiLlama TVL must be decimal") from exc
        results.append(
            MetricObservation(
                source=WorldSource.DEFILLAMA,
                asset_or_protocol=chain,
                metric="tvl_usd",
                event_time=event_time,
                available_at=available,
                value=value,
                quality_status="unreviewed_public",
                source_hash=canonical_sha256(
                    {"chain": chain, "date": raw_timestamp, "tvl": str(row.get("tvl"))}
                ),
            )
        )
    return tuple(results)


_SQL_WRITE_RE: Final = re.compile(
    r"\b(insert|update|delete|merge|alter|drop|create|grant|revoke|copy|call|execute|truncate)\b",
    re.IGNORECASE,
)


class DuneQueryVersion(DomainModel):
    query_id: int = Field(gt=0)
    version: int = Field(ge=1)
    name: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    sql_sha256: str
    parameter_names: tuple[str, ...]
    registered_at: UtcDateTime
    supersedes_version: int | None = None

    @model_validator(mode="after")
    def validate_query(self) -> DuneQueryVersion:
        normalized = self.sql.strip()
        without_comments = re.sub(r"(?m)--.*$|/\*.*?\*/", " ", normalized, flags=re.DOTALL).strip()
        if not re.match(r"^(select|with)\b", without_comments, flags=re.IGNORECASE):
            raise ValueError("Dune query must be read-only SELECT/WITH SQL")
        if _SQL_WRITE_RE.search(without_comments) or ";" in without_comments.rstrip(";"):
            raise ValueError("Dune query contains denied SQL operation or multiple statements")
        if self.sql_sha256 != canonical_sha256({"sql": normalized}):
            raise ValueError("Dune SQL hash does not match SQL text")
        if self.version == 1 and self.supersedes_version is not None:
            raise ValueError("first Dune version cannot supersede another")
        if self.version > 1 and self.supersedes_version != self.version - 1:
            raise ValueError("Dune query version must supersede its immediate predecessor")
        return self


def register_dune_query(
    *,
    query_id: int,
    version: int,
    name: str,
    sql: str,
    parameter_names: tuple[str, ...],
    registered_at: datetime,
    supersedes_version: int | None = None,
) -> DuneQueryVersion:
    normalized = sql.strip()
    return DuneQueryVersion(
        query_id=query_id,
        version=version,
        name=name,
        sql=normalized,
        sql_sha256=canonical_sha256({"sql": normalized}),
        parameter_names=tuple(sorted(set(parameter_names))),
        registered_at=ensure_utc(registered_at),
        supersedes_version=supersedes_version,
    )


class DuneResultManifest(DomainModel):
    query_id: int = Field(gt=0)
    query_version: int = Field(ge=1)
    sql_sha256: str
    parameters_sha256: str
    execution_id: str = Field(min_length=1)
    requested_at: UtcDateTime
    available_at: UtcDateTime
    result_sha256: str
    row_count: int = Field(ge=0)
    state: str = Field(
        pattern=r"^(QUERY_STATE_COMPLETED|QUERY_STATE_FAILED|QUERY_STATE_CANCELLED)$"
    )

    @model_validator(mode="after")
    def validate_result(self) -> DuneResultManifest:
        if self.available_at < self.requested_at:
            raise ValueError("Dune result cannot be available before request")
        if any(
            len(value) != 64
            for value in (self.sql_sha256, self.parameters_sha256, self.result_sha256)
        ):
            raise ValueError("Dune manifest hashes must be SHA-256")
        if self.state != "QUERY_STATE_COMPLETED" and self.row_count != 0:
            raise ValueError("failed or cancelled Dune result cannot expose rows")
        return self


def manifest_dune_result(
    *,
    query: DuneQueryVersion,
    parameters: Mapping[str, str | int],
    execution_id: str,
    requested_at: datetime,
    available_at: datetime,
    rows: Sequence[Mapping[str, object]],
    state: str = "QUERY_STATE_COMPLETED",
) -> DuneResultManifest:
    if set(parameters) != set(query.parameter_names):
        raise ValueError("Dune parameters must exactly match registered query schema")
    serializable_rows = [dict(row) for row in rows]
    return DuneResultManifest(
        query_id=query.query_id,
        query_version=query.version,
        sql_sha256=query.sql_sha256,
        parameters_sha256=canonical_sha256(dict(parameters)),
        execution_id=execution_id,
        requested_at=ensure_utc(requested_at),
        available_at=ensure_utc(available_at),
        result_sha256=canonical_sha256(serializable_rows),
        row_count=len(rows) if state == "QUERY_STATE_COMPLETED" else 0,
        state=state,
    )


class OriginalSourceDiscovery(DomainModel):
    discovery_id: str
    discovery_source: WorldSource
    original_url: str
    original_host: str
    discovered_at: UtcDateTime
    original_published_at: UtcDateTime | None
    title: str = Field(min_length=1)
    authoritative_evidence: bool = False

    @model_validator(mode="after")
    def discovery_is_not_authority(self) -> OriginalSourceDiscovery:
        if self.discovery_source is not WorldSource.GDELT or self.authoritative_evidence:
            raise ValueError("GDELT discovery cannot itself be authoritative evidence")
        parsed = urlsplit(self.original_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("GDELT original URL must be public HTTP(S)")
        if parsed.hostname.casefold().endswith("gdeltproject.org"):
            raise ValueError("GDELT result must trace to an original-source host")
        if parsed.hostname.casefold() != self.original_host.casefold():
            raise ValueError("GDELT original host does not match URL")
        return self


def gdelt_discover_originals(
    payload: Mapping[str, object], *, discovered_at: datetime
) -> tuple[OriginalSourceDiscovery, ...]:
    discovered = ensure_utc(discovered_at)
    results: list[OriginalSourceDiscovery] = []
    for row in _objects(payload.get("articles"), "articles"):
        url = _required_text(row.get("url"), "url")
        host = urlsplit(url).hostname or ""
        raw_seen = row.get("seendate")
        published = None
        if isinstance(raw_seen, str) and raw_seen:
            published = datetime.strptime(raw_seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        title = _required_text(row.get("title"), "title")
        results.append(
            OriginalSourceDiscovery(
                discovery_id=canonical_sha256(
                    {"url": url, "discovered_at": discovered.isoformat()}
                ),
                discovery_source=WorldSource.GDELT,
                original_url=url,
                original_host=host,
                discovered_at=discovered,
                original_published_at=published,
                title=title,
            )
        )
    return tuple(results)


class CursorGap(DomainModel):
    source: WorldSource
    expected_cursor: int = Field(ge=0)
    observed_cursor: int = Field(ge=0)
    detected_at: UtcDateTime
    earliest_recoverable_at: UtcDateTime | None
    missing_count: int = Field(ge=0)
    recoverable: bool
    action: str

    @model_validator(mode="after")
    def validate_gap(self) -> CursorGap:
        if self.observed_cursor <= self.expected_cursor:
            raise ValueError("gap requires observed cursor greater than expected cursor")
        if self.missing_count != self.observed_cursor - self.expected_cursor:
            raise ValueError("gap size does not match cursors")
        expected_action = "BACKFILL" if self.recoverable else "RECORD_PERMANENT_GAP"
        if self.action != expected_action:
            raise ValueError("gap action and recoverability disagree")
        return self


def plan_cursor_gap(
    *,
    source: WorldSource,
    expected_cursor: int,
    observed_cursor: int,
    detected_at: datetime,
    earliest_recoverable_at: datetime | None,
) -> CursorGap:
    detected = ensure_utc(detected_at)
    earliest = ensure_utc(earliest_recoverable_at) if earliest_recoverable_at else None
    recoverable = earliest is not None and earliest <= detected
    return CursorGap(
        source=source,
        expected_cursor=expected_cursor,
        observed_cursor=observed_cursor,
        detected_at=detected,
        earliest_recoverable_at=earliest,
        missing_count=observed_cursor - expected_cursor,
        recoverable=recoverable,
        action="BACKFILL" if recoverable else "RECORD_PERMANENT_GAP",
    )


class DegradationMode(StrEnum):
    NORMAL = "NORMAL"
    CACHED_POINT_IN_TIME = "CACHED_POINT_IN_TIME"
    LOCAL_RULES_ONLY = "LOCAL_RULES_ONLY"
    ABSTAIN = "ABSTAIN"


class IntelligenceDegradationPlan(DomainModel):
    source: WorldSource
    source_state: RuntimeSourceState
    llm_available: bool
    cache_available_at: UtcDateTime | None
    as_of_time: UtcDateTime
    mode: DegradationMode
    can_emit_forecast: bool
    action: str = "RESEARCH_PROPOSAL_ONLY"
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_degradation(self) -> IntelligenceDegradationPlan:
        if self.cache_available_at is not None and self.cache_available_at > self.as_of_time:
            raise ValueError("degradation plan cannot use future cache")
        if self.mode is DegradationMode.ABSTAIN and self.can_emit_forecast:
            raise ValueError("abstaining degradation plan cannot emit forecast")
        if self.action != "RESEARCH_PROPOSAL_ONLY":
            raise ValueError("degradation cannot widen execution boundary")
        return self


def plan_intelligence_degradation(
    *,
    source: WorldSource,
    source_state: RuntimeSourceState,
    llm_available: bool,
    cache_available_at: datetime | None,
    as_of_time: datetime,
) -> IntelligenceDegradationPlan:
    as_of = ensure_utc(as_of_time)
    cache_time = ensure_utc(cache_available_at) if cache_available_at is not None else None
    reasons: set[str] = set()
    if source_state is not RuntimeSourceState.READY:
        reasons.add(f"SOURCE_{source_state.value}")
    if not llm_available:
        reasons.add("LLM_UNAVAILABLE")
    if source_state is RuntimeSourceState.READY and llm_available:
        mode = DegradationMode.NORMAL
        can_emit = True
    elif cache_time is not None and cache_time <= as_of:
        mode = (
            DegradationMode.CACHED_POINT_IN_TIME
            if llm_available
            else DegradationMode.LOCAL_RULES_ONLY
        )
        can_emit = True
        reasons.add("STALE_CACHE_DISCLOSED")
    elif source_state is RuntimeSourceState.READY:
        mode = DegradationMode.LOCAL_RULES_ONLY
        can_emit = True
    else:
        mode = DegradationMode.ABSTAIN
        can_emit = False
        reasons.add("NO_POINT_IN_TIME_INPUT")
    return IntelligenceDegradationPlan(
        source=source,
        source_state=source_state,
        llm_available=llm_available,
        cache_available_at=cache_time,
        as_of_time=as_of,
        mode=mode,
        can_emit_forecast=can_emit,
        reason_codes=tuple(sorted(reasons)),
    )


def official_source_catalog(*, checked_at: datetime) -> tuple[SourceCatalogEntry, ...]:
    _ = ensure_utc(checked_at)
    entries = (
        ("fed", "central_bank", "www.federalreserve.gov", "US"),
        ("ecb", "central_bank", "www.ecb.europa.eu", "EU"),
        ("sec", "regulator", "www.sec.gov", "US"),
        ("cftc", "regulator", "www.cftc.gov", "US"),
        ("us_supreme_court", "court", "www.supremecourt.gov", "US"),
        ("binance_announcements", "exchange", "www.binance.com", "GLOBAL"),
        ("ethereum_foundation", "project", "ethereum.foundation", "GLOBAL"),
        ("blackrock_ishares", "etf_issuer", "www.ishares.com", "US"),
    )
    return tuple(
        SourceCatalogEntry(
            source_id=source_id,
            source=WorldSource.OFFICIAL,
            tier=SourceTier.OFFICIAL_PRIMARY,
            authority_type=authority_type,
            canonical_host=host,
            jurisdiction=jurisdiction,
            policy_id="official_public_metadata_v1",
            approved_capabilities=("announcement_discovery", "revision_snapshot"),
            runtime_state=RuntimeSourceState.READY,
            credentials_required=False,
        )
        for source_id, authority_type, host, jurisdiction in entries
    )


def default_social_catalog() -> tuple[SourceCatalogEntry, ...]:
    return (
        SourceCatalogEntry(
            source_id="x_official",
            source=WorldSource.X,
            tier=SourceTier.SOCIAL_OBSERVATION,
            authority_type="social_platform",
            canonical_host="api.x.com",
            jurisdiction="GLOBAL",
            policy_id="x_official_restricted_v1",
            approved_capabilities=("offline_contract",),
            runtime_state=RuntimeSourceState.AWAITING_CREDENTIALS,
            credentials_required=True,
        ),
        SourceCatalogEntry(
            source_id="telegram_bot",
            source=WorldSource.TELEGRAM,
            tier=SourceTier.SOCIAL_OBSERVATION,
            authority_type="approved_public_channel",
            canonical_host="api.telegram.org",
            jurisdiction="GLOBAL",
            policy_id="telegram_bot_restricted_v1",
            approved_capabilities=("offline_contract",),
            runtime_state=RuntimeSourceState.AWAITING_CREDENTIALS,
            credentials_required=True,
        ),
        SourceCatalogEntry(
            source_id="bluesky_jetstream",
            source=WorldSource.BLUESKY,
            tier=SourceTier.SOCIAL_OBSERVATION,
            authority_type="public_social_stream",
            canonical_host="jetstream2.us-east.bsky.network",
            jurisdiction="GLOBAL",
            policy_id="bluesky_jetstream_v2",
            approved_capabilities=("public_post_metadata", "revision", "deletion"),
            runtime_state=RuntimeSourceState.READY,
            credentials_required=False,
        ),
        SourceCatalogEntry(
            source_id="youtube_official",
            source=WorldSource.YOUTUBE,
            tier=SourceTier.SOCIAL_OBSERVATION,
            authority_type="video_metadata",
            canonical_host="www.googleapis.com",
            jurisdiction="GLOBAL",
            policy_id="youtube_official_restricted_v1",
            approved_capabilities=("offline_contract",),
            runtime_state=RuntimeSourceState.AWAITING_CREDENTIALS,
            credentials_required=True,
        ),
        SourceCatalogEntry(
            source_id="github_public",
            source=WorldSource.GITHUB,
            tier=SourceTier.STRUCTURED_PRIMARY,
            authority_type="project_release_metadata",
            canonical_host="api.github.com",
            jurisdiction="GLOBAL",
            policy_id="github_public_v1",
            approved_capabilities=("public_releases",),
            runtime_state=RuntimeSourceState.READY,
            credentials_required=False,
        ),
        SourceCatalogEntry(
            source_id="reddit_disabled",
            source=WorldSource.REDDIT,
            tier=SourceTier.DISABLED,
            authority_type="social_platform",
            canonical_host="reddit.com",
            jurisdiction="GLOBAL",
            policy_id="unknown_rights_deny_v1",
            approved_capabilities=(),
            runtime_state=RuntimeSourceState.DISABLED_BY_POLICY,
            credentials_required=False,
        ),
        SourceCatalogEntry(
            source_id="discord_disabled",
            source=WorldSource.DISCORD,
            tier=SourceTier.DISABLED,
            authority_type="private_community",
            canonical_host="discord.com",
            jurisdiction="GLOBAL",
            policy_id="unknown_rights_deny_v1",
            approved_capabilities=(),
            runtime_state=RuntimeSourceState.DISABLED_BY_POLICY,
            credentials_required=False,
        ),
    )


def conservative_vintage_available_at(vintage: date) -> datetime:
    """Return end-of-day UTC only for fixture planning; production must record actual ingestion."""
    return datetime.combine(vintage + timedelta(days=1), time.min, tzinfo=UTC)
