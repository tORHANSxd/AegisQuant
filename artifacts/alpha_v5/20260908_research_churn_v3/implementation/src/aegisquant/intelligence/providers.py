"""Vendor-neutral structured LLM transport with no tool, secret, or execution surface."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field, JsonValue, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.intelligence.rag import RagContext


class StructuredLlmRequest(DomainModel):
    request_id: str
    provider_id: str
    model_id: str
    schema_id: str
    system_instruction: str = Field(min_length=1, max_length=4000)
    contexts: tuple[RagContext, ...]
    allowed_evidence_ids: tuple[str, ...]
    temperature: float = Field(default=0.0, ge=0, le=1)
    tools_allowed: bool = False
    network_proxy_allowed: bool = False
    configuration_access_allowed: bool = False

    @model_validator(mode="after")
    def enforce_provider_boundary(self) -> StructuredLlmRequest:
        if self.tools_allowed or self.network_proxy_allowed or self.configuration_access_allowed:
            raise ValueError("structured LLM request cannot expose execution capabilities")
        if {item.evidence_id for item in self.contexts} != set(self.allowed_evidence_ids):
            raise ValueError("LLM allowed evidence ids must exactly match RAG contexts")
        return self


class StructuredLlmResponse(DomainModel):
    provider_request_id: str
    model_version: str
    structured_output: dict[str, JsonValue]
    used_evidence_ids: tuple[str, ...]


class StructuredTransport(Protocol):
    def invoke(self, request: StructuredLlmRequest) -> StructuredLlmResponse: ...


class StructuredLlmProvider:
    def __init__(self, transport: StructuredTransport) -> None:
        self._transport = transport

    def complete[T: BaseModel](self, *, request: StructuredLlmRequest, output_model: type[T]) -> T:
        response = self._transport.invoke(request)
        if response.provider_request_id != request.request_id:
            raise ValueError("AQ-LLM-REQUEST-ID-MISMATCH")
        if not set(response.used_evidence_ids).issubset(request.allowed_evidence_ids):
            raise ValueError("AQ-LLM-EVIDENCE-ESCALATION")
        return output_model.model_validate(response.structured_output)
