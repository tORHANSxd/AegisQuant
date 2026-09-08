"""Point-in-time RAG context with source-policy and prompt-injection gates."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Final

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.policy import PolicyBoundary, SourceProcessingPolicy
from aegisquant.domain.time import UtcDateTime, assert_point_in_time
from aegisquant.intelligence.pipeline import prompt_safety

SECRET_PATTERN: Final = re.compile(
    r"(?i)(?:password|api[_ -]?secret|api[_ -]?key|cookie|verification[_ -]?code)\s*[:=]"
    r"|\bsk-[A-Za-z0-9_-]{12,}\b"
)
CONTROL_PATTERN: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class RagSecurityError(ValueError):
    """Untrusted content failed a fail-closed RAG boundary."""


class RagDocument(DomainModel):
    evidence_id: str
    source_policy_id: str
    text: str = Field(min_length=1)
    available_at_utc: UtcDateTime


class RagContext(DomainModel):
    evidence_id: str
    source_policy_id: str
    text: str
    available_at_utc: UtcDateTime
    untrusted_data: bool = True
    tool_calls_allowed: bool = False
    secret_access_allowed: bool = False
    safety_flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_isolation(self) -> RagContext:
        if not self.untrusted_data or self.tool_calls_allowed or self.secret_access_allowed:
            raise ValueError("RAG context must remain isolated untrusted data")
        return self


def build_rag_context(
    *,
    document: RagDocument,
    policy: SourceProcessingPolicy,
    decision_time: datetime,
    cloud_inference: bool,
    maximum_characters: int = 20_000,
) -> RagContext:
    if str(policy.source_policy_id) != document.source_policy_id:
        raise RagSecurityError("AQ-RAG-SOURCE-POLICY-MISMATCH")
    boundary = PolicyBoundary.CLOUD_INFERENCE if cloud_inference else PolicyBoundary.COLLECTION
    policy.require(boundary)
    assert_point_in_time(
        available_time=document.available_at_utc,
        decision_time=decision_time,
    )
    if maximum_characters < 1:
        raise ValueError("RAG maximum characters must be positive")
    normalized = unicodedata.normalize("NFKC", document.text)
    normalized = CONTROL_PATTERN.sub("", normalized).strip()
    if not normalized or len(normalized) > maximum_characters:
        raise RagSecurityError("AQ-RAG-CONTENT-LENGTH-REJECTED")
    if SECRET_PATTERN.search(normalized):
        raise RagSecurityError("AQ-RAG-SECRET-LIKE-CONTENT-REJECTED")
    safety = prompt_safety(normalized)
    if safety.flags:
        raise RagSecurityError("AQ-RAG-PROMPT-INJECTION-REJECTED:" + ",".join(safety.flags))
    return RagContext(
        evidence_id=document.evidence_id,
        source_policy_id=document.source_policy_id,
        text=normalized,
        available_at_utc=document.available_at_utc,
        safety_flags=safety.flags,
    )
