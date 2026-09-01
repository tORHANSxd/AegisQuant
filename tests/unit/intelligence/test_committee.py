from __future__ import annotations

import pytest

from aegisquant.intelligence.committee import arbitrate
from tests.p08_intelligence_helpers import committee_findings


def test_full_committee_arbiter_uses_only_supplied_evidence() -> None:
    result = arbitrate(
        findings=committee_findings(),
        allowed_evidence_ids=frozenset({"evidence-1", "evidence-2"}),
    )
    assert result.arbiter.evidence_ids == ("evidence-1", "evidence-2")
    assert result.arbiter.evidence_coverage == 1
    assert result.arbiter.should_abstain is False
    assert result.arbiter.action == "RESEARCH_PROPOSAL_ONLY"


def test_arbiter_rejects_evidence_escalation() -> None:
    with pytest.raises(ValueError, match="EVIDENCE-ESCALATION"):
        arbitrate(
            findings=committee_findings(),
            allowed_evidence_ids=frozenset({"evidence-1"}),
        )
