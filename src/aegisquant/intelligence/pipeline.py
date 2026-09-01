"""Rule-only P04 language, deduplication, entity, claim, event, and prompt-safety pipeline."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import model_validator

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    ClaimId,
    ContentId,
    EventClusterId,
    ModelVersionId,
    SourceDocumentId,
)
from aegisquant.domain.intelligence import (
    AssertionMode,
    ClaimRecord,
    EventCluster,
    EventClusterStatus,
    Polarity,
)
from aegisquant.domain.time import ensure_utc
from aegisquant.intelligence.collectors import CollectedContent

TRACKING_PARAMETERS: Final = frozenset(
    {
        "fbclid",
        "gclid",
        "ref",
        "ref_src",
        "source",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)
PROMPT_PATTERNS: Final = {
    "IGNORE_INSTRUCTIONS": re.compile(
        r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|system|instructions?)\b",
        re.IGNORECASE,
    ),
    "TOOL_INVOCATION": re.compile(
        r"\b(call|invoke|execute|run)\b.{0,30}\b(tool|shell|terminal|function)\b|调用.{0,10}(工具|命令)",
        re.IGNORECASE,
    ),
    "CONFIG_MUTATION": re.compile(
        r"\b(change|edit|overwrite|disable)\b.{0,30}\b(config|policy|guard|lock)\b|修改.{0,10}(配置|策略|锁)",
        re.IGNORECASE,
    ),
    "SECRET_EXTRACTION": re.compile(
        r"\b(reveal|print|show|exfiltrate)\b.{0,30}\b(secret|token|password|cookie|api.?key)\b|输出.{0,10}(密码|密钥|令牌)",
        re.IGNORECASE,
    ),
}
ENTITY_ALIASES: Final = {
    "bitcoin": "asset:BTC",
    "btc": "asset:BTC",
    "ethereum": "asset:ETH",
    "ether": "asset:ETH",
    "eth": "asset:ETH",
    "tether": "asset:USDT",
    "usdt": "asset:USDT",
    "circle": "organization:CIRCLE",
    "usdc": "asset:USDC",
    "sec": "regulator:US_SEC",
    "federal reserve": "central_bank:US_FED",
    "ecb": "central_bank:ECB",
    "okx": "exchange:OKX",
    "bybit": "exchange:BYBIT",
    "deribit": "exchange:DERIBIT",
    "binance": "exchange:BINANCE",
}
EVENT_RULES: Final = (
    ("SECURITY_INCIDENT", ("hack", "exploit", "breach", "vulnerability", "攻击", "漏洞")),
    ("REGULATORY_ACTION", ("regulation", "lawsuit", "approval", "etf", "监管", "批准")),
    ("LISTING_CHANGE", ("listing", "delisting", "listed", "上线", "下架")),
    ("PROTOCOL_RELEASE", ("release", "upgrade", "mainnet", "fork", "发布", "升级")),
    ("STABLECOIN_EVENT", ("depeg", "redemption", "reserve", "脱锚", "储备")),
)


class PromptSafetyResult(DomainModel):
    flags: tuple[str, ...]
    external_content_is_data: bool = True
    tool_calls_allowed: bool = False
    config_mutation_allowed: bool = False

    @model_validator(mode="after")
    def enforce_isolation(self) -> PromptSafetyResult:
        if (
            not self.external_content_is_data
            or self.tool_calls_allowed
            or self.config_mutation_allowed
        ):
            raise ValueError("external content must remain isolated data")
        return self


class EvidenceGroup(DomainModel):
    fingerprint: str
    content_ids: tuple[ContentId, ...]
    canonical_urls: tuple[str, ...]
    independence_group: str


class PipelineResult(DomainModel):
    evidence_groups: tuple[EvidenceGroup, ...]
    claims: tuple[ClaimRecord, ...]
    event_clusters: tuple[EventCluster, ...]
    safety: dict[ContentId, PromptSafetyResult]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http", "at"}:
        raise ValueError("content URL must use an expected public scheme")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_PARAMETERS
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, query, ""))


def content_id(item: CollectedContent) -> ContentId:
    return ContentId(
        canonical_sha256({"provider": str(item.provider_id), "native_id": item.native_id})
    )


def content_fingerprint(item: CollectedContent) -> str:
    return canonical_sha256({"text": normalize_text(item.text)})


def detect_language(text: str, declared: str) -> str:
    if declared and declared != "und":
        return declared.casefold()
    cjk_count = sum("\u3400" <= character <= "\u9fff" for character in text)
    latin_count = sum(character.isascii() and character.isalpha() for character in text)
    if cjk_count > latin_count:
        return "zh"
    return "en" if latin_count else "und"


def prompt_safety(text: str) -> PromptSafetyResult:
    flags = tuple(name for name, pattern in PROMPT_PATTERNS.items() if pattern.search(text))
    return PromptSafetyResult(flags=flags)


def link_entities(text: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    entities = {
        entity_id
        for alias, entity_id in ENTITY_ALIASES.items()
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized)
    }
    return tuple(sorted(entities))


def classify_event(text: str) -> str:
    normalized = normalize_text(text)
    for event_type, keywords in EVENT_RULES:
        if any(keyword in normalized for keyword in keywords):
            return event_type
    return "MARKET_INFORMATION"


def _claim(
    item: CollectedContent,
    *,
    fingerprint: str,
    safety: PromptSafetyResult,
) -> ClaimRecord:
    normalized = normalize_text(item.text)
    entities = link_entities(normalized)
    event_type = classify_event(normalized)
    assertion_mode = (
        AssertionMode.RUMOR
        if any(token in normalized for token in ("rumor", "unconfirmed", "传闻", "未经证实"))
        else AssertionMode.FACT
    )
    polarity = (
        Polarity.NEGATE
        if any(token in normalized for token in ("not ", "denies", "false", "否认", "并非"))
        else Polarity.AFFIRM
    )
    stable_id = content_id(item)
    identity = {
        "content_id": str(stable_id),
        "fingerprint": fingerprint,
        "event_type": event_type,
        "entities": entities,
    }
    return ClaimRecord(
        claim_id=ClaimId(canonical_sha256(identity)),
        content_id=stable_id,
        claim_text_normalized=normalized[:2000],
        subject_entity_ids=entities,
        predicate=event_type.casefold(),
        object_entity_ids=(),
        event_type=event_type,
        assertion_mode=assertion_mode,
        polarity=polarity,
        evidence_spans=(item.text[:500],),
        extractor_versions=(ModelVersionId("rules-p04-v1"),),
        source_independence_group=f"repost:{fingerprint}",
        credibility_prior=Decimal("0.8") if item.verified_source else Decimal("0.4"),
        novelty_score=Decimal("1"),
        prompt_injection_flags=safety.flags,
    )


def deduplicate(contents: tuple[CollectedContent, ...]) -> tuple[EvidenceGroup, ...]:
    grouped: dict[str, list[CollectedContent]] = defaultdict(list)
    for item in contents:
        grouped[content_fingerprint(item)].append(item)
    groups: list[EvidenceGroup] = []
    for fingerprint, items in sorted(grouped.items()):
        groups.append(
            EvidenceGroup(
                fingerprint=fingerprint,
                content_ids=tuple(sorted((content_id(item) for item in items), key=str)),
                canonical_urls=tuple(
                    sorted({canonicalize_url(item.canonical_url) for item in items})
                ),
                independence_group=f"repost:{fingerprint}",
            )
        )
    return tuple(groups)


def cluster_claims(
    claims: tuple[ClaimRecord, ...],
    *,
    as_of_time: datetime,
    verified_content_ids: frozenset[ContentId],
) -> tuple[EventCluster, ...]:
    as_of = ensure_utc(as_of_time)
    grouped: dict[tuple[str, tuple[str, ...], str], list[ClaimRecord]] = defaultdict(list)
    for claim in claims:
        key = (claim.event_type, claim.subject_entity_ids, claim.predicate)
        grouped[key].append(claim)
    clusters: list[EventCluster] = []
    for key, group in sorted(grouped.items(), key=lambda item: item[0]):
        event_type, entities, predicate = key
        independent = len({claim.source_independence_group for claim in group})
        official_ids = tuple(
            SourceDocumentId(str(claim.content_id))
            for claim in group
            if claim.content_id in verified_content_ids
        )
        if official_ids:
            status = EventClusterStatus.CONFIRMED
        elif independent >= 2:
            status = EventClusterStatus.CORROBORATED
        else:
            status = EventClusterStatus.EMERGING
        cluster_identity = {
            "event_type": event_type,
            "entities": entities,
            "predicate": predicate,
            "claim_ids": sorted(str(claim.claim_id) for claim in group),
        }
        clusters.append(
            EventCluster(
                event_cluster_id=EventClusterId(canonical_sha256(cluster_identity)),
                event_type=event_type,
                status=status,
                entity_ids=entities,
                first_observed_time=as_of,
                last_updated_time=as_of,
                claim_ids=tuple(sorted((claim.claim_id for claim in group), key=str)),
                supporting_evidence_ids=tuple(
                    sorted((SourceDocumentId(str(claim.content_id)) for claim in group), key=str)
                ),
                contradicting_evidence_ids=(),
                independent_source_count=independent,
                official_confirmation_ids=official_ids,
                credibility_score=Decimal("0.8") if official_ids else Decimal("0.5"),
                manipulation_risk=Decimal("0.2") if official_ids else Decimal("0.5"),
                uncertainty=Decimal("0.2") if official_ids else Decimal("0.5"),
            )
        )
    return tuple(clusters)


def run_pipeline(contents: tuple[CollectedContent, ...], *, as_of_time: datetime) -> PipelineResult:
    groups = deduplicate(contents)
    group_by_content = {
        content: group.fingerprint for group in groups for content in group.content_ids
    }
    safety = {content_id(item): prompt_safety(item.text) for item in contents}
    claims = tuple(
        _claim(
            item,
            fingerprint=group_by_content[content_id(item)],
            safety=safety[content_id(item)],
        )
        for item in contents
    )
    verified = frozenset(content_id(item) for item in contents if item.verified_source)
    clusters = cluster_claims(claims, as_of_time=as_of_time, verified_content_ids=verified)
    return PipelineResult(
        evidence_groups=groups,
        claims=claims,
        event_clusters=clusters,
        safety=safety,
    )
