from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.intelligence.committee import ExpertRole
from aegisquant.intelligence.world.events import (
    AuditedCommitteeDecision,
    CommitteePath,
    run_committee_path,
)
from tests.intelligence.world.helpers import committee_findings


@pytest.mark.parametrize(
    ("path", "context_items", "passes"),
    [(CommitteePath.FAST, 24, 1), (CommitteePath.DEEP, 128, 3)],
)
def test_fast_and_deep_paths_keep_skeptic_and_fixed_budget(
    path: CommitteePath, context_items: int, passes: int
) -> None:
    decision = run_committee_path(
        path=path,
        findings=committee_findings(),
        evidence_ids=("evidence-1",),
        policy_ids=("policy-v1",),
        model_versions=("committee-v1",),
    )
    roles = {item.role for item in decision.committee.findings}
    assert ExpertRole.SKEPTIC in roles
    assert decision.max_context_items == context_items
    assert decision.reasoning_passes == passes
    assert decision.action == "RESEARCH_PROPOSAL_ONLY"


def test_low_evidence_or_expert_abstention_is_structured() -> None:
    decision = run_committee_path(
        path=CommitteePath.DEEP,
        findings=committee_findings(abstain_role=ExpertRole.SKEPTIC),
        evidence_ids=("evidence-1", "unused-evidence"),
        policy_ids=("policy-v1",),
        model_versions=("committee-v1",),
    )
    assert decision.committee.arbiter.should_abstain is True
    assert "INSUFFICIENT_CORROBORATION" in decision.committee.arbiter.abstain_reasons


def test_committee_cannot_escalate_evidence_or_publish_order() -> None:
    with pytest.raises(ValueError, match="EVIDENCE-ESCALATION"):
        run_committee_path(
            path=CommitteePath.FAST,
            findings=committee_findings("unapproved-evidence"),
            evidence_ids=("approved-evidence",),
            policy_ids=("policy-v1",),
            model_versions=("committee-v1",),
        )
    valid = run_committee_path(
        path=CommitteePath.FAST,
        findings=committee_findings(),
        evidence_ids=("evidence-1",),
        policy_ids=("policy-v1",),
        model_versions=("committee-v1",),
    )
    payload = valid.model_dump()
    payload["action"] = "ORDER_COMMAND"
    with pytest.raises(ValidationError, match="cannot construct or submit orders"):
        AuditedCommitteeDecision.model_validate(payload)


def test_single_social_post_never_becomes_an_order() -> None:
    decision = run_committee_path(
        path=CommitteePath.FAST,
        findings=committee_findings("single-social-post"),
        evidence_ids=("single-social-post",),
        policy_ids=("social-restricted-v1",),
        model_versions=("committee-v1",),
    )
    assert decision.committee.arbiter.evidence_coverage == Decimal("1")
    assert decision.action == "RESEARCH_PROPOSAL_ONLY"
    assert "OrderCommand" not in decision.model_dump_json()
