from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisquant.domain.base import DomainModel
from aegisquant.intelligence.providers import (
    StructuredLlmProvider,
    StructuredLlmRequest,
    StructuredLlmResponse,
)
from aegisquant.intelligence.rag import RagContext
from aegisquant.research.proposals import ApprovalState, EventProposal, assert_experiment_launchable
from tests.p08_helpers import NOW, approved_proposal


class _ExpectedOutput(DomainModel):
    proposal_id: str


class _InvalidTransport:
    def invoke(self, request: StructuredLlmRequest) -> StructuredLlmResponse:
        return StructuredLlmResponse(
            provider_request_id=request.request_id,
            model_version="local-contract-v1",
            structured_output={"unexpected": True},
            used_evidence_ids=("evidence-1",),
        )


def test_invalid_structured_ai_output_cannot_start_experiment(tmp_path: Path) -> None:
    request = StructuredLlmRequest(
        request_id="request-1",
        provider_id="injected-test-provider",
        model_id="local-contract",
        schema_id="experiment-proposal-v1",
        system_instruction="Return only a research proposal.",
        contexts=(
            RagContext(
                evidence_id="evidence-1",
                source_policy_id="policy-1",
                text="bounded external evidence",
                available_at_utc=NOW,
            ),
        ),
        allowed_evidence_ids=("evidence-1",),
    )
    provider = StructuredLlmProvider(_InvalidTransport())
    with pytest.raises(ValidationError):
        provider.complete(request=request, output_model=_ExpectedOutput)
    assert not (tmp_path / "experiment-events.jsonl").exists()

    assert_experiment_launchable(approved_proposal())


def test_event_proposal_rejects_execution_fields_and_ai_self_approval() -> None:
    payload = {
        "proposal_id": "event-proposal-1",
        "event_type": "MACRO_RELEASE",
        "claim_ids": ("claim-1",),
        "evidence_ids": ("evidence-1",),
        "ai_generated": True,
        "state": ApprovalState.PROPOSED,
        "created_at_utc": NOW,
        "order": "BUY",
    }
    with pytest.raises(ValidationError):
        EventProposal.model_validate(payload)
    payload.pop("order")
    payload.update({"state": ApprovalState.APPROVED, "approved_by": "ai"})
    with pytest.raises(ValidationError, match="AI cannot approve"):
        EventProposal.model_validate(payload)
