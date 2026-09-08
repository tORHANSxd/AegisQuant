"""Normalize public search-index metadata without fetching protected content."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.intelligence.static_analysis.models import KnowledgePlatform

ALLOWED_PUBLIC_HOSTS = frozenset(
    {
        "www.joinquant.com",
        "joinquant.com",
        "www.ricequant.com",
        "ricequant.com",
        "bigquant.com",
        "www.bigquant.com",
        "github.com",
    }
)
SECRET_QUERY_NAMES = frozenset(
    {"access_token", "api_key", "apikey", "auth", "cookie", "password", "secret", "token"}
)


class PublicIndexCandidate(DomainModel):
    candidate_id: str
    platform: KnowledgePlatform
    url: str
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=1000)
    keywords: tuple[str, ...] = ()
    untrusted_metadata: bool = True
    content_fetch_allowed: bool = False
    access_bypass_allowed: bool = False

    @model_validator(mode="after")
    def fail_closed(self) -> PublicIndexCandidate:
        if not self.untrusted_metadata or self.content_fetch_allowed or self.access_bypass_allowed:
            raise ValueError("public-index discovery is metadata-only and untrusted")
        return self


def _canonical_public_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_PUBLIC_HOSTS:
        raise ValueError("public discovery URL must use HTTPS on an approved platform host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("public discovery URL cannot contain credentials")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(name.casefold() in SECRET_QUERY_NAMES for name, _ in query):
        raise ValueError("public discovery URL contains a secret-like query parameter")
    clean_query = "&".join(f"{name}={value}" for name, value in sorted(query))
    return urlunsplit(("https", parsed.netloc.casefold(), parsed.path or "/", clean_query, ""))


def normalize_public_candidates(
    records: Iterable[Mapping[str, object]],
) -> tuple[PublicIndexCandidate, ...]:
    """Validate caller-supplied search metadata; this function performs no network access."""
    candidates: dict[str, PublicIndexCandidate] = {}
    for record in records:
        url_value = record.get("url")
        platform_value = record.get("platform")
        title_value = record.get("title")
        if not isinstance(url_value, str) or not isinstance(platform_value, str):
            raise ValueError("public discovery record requires string URL and platform")
        if not isinstance(title_value, str):
            raise ValueError("public discovery record requires a string title")
        author_value = record.get("author")
        summary_value = record.get("summary")
        keywords_value = record.get("keywords", ())
        if author_value is not None and not isinstance(author_value, str):
            raise ValueError("public discovery author must be a string")
        if summary_value is not None and not isinstance(summary_value, str):
            raise ValueError("public discovery summary must be a string")
        if not isinstance(keywords_value, (list, tuple)):
            raise ValueError("public discovery keywords must be strings")
        typed_keywords = cast("list[object] | tuple[object, ...]", keywords_value)
        if not all(isinstance(item, str) for item in typed_keywords):
            raise ValueError("public discovery keywords must be strings")
        keywords = tuple(cast("str", item) for item in typed_keywords)
        url = _canonical_public_url(url_value)
        platform = KnowledgePlatform(platform_value)
        candidate_id = canonical_sha256({"platform": platform.value, "url": url})
        payload: dict[str, object] = {
            "candidate_id": candidate_id,
            "platform": platform,
            "url": url,
            "title": title_value.strip(),
            "author": author_value,
            "summary": summary_value,
            "keywords": tuple(sorted(set(keywords))),
        }
        candidate = PublicIndexCandidate.model_validate(payload)
        existing = candidates.get(candidate_id)
        if existing is not None and existing != candidate:
            raise ValueError("conflicting public-index metadata for the same canonical URL")
        candidates[candidate_id] = candidate
    return tuple(sorted(candidates.values(), key=lambda item: item.candidate_id))
