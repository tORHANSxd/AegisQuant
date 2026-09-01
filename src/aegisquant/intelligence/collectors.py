"""Official-source contracts and deterministic parsers for P04 event intelligence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, cast
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree  # nosec B405 -- bounded input rejects DTD/entity declarations

import httpx
from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.models import ProviderAccessState
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    ArtifactId,
    ContentId,
    ProviderId,
    ProviderNativeId,
    SourceIdentityId,
    SourcePolicyId,
)
from aegisquant.domain.intelligence import (
    ContentType,
    EngagementSnapshot,
    QualityState,
    RawContentEnvelope,
    RightsState,
    SourceIdentity,
)
from aegisquant.domain.time import UtcDateTime, ensure_utc


class SourceKind(StrEnum):
    RSS_ATOM = "rss_atom"
    GDELT = "gdelt"
    X = "x"
    TELEGRAM_BOT = "telegram_bot"
    BLUESKY_JETSTREAM = "bluesky_jetstream"
    GITHUB = "github"
    YOUTUBE = "youtube"


@dataclass(frozen=True, slots=True)
class SourceEndpoint:
    capability: str
    base_url: str
    path: str
    allowed_parameters: frozenset[str]
    required_parameters: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SourceContract:
    source: SourceKind
    provider_id: ProviderId
    endpoints: Mapping[str, SourceEndpoint]
    credentials_required: bool
    access_state: ProviderAccessState
    checkpoint_field: str
    revisions_supported: bool
    deletions_supported: bool


def _source_endpoint(
    capability: str,
    base_url: str,
    path: str,
    allowed: set[str],
    required: set[str] | None = None,
) -> SourceEndpoint:
    return SourceEndpoint(
        capability=capability,
        base_url=base_url,
        path=path,
        allowed_parameters=frozenset(allowed),
        required_parameters=frozenset(required or set()),
    )


SOURCE_CONTRACTS: Final = MappingProxyType(
    {
        SourceKind.RSS_ATOM: SourceContract(
            source=SourceKind.RSS_ATOM,
            provider_id=ProviderId("official_rss_atom"),
            endpoints=MappingProxyType(
                {
                    "federal_reserve": _source_endpoint(
                        "federal_reserve",
                        "https://www.federalreserve.gov",
                        "/feeds/press_all.xml",
                        set(),
                    ),
                    "ecb": _source_endpoint(
                        "ecb",
                        "https://www.ecb.europa.eu",
                        "/rss/press.html",
                        set(),
                    ),
                    "sec": _source_endpoint(
                        "sec",
                        "https://www.sec.gov",
                        "/news/pressreleases.rss",
                        set(),
                    ),
                }
            ),
            credentials_required=False,
            access_state=ProviderAccessState.READY,
            checkpoint_field="published_time+native_id",
            revisions_supported=True,
            deletions_supported=False,
        ),
        SourceKind.GDELT: SourceContract(
            source=SourceKind.GDELT,
            provider_id=ProviderId("gdelt_public"),
            endpoints=MappingProxyType(
                {
                    "doc": _source_endpoint(
                        "doc",
                        "https://api.gdeltproject.org",
                        "/api/v2/doc/doc",
                        {
                            "query",
                            "mode",
                            "maxrecords",
                            "format",
                            "startdatetime",
                            "enddatetime",
                            "sort",
                        },
                        {"query", "mode", "format"},
                    )
                }
            ),
            credentials_required=False,
            access_state=ProviderAccessState.READY,
            checkpoint_field="seendate+url",
            revisions_supported=False,
            deletions_supported=False,
        ),
        SourceKind.X: SourceContract(
            source=SourceKind.X,
            provider_id=ProviderId("x_official"),
            endpoints=MappingProxyType(
                {
                    "filtered_stream": _source_endpoint(
                        "filtered_stream",
                        "https://api.x.com",
                        "/2/tweets/search/stream",
                        {"tweet.fields", "expansions", "user.fields", "backfill_minutes"},
                    ),
                    "recent_search": _source_endpoint(
                        "recent_search",
                        "https://api.x.com",
                        "/2/tweets/search/recent",
                        {
                            "query",
                            "start_time",
                            "end_time",
                            "since_id",
                            "until_id",
                            "max_results",
                            "next_token",
                            "tweet.fields",
                            "expansions",
                            "user.fields",
                        },
                        {"query"},
                    ),
                    "full_archive_search": _source_endpoint(
                        "full_archive_search",
                        "https://api.x.com",
                        "/2/tweets/search/all",
                        {
                            "query",
                            "start_time",
                            "end_time",
                            "since_id",
                            "until_id",
                            "max_results",
                            "next_token",
                            "tweet.fields",
                            "expansions",
                            "user.fields",
                        },
                        {"query"},
                    ),
                }
            ),
            credentials_required=True,
            access_state=ProviderAccessState.AWAITING_CREDENTIALS,
            checkpoint_field="newest_id+next_token",
            revisions_supported=True,
            deletions_supported=True,
        ),
        SourceKind.TELEGRAM_BOT: SourceContract(
            source=SourceKind.TELEGRAM_BOT,
            provider_id=ProviderId("telegram_bot"),
            endpoints=MappingProxyType(
                {
                    "updates": _source_endpoint(
                        "updates",
                        "https://api.telegram.org",
                        "/bot{runtime_credential}/getUpdates",
                        {"offset", "limit", "timeout", "allowed_updates"},
                    )
                }
            ),
            credentials_required=True,
            access_state=ProviderAccessState.AWAITING_CREDENTIALS,
            checkpoint_field="update_id",
            revisions_supported=True,
            deletions_supported=False,
        ),
        SourceKind.BLUESKY_JETSTREAM: SourceContract(
            source=SourceKind.BLUESKY_JETSTREAM,
            provider_id=ProviderId("bluesky_jetstream"),
            endpoints=MappingProxyType(
                {
                    "stream": _source_endpoint(
                        "stream",
                        "wss://jetstream2.us-east.bsky.network",
                        "/xrpc/network.bsky.jetstream.subscribeEvents",
                        {"kinds", "dids", "collections", "cursor", "maxMessageSizeBytes"},
                    ),
                    "stream_v1_legacy": _source_endpoint(
                        "stream_v1_legacy",
                        "wss://jetstream2.us-east.bsky.network",
                        "/subscribe",
                        {"wantedCollections", "wantedDids", "cursor", "compress"},
                    ),
                }
            ),
            credentials_required=False,
            access_state=ProviderAccessState.READY,
            checkpoint_field="seq",
            revisions_supported=True,
            deletions_supported=True,
        ),
        SourceKind.GITHUB: SourceContract(
            source=SourceKind.GITHUB,
            provider_id=ProviderId("github_public"),
            endpoints=MappingProxyType(
                {
                    "releases": _source_endpoint(
                        "releases",
                        "https://api.github.com",
                        "/repos/{owner}/{repo}/releases",
                        {"owner", "repo", "per_page", "page"},
                        {"owner", "repo"},
                    ),
                    "security_advisories": _source_endpoint(
                        "security_advisories",
                        "https://api.github.com",
                        "/advisories",
                        {
                            "ghsa_id",
                            "type",
                            "ecosystem",
                            "severity",
                            "cve_id",
                            "per_page",
                            "before",
                            "after",
                        },
                    ),
                }
            ),
            credentials_required=False,
            access_state=ProviderAccessState.READY,
            checkpoint_field="updated_at+id",
            revisions_supported=True,
            deletions_supported=True,
        ),
        SourceKind.YOUTUBE: SourceContract(
            source=SourceKind.YOUTUBE,
            provider_id=ProviderId("youtube_official"),
            endpoints=MappingProxyType(
                {
                    "videos": _source_endpoint(
                        "videos",
                        "https://www.googleapis.com",
                        "/youtube/v3/videos",
                        {"part", "id", "chart", "regionCode", "maxResults", "pageToken"},
                        {"part"},
                    ),
                    "channels": _source_endpoint(
                        "channels",
                        "https://www.googleapis.com",
                        "/youtube/v3/channels",
                        {"part", "id", "forHandle", "mine", "maxResults", "pageToken"},
                        {"part"},
                    ),
                    "live_chat": _source_endpoint(
                        "live_chat",
                        "https://www.googleapis.com",
                        "/youtube/v3/liveChat/messages",
                        {"part", "liveChatId", "maxResults", "pageToken", "profileImageSize"},
                        {"part", "liveChatId"},
                    ),
                }
            ),
            credentials_required=True,
            access_state=ProviderAccessState.AWAITING_CREDENTIALS,
            checkpoint_field="nextPageToken+publishedAt",
            revisions_supported=True,
            deletions_supported=True,
        ),
    }
)


class SourceRequest(DomainModel):
    source: SourceKind
    provider_id: ProviderId
    capability: str
    base_url: str
    path_template: str
    parameters: dict[str, str | int | bool]
    access_state: ProviderAccessState
    executable: bool
    request_hash: str


class SourceQuotaWindow(DomainModel):
    source: SourceKind
    window_start: UtcDateTime
    reset_time: UtcDateTime
    limit: int = Field(ge=0)
    used: int = Field(ge=0)
    unit: str

    @model_validator(mode="after")
    def validate_window(self) -> SourceQuotaWindow:
        if self.reset_time <= self.window_start:
            raise ValueError("quota reset must follow window start")
        if self.used > self.limit:
            raise ValueError("quota usage cannot exceed limit")
        return self

    def consume(self, cost: int = 1) -> SourceQuotaWindow:
        if cost < 1 or self.used + cost > self.limit:
            raise ValueError("AQ-SOURCE-QUOTA-EXHAUSTED")
        return SourceQuotaWindow(
            source=self.source,
            window_start=self.window_start,
            reset_time=self.reset_time,
            limit=self.limit,
            used=self.used + cost,
            unit=self.unit,
        )


class OfficialWebChangeSnapshot(DomainModel):
    provider_id: ProviderId
    source_native_id: str
    canonical_url: str
    observed_time: UtcDateTime
    content_sha256: str
    previous_sha256: str | None = None
    changed: bool


def snapshot_official_web_change(
    *,
    source_native_id: str,
    canonical_url: str,
    content: bytes,
    observed_time: datetime,
    previous_sha256: str | None = None,
) -> OfficialWebChangeSnapshot:
    parsed = urlsplit(canonical_url)
    approved_hosts = {
        urlsplit(endpoint.base_url).hostname
        for endpoint in SOURCE_CONTRACTS[SourceKind.RSS_ATOM].endpoints.values()
    }
    if parsed.scheme != "https" or parsed.hostname not in approved_hosts:
        raise ValueError("AQ-SOURCE-WEB-CHANGE-HOST-NOT-ALLOWLISTED")
    if len(content) > 5_242_880:
        raise ValueError("AQ-SOURCE-WEB-CHANGE-CONTENT-TOO-LARGE")
    digest = hashlib.sha256(content).hexdigest()
    return OfficialWebChangeSnapshot(
        provider_id=ProviderId("official_rss_atom"),
        source_native_id=source_native_id,
        canonical_url=canonical_url,
        observed_time=ensure_utc(observed_time),
        content_sha256=digest,
        previous_sha256=previous_sha256,
        changed=previous_sha256 is not None and previous_sha256 != digest,
    )


def build_source_request(
    source: SourceKind,
    capability: str,
    parameters: Mapping[str, str | int | bool] | None = None,
    *,
    credential_available: bool = False,
) -> SourceRequest:
    contract = SOURCE_CONTRACTS[source]
    endpoint = contract.endpoints.get(capability)
    if endpoint is None:
        raise ValueError(f"AQ-SOURCE-{source.value}-CAPABILITY-DENIED")
    normalized = dict(parameters or {})
    if any(key.casefold() in {"key", "api_key", "token", "secret", "cookie"} for key in normalized):
        raise ValueError("AQ-SOURCE-PLAINTEXT-CREDENTIAL-DENIED")
    unknown = sorted(set(normalized) - endpoint.allowed_parameters)
    missing = sorted(endpoint.required_parameters - set(normalized))
    if unknown or missing:
        raise ValueError(f"AQ-SOURCE-PARAMETERS: unknown={unknown}, missing={missing}")
    parsed = urlsplit(endpoint.base_url)
    if parsed.scheme not in {"https", "wss"} or parsed.username or parsed.password:
        raise ValueError("AQ-SOURCE-OFFICIAL-URL-DENIED")
    access_state = contract.access_state
    executable = access_state is ProviderAccessState.READY
    if contract.credentials_required:
        access_state = (
            ProviderAccessState.READY
            if credential_available
            else ProviderAccessState.AWAITING_CREDENTIALS
        )
        executable = credential_available
    identity = canonical_sha256(
        {
            "source": source.value,
            "capability": capability,
            "base_url": endpoint.base_url,
            "path_template": endpoint.path,
            "parameters": normalized,
            "credential_present": credential_available,
        }
    )
    return SourceRequest(
        source=source,
        provider_id=contract.provider_id,
        capability=capability,
        base_url=endpoint.base_url,
        path_template=endpoint.path,
        parameters=normalized,
        access_state=access_state,
        executable=executable,
        request_hash=identity,
    )


class CollectedContent(DomainModel):
    source: SourceKind
    provider_id: ProviderId
    native_id: str
    source_native_id: str
    display_name: str
    ownership_group: str
    independence_group: str
    verified_source: bool
    content_type: ContentType
    canonical_url: str
    text: str
    language: str
    published_time: UtcDateTime
    observed_time: UtcDateTime
    modified_time: UtcDateTime | None = None
    deleted_time: UtcDateTime | None = None
    revision: int = Field(ge=1)
    engagement: dict[str, int] = Field(default_factory=dict)
    checkpoint: str

    @model_validator(mode="after")
    def validate_content(self) -> CollectedContent:
        if not self.native_id or not self.source_native_id or not self.text:
            raise ValueError("collected content identity and text are required")
        if self.modified_time is not None and self.modified_time < self.published_time:
            raise ValueError("content modification cannot precede publication")
        if self.deleted_time is not None and self.deleted_time < self.published_time:
            raise ValueError("content deletion cannot precede publication")
        if any(value < 0 for value in self.engagement.values()):
            raise ValueError("engagement counts cannot be negative")
        return self


class SourceBatch(DomainModel):
    source: SourceKind
    access_state: ProviderAccessState
    contents: tuple[CollectedContent, ...] = ()
    error_code: str | None = None
    checkpoint: str | None = None

    @model_validator(mode="after")
    def validate_batch(self) -> SourceBatch:
        if self.error_code is not None and self.contents:
            raise ValueError("degraded source batch cannot expose partial contents")
        return self


def degraded_batch(source: SourceKind, error_code: str) -> SourceBatch:
    return SourceBatch(
        source=source,
        access_state=ProviderAccessState.DEGRADED,
        error_code=error_code,
    )


def awaiting_credentials_batch(source: SourceKind) -> SourceBatch:
    contract = SOURCE_CONTRACTS[source]
    if not contract.credentials_required:
        raise ValueError("source does not require credentials")
    return SourceBatch(source=source, access_state=ProviderAccessState.AWAITING_CREDENTIALS)


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{field_name} keys must be strings")
    return {cast(str, key): item for key, item in raw.items()}


def _items(value: object, field_name: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return tuple(_mapping(item, field_name) for item in cast(list[object], value))


def _text(value: object, field_name: str, *, blank: bool = False) -> str:
    if not isinstance(value, str) or (not blank and not value.strip()):
        raise ValueError(f"{field_name} must be text")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"{field_name} must be an integer")


def _timestamp(value: object, field_name: str) -> datetime:
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    raw = _text(value, field_name)
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw), tz=UTC)
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        return ensure_utc(datetime.fromisoformat(raw))
    except ValueError:
        return ensure_utc(parsedate_to_datetime(raw))


def _gdelt_time(value: object) -> datetime:
    raw = _text(value, "seendate")
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return _timestamp(raw, "seendate")


def _language(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()[:16]
    return "und"


def parse_rss_atom(
    payload: bytes, *, observed_time: datetime, capability: str
) -> tuple[CollectedContent, ...]:
    if capability not in SOURCE_CONTRACTS[SourceKind.RSS_ATOM].endpoints:
        raise ValueError("RSS capability is not in the official feed catalog")
    if (
        len(payload) > 1_048_576
        or b"<!DOCTYPE" in payload.upper()
        or b"<!ENTITY" in payload.upper()
    ):
        raise ValueError("AQ-SOURCE-XML-UNSAFE")
    # Bounded official-feed input rejects DTD/entity declarations before stdlib parsing.
    root = ElementTree.fromstring(payload)  # noqa: S314  # nosec B314
    endpoint = SOURCE_CONTRACTS[SourceKind.RSS_ATOM].endpoints[capability]
    entries = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"item", "entry"}]
    observed = ensure_utc(observed_time)
    contents: list[CollectedContent] = []
    for entry in entries:
        fields: dict[str, str] = {}
        link = ""
        for child in entry:
            name = child.tag.rsplit("}", 1)[-1]
            value = (child.text or "").strip()
            if name == "link":
                link = child.attrib.get("href", value)
            elif value:
                fields.setdefault(name, value)
        native_id = fields.get("id") or fields.get("guid") or link
        published = fields.get("published") or fields.get("updated") or fields.get("pubDate")
        if not native_id or not published:
            raise ValueError("RSS/Atom item requires stable ID and published time")
        title = fields.get("title", "")
        body = fields.get("summary") or fields.get("description") or fields.get("content", "")
        contents.append(
            CollectedContent(
                source=SourceKind.RSS_ATOM,
                provider_id=ProviderId("official_rss_atom"),
                native_id=native_id,
                source_native_id=capability,
                display_name=capability.replace("_", " ").title(),
                ownership_group=capability,
                independence_group=capability,
                verified_source=True,
                content_type=ContentType.ANNOUNCEMENT,
                canonical_url=link or urljoin(endpoint.base_url, endpoint.path),
                text=f"{title}\n{body}".strip(),
                language=_language(fields.get("language")),
                published_time=_timestamp(published, "published"),
                observed_time=observed,
                modified_time=(
                    _timestamp(fields["updated"], "updated") if "updated" in fields else None
                ),
                revision=1,
                checkpoint=f"{published}|{native_id}",
            )
        )
    return tuple(contents)


def parse_gdelt(
    payload: Mapping[str, object], *, observed_time: datetime
) -> tuple[CollectedContent, ...]:
    observed = ensure_utc(observed_time)
    contents: list[CollectedContent] = []
    for article in _items(payload.get("articles"), "articles"):
        url = _text(article.get("url"), "url")
        published = _gdelt_time(article.get("seendate"))
        domain = _text(article.get("domain") or urlsplit(url).hostname, "domain")
        contents.append(
            CollectedContent(
                source=SourceKind.GDELT,
                provider_id=ProviderId("gdelt_public"),
                native_id=canonical_sha256({"url": url, "seen": published.isoformat()}),
                source_native_id=domain,
                display_name=domain,
                ownership_group=domain,
                independence_group=domain,
                verified_source=False,
                content_type=ContentType.ARTICLE,
                canonical_url=url,
                text=_text(article.get("title"), "title"),
                language=_language(article.get("language")),
                published_time=published,
                observed_time=observed,
                revision=1,
                checkpoint=f"{published.isoformat()}|{url}",
            )
        )
    return tuple(contents)


def parse_x(
    payload: Mapping[str, object], *, observed_time: datetime
) -> tuple[CollectedContent, ...]:
    observed = ensure_utc(observed_time)
    includes = _mapping(payload.get("includes") or {}, "includes")
    users = {
        _text(user.get("id"), "user.id"): user
        for user in _items(includes.get("users") or [], "includes.users")
    }
    data_value: object = payload.get("data")
    data: object = (
        [_mapping(cast(object, data_value), "data")] if isinstance(data_value, dict) else data_value
    )
    contents: list[CollectedContent] = []
    for post in _items(data or [], "data"):
        post_id = _text(post.get("id"), "id")
        author_id = _text(post.get("author_id"), "author_id")
        user = users.get(author_id, {})
        username = _text(user.get("username") or author_id, "username")
        history = post.get("edit_history_tweet_ids") or [post_id]
        if not isinstance(history, list):
            raise ValueError("edit history must be a list")
        public_metrics = _mapping(post.get("public_metrics") or {}, "public_metrics")
        engagement = {
            key: _integer(value, f"public_metrics.{key}")
            for key, value in public_metrics.items()
            if key
            in {
                "like_count",
                "reply_count",
                "retweet_count",
                "quote_count",
                "bookmark_count",
                "impression_count",
            }
        }
        contents.append(
            CollectedContent(
                source=SourceKind.X,
                provider_id=ProviderId("x_official"),
                native_id=post_id,
                source_native_id=author_id,
                display_name=_text(user.get("name") or username, "name"),
                ownership_group=author_id,
                independence_group=author_id,
                verified_source=bool(user.get("verified", False)),
                content_type=ContentType.POST,
                canonical_url=f"https://x.com/{username}/status/{post_id}",
                text=_text(post.get("text") or "[deleted]", "text"),
                language=_language(post.get("lang")),
                published_time=_timestamp(post.get("created_at"), "created_at"),
                observed_time=observed,
                modified_time=(observed if len(cast(list[object], history)) > 1 else None),
                deleted_time=(observed if post.get("deleted") is True else None),
                revision=len(cast(list[object], history)),
                engagement=engagement,
                checkpoint=post_id,
            )
        )
    return tuple(contents)


def parse_telegram_bot(
    payload: Mapping[str, object],
    *,
    observed_time: datetime,
    allowed_channel_ids: frozenset[str],
) -> tuple[CollectedContent, ...]:
    observed = ensure_utc(observed_time)
    contents: list[CollectedContent] = []
    for update in _items(payload.get("result"), "result"):
        update_id = _integer(update.get("update_id"), "update_id")
        revision = 2 if "edited_channel_post" in update else 1
        message = update.get("edited_channel_post") or update.get("channel_post")
        if message is None:
            raise ValueError("AQ-TELEGRAM-NON-CHANNEL-UPDATE-DENIED")
        message_map = _mapping(message, "channel_post")
        chat = _mapping(message_map.get("chat"), "chat")
        channel_id = str(_integer(chat.get("id"), "chat.id"))
        if (
            _text(chat.get("type"), "chat.type") != "channel"
            or channel_id not in allowed_channel_ids
        ):
            raise ValueError("AQ-TELEGRAM-CHANNEL-NOT-ALLOWLISTED")
        message_id = _integer(message_map.get("message_id"), "message_id")
        username = _text(chat.get("username") or channel_id, "chat.username")
        published = _timestamp(message_map.get("date"), "date")
        modified = (
            _timestamp(message_map.get("edit_date"), "edit_date")
            if message_map.get("edit_date") is not None
            else None
        )
        contents.append(
            CollectedContent(
                source=SourceKind.TELEGRAM_BOT,
                provider_id=ProviderId("telegram_bot"),
                native_id=f"{channel_id}:{message_id}",
                source_native_id=channel_id,
                display_name=_text(chat.get("title") or username, "chat.title"),
                ownership_group=channel_id,
                independence_group=channel_id,
                verified_source=True,
                content_type=ContentType.CHANNEL_MESSAGE,
                canonical_url=f"https://t.me/{username}/{message_id}",
                text=_text(message_map.get("text") or message_map.get("caption"), "text"),
                language="und",
                published_time=published,
                observed_time=observed,
                modified_time=modified,
                revision=revision,
                checkpoint=str(update_id),
            )
        )
    return tuple(contents)


def parse_bluesky_jetstream(
    payload: Mapping[str, object], *, observed_time: datetime
) -> tuple[CollectedContent, ...]:
    observed = ensure_utc(observed_time)
    if payload.get("$type") == "message":
        event = _mapping(payload.get("payload"), "payload")
        event_type = _text(event.get("$type"), "payload.$type")
        if not event_type.endswith("#commit"):
            return ()
        did = _text(event.get("did"), "payload.did")
        checkpoint = str(_integer(event.get("seq"), "payload.seq"))
        collection = _text(event.get("collection"), "payload.collection")
        operation = _text(event.get("operation"), "payload.operation").casefold()
        rkey = _text(event.get("rkey"), "payload.rkey")
        record = _mapping(event.get("record") or {}, "payload.record")
        witnessed_time = _timestamp(event.get("time"), "payload.time")
    else:
        did = _text(payload.get("did"), "did")
        time_us = _integer(payload.get("time_us"), "time_us")
        commit = _mapping(payload.get("commit"), "commit")
        collection = _text(commit.get("collection"), "collection")
        operation = _text(commit.get("operation"), "operation").casefold()
        rkey = _text(commit.get("rkey"), "rkey")
        record = _mapping(commit.get("record") or {}, "record")
        cursor = payload.get("cursor")
        checkpoint = str(_integer(cursor, "cursor")) if cursor is not None else str(time_us)
        witnessed_time = datetime.fromtimestamp(time_us / 1_000_000, tz=UTC)
    if collection != "app.bsky.feed.post":
        return ()
    published = (
        _timestamp(record.get("createdAt"), "createdAt")
        if record.get("createdAt") is not None
        else witnessed_time
    )
    text = _text(record.get("text") or "[deleted]", "text")
    uri = f"at://{did}/{collection}/{rkey}"
    languages_value = record.get("langs")
    languages = cast(list[object], languages_value) if isinstance(languages_value, list) else []
    return (
        CollectedContent(
            source=SourceKind.BLUESKY_JETSTREAM,
            provider_id=ProviderId("bluesky_jetstream"),
            native_id=uri,
            source_native_id=did,
            display_name=did,
            ownership_group=did,
            independence_group=did,
            verified_source=did.startswith("did:"),
            content_type=ContentType.POST,
            canonical_url=uri,
            text=text,
            language=_language(languages[0] if languages else "und"),
            published_time=published,
            observed_time=observed,
            modified_time=observed if operation == "update" else None,
            deleted_time=observed if operation == "delete" else None,
            revision=2 if operation in {"update", "delete"} else 1,
            checkpoint=checkpoint,
        ),
    )


class BlueskyStreamSelection(DomainModel):
    mode: str
    url: str
    checkpoint_parameter: str
    fallback_used: bool
    reason_code: str


def select_bluesky_transport(
    *, detected_event_fields: frozenset[str], jetstream_available: bool
) -> BlueskyStreamSelection:
    required_v2_fields = frozenset({"$type", "payload", "seq"})
    required_v1_fields = frozenset({"did", "time_us", "kind", "commit"})
    if jetstream_available and required_v2_fields <= detected_event_fields:
        return BlueskyStreamSelection(
            mode="JETSTREAM_V2",
            url=(
                "wss://jetstream2.us-east.bsky.network/xrpc/network.bsky.jetstream.subscribeEvents"
            ),
            checkpoint_parameter="cursor",
            fallback_used=False,
            reason_code="AQ-BLUESKY-JETSTREAM-V2-CONTRACT-COMPATIBLE",
        )
    if jetstream_available and required_v1_fields <= detected_event_fields:
        return BlueskyStreamSelection(
            mode="JETSTREAM_V1_LEGACY",
            url="wss://jetstream2.us-east.bsky.network/subscribe",
            checkpoint_parameter="cursor",
            fallback_used=True,
            reason_code="AQ-BLUESKY-JETSTREAM-V1-LEGACY-FALLBACK",
        )
    return BlueskyStreamSelection(
        mode="FIREHOSE",
        url="wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos",
        checkpoint_parameter="cursor",
        fallback_used=True,
        reason_code="AQ-BLUESKY-FIREHOSE-FALLBACK",
    )


def parse_github(
    payload: Mapping[str, object], *, observed_time: datetime, capability: str
) -> tuple[CollectedContent, ...]:
    observed = ensure_utc(observed_time)
    values: object = payload.get("items") or payload.get("data") or payload
    raw_items: object = (
        [_mapping(cast(object, values), capability)] if isinstance(values, dict) else values
    )
    contents: list[CollectedContent] = []
    for item in _items(raw_items, capability):
        if capability == "security_advisories":
            native_id = _text(item.get("ghsa_id"), "ghsa_id")
            title = _text(item.get("summary"), "summary")
            body = _text(item.get("description") or title, "description")
            published = _timestamp(item.get("published_at"), "published_at")
            url = _text(item.get("html_url"), "html_url")
            source_id = _text(item.get("cve_id") or native_id, "cve_id")
        else:
            native_id = str(_integer(item.get("id"), "id"))
            title = _text(item.get("name") or item.get("tag_name"), "name")
            body = _text(item.get("body") or title, "body")
            published = _timestamp(
                item.get("published_at") or item.get("created_at"), "published_at"
            )
            url = _text(item.get("html_url"), "html_url")
            author = _mapping(item.get("author") or {}, "author")
            source_id = _text(author.get("login") or urlsplit(url).path.split("/")[1], "author")
        modified_value = item.get("updated_at")
        contents.append(
            CollectedContent(
                source=SourceKind.GITHUB,
                provider_id=ProviderId("github_public"),
                native_id=native_id,
                source_native_id=source_id,
                display_name=source_id,
                ownership_group=source_id,
                independence_group=source_id,
                verified_source=True,
                content_type=ContentType.RELEASE
                if capability != "security_advisories"
                else ContentType.ANNOUNCEMENT,
                canonical_url=url,
                text=f"{title}\n{body}",
                language="en",
                published_time=published,
                observed_time=observed,
                modified_time=_timestamp(modified_value, "updated_at") if modified_value else None,
                revision=1,
                checkpoint=f"{modified_value or published.isoformat()}|{native_id}",
            )
        )
    return tuple(contents)


def parse_github_webhook(
    payload: Mapping[str, object],
    *,
    observed_time: datetime,
    event_name: str,
    delivery_id: str,
    signature_verified: bool,
) -> tuple[CollectedContent, ...]:
    if not signature_verified:
        raise ValueError("AQ-GITHUB-WEBHOOK-SIGNATURE-NOT-VERIFIED")
    if event_name not in {"release", "security_advisory", "push", "discussion", "issues"}:
        raise ValueError("AQ-GITHUB-WEBHOOK-EVENT-NOT-ALLOWLISTED")
    repository = _mapping(payload.get("repository"), "repository")
    repository_name = _text(repository.get("full_name"), "repository.full_name")
    repository_url = _text(repository.get("html_url"), "repository.html_url")
    if event_name == "release":
        record = _mapping(payload.get("release"), "release")
        record.setdefault("author", payload.get("sender") or {})
        return parse_github({"items": [record]}, observed_time=observed_time, capability="releases")
    if event_name == "security_advisory":
        record = _mapping(payload.get("security_advisory"), "security_advisory")
        return parse_github(
            {"items": [record]}, observed_time=observed_time, capability="security_advisories"
        )
    observed = ensure_utc(observed_time)
    action = _text(payload.get("action") or event_name, "action")
    return (
        CollectedContent(
            source=SourceKind.GITHUB,
            provider_id=ProviderId("github_public"),
            native_id=delivery_id,
            source_native_id=repository_name,
            display_name=repository_name,
            ownership_group=repository_name,
            independence_group=repository_name,
            verified_source=True,
            content_type=ContentType.ANNOUNCEMENT,
            canonical_url=repository_url,
            text=f"GitHub {event_name} event: {action}",
            language="en",
            published_time=observed,
            observed_time=observed,
            revision=1,
            checkpoint=delivery_id,
        ),
    )


def parse_youtube(
    payload: Mapping[str, object], *, observed_time: datetime, capability: str
) -> tuple[CollectedContent, ...]:
    observed = ensure_utc(observed_time)
    contents: list[CollectedContent] = []
    for item in _items(payload.get("items"), "items"):
        snippet = _mapping(item.get("snippet"), "snippet")
        author = _mapping(item.get("authorDetails") or {}, "authorDetails")
        raw_id = item.get("id")
        if isinstance(raw_id, dict):
            id_map = _mapping(cast(object, raw_id), "id")
            native_id = _text(id_map.get("videoId") or id_map.get("channelId"), "id")
        else:
            native_id = _text(raw_id, "id")
        channel_id = _text(
            snippet.get("channelId") or author.get("channelId") or "youtube", "channelId"
        )
        published = _timestamp(snippet.get("publishedAt"), "publishedAt")
        title = _text(snippet.get("title") or snippet.get("displayMessage") or native_id, "title")
        description = _text(snippet.get("description") or title, "description")
        url = (
            f"https://www.youtube.com/watch?v={native_id}"
            if capability == "videos"
            else f"https://www.youtube.com/channel/{channel_id}"
        )
        contents.append(
            CollectedContent(
                source=SourceKind.YOUTUBE,
                provider_id=ProviderId("youtube_official"),
                native_id=native_id,
                source_native_id=channel_id,
                display_name=_text(
                    snippet.get("channelTitle") or author.get("displayName") or channel_id,
                    "channelTitle",
                ),
                ownership_group=channel_id,
                independence_group=channel_id,
                verified_source=bool(author.get("isVerified", False)),
                content_type=(
                    ContentType.CHANNEL_MESSAGE
                    if capability == "live_chat"
                    else ContentType.VIDEO_META
                ),
                canonical_url=url,
                text=f"{title}\n{description}",
                language=_language(snippet.get("defaultLanguage")),
                published_time=published,
                observed_time=observed,
                revision=1,
                checkpoint=f"{published.isoformat()}|{native_id}",
            )
        )
    return tuple(contents)


def content_contracts(
    item: CollectedContent,
    *,
    available_time: datetime,
    ingest_time: datetime,
    source_policy_id: SourcePolicyId,
    rights_state: RightsState,
) -> tuple[SourceIdentity, RawContentEnvelope, EngagementSnapshot | None]:
    available = ensure_utc(available_time)
    ingested = ensure_utc(ingest_time)
    stable_content_id = ContentId(
        canonical_sha256({"provider": str(item.provider_id), "native_id": item.native_id})
    )
    identity_id = SourceIdentityId(
        canonical_sha256(
            {
                "provider": str(item.provider_id),
                "native_id": item.source_native_id,
                "version": 1,
            }
        )
    )
    identity = SourceIdentity(
        source_identity_id=identity_id,
        provider_id=item.provider_id,
        provider_native_id=ProviderNativeId(item.source_native_id),
        display_name=item.display_name,
        ownership_group=item.ownership_group,
        independence_group=item.independence_group,
        verified=item.verified_source,
        first_observed_time=item.observed_time,
    )
    raw_hash = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
    snapshot = None
    if item.engagement:
        snapshot_id = ArtifactId(
            canonical_sha256(
                {
                    "content_id": str(stable_content_id),
                    "observed_time": item.observed_time.isoformat(),
                    "metrics": item.engagement,
                }
            )
        )
        snapshot = EngagementSnapshot(
            engagement_snapshot_id=snapshot_id,
            content_id=stable_content_id,
            observed_time=item.observed_time,
            available_time=available,
            metrics=item.engagement,
        )
    envelope = RawContentEnvelope(
        content_id=stable_content_id,
        provider_id=item.provider_id,
        provider_native_id=ProviderNativeId(item.native_id),
        source_identity_id=identity_id,
        content_type=item.content_type,
        canonical_url=item.canonical_url,
        author_time=item.published_time,
        published_time=item.published_time,
        first_observed_time=item.observed_time,
        available_time=available,
        ingest_time=ingested,
        modified_time=item.modified_time,
        deleted_time=item.deleted_time,
        language=item.language,
        raw_content_hash=raw_hash,
        revision=item.revision,
        engagement_snapshot_id=(snapshot.engagement_snapshot_id if snapshot else None),
        source_policy_id=source_policy_id,
        rights_state=rights_state,
        quality_state=(QualityState.DEGRADED if item.deleted_time else QualityState.GOOD),
    )
    return identity, envelope, snapshot


@dataclass(slots=True)
class OfficialSourceAdapter:
    source: SourceKind
    client: httpx.Client

    def fetch_text(
        self, capability: str, parameters: Mapping[str, str | int | bool] | None = None
    ) -> bytes:
        request = build_source_request(self.source, capability, parameters)
        if not request.executable:
            raise RuntimeError(f"AQ-SOURCE-{request.access_state.value.upper()}")
        forbidden_headers = {"authorization", "cookie", "x-api-key"}
        if any(name.casefold() in forbidden_headers for name in self.client.headers):
            raise ValueError("AQ-SOURCE-CREDENTIALLED-CLIENT-DENIED")
        if len(self.client.cookies) > 0:
            raise ValueError("AQ-SOURCE-COOKIE-DENIED")
        endpoint = SOURCE_CONTRACTS[self.source].endpoints[capability]
        if urlsplit(endpoint.base_url).scheme != "https":
            raise RuntimeError("AQ-SOURCE-STREAM-REQUIRES-WEBSOCKET-TRANSPORT")
        path = endpoint.path
        path_fields = set(re.findall(r"{([A-Za-z_][A-Za-z0-9_]*)}", path))
        if "{" in path:
            path = path.format(**dict(parameters or {}))
        query = {
            key: value for key, value in dict(parameters or {}).items() if key not in path_fields
        }
        response = self.client.get(urljoin(endpoint.base_url, path), params=query)
        if response.history:
            raise ValueError("AQ-SOURCE-REDIRECT-DENIED")
        response.raise_for_status()
        return response.content

    def fetch_json(
        self, capability: str, parameters: Mapping[str, str | int | bool] | None = None
    ) -> dict[str, object]:
        raw = self.fetch_text(capability, parameters)
        return _mapping(cast(object, json.loads(raw)), "response")
