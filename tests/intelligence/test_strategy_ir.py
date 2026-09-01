from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegisquant.intelligence.static_analysis.extraction import (
    ir_evidence_ids,
    validate_ai_knowledge_proposal,
)
from aegisquant.intelligence.static_analysis.models import EvidenceStatus, KnowledgeProposal
from tests.intelligence.helpers import extract_fixture


def test_rule_extraction_links_every_supported_assertion_to_exact_evidence(
    project_root: Path,
) -> None:
    result = extract_fixture(
        project_root / "tests/fixtures/p09/joinquant_manual_export/code/strategy.py"
    )
    ir = result.strategy_ir
    evidence_ids = {item.evidence_id for item in result.evidence_spans}
    assert ir_evidence_ids(ir) == evidence_ids
    assert ir.data_requirements == ("attribute_history", "get_index_stocks")
    assert ir.entries and ir.exits and ir.rebalance and ir.execution_assumptions
    assert all(
        item.evidence_ids
        for group in (
            ir.features,
            ir.signals,
            ir.entries,
            ir.exits,
            ir.position_sizing,
            ir.rebalance,
            ir.execution_assumptions,
            ir.risk_controls,
        )
        for item in group
        if item.status is EvidenceStatus.SUPPORTED
    )
    assert ir.backtest_evidence["source_performance_accepted"] is False
    assert result.source_code_executed is False


def test_ai_ir_lane_rejects_fabricated_or_unused_evidence(project_root: Path) -> None:
    result = extract_fixture(
        project_root / "tests/fixtures/p09/joinquant_manual_export/code/strategy.py"
    )
    evidence_ids = tuple(item.evidence_id for item in result.evidence_spans)
    proposal = KnowledgeProposal(
        proposal_id="p09-ai-proposal",
        strategy_id=result.strategy_ir.strategy_id,
        source_ids=result.strategy_ir.source_ids,
        claimed_evidence_ids=evidence_ids,
        candidate_ir=result.strategy_ir,
    )
    assert validate_ai_knowledge_proposal(proposal, result.evidence_spans) == proposal
    fabricated = proposal.model_copy(
        update={"claimed_evidence_ids": (*proposal.claimed_evidence_ids, "fabricated-evidence")}
    )
    with pytest.raises(ValueError, match="fabricated evidence"):
        validate_ai_knowledge_proposal(fabricated, result.evidence_spans)


def test_ai_proposal_contract_has_no_execution_or_publication_state(project_root: Path) -> None:
    result = extract_fixture(
        project_root / "tests/fixtures/p09/joinquant_manual_export/code/strategy.py"
    )
    proposal = KnowledgeProposal(
        proposal_id="p09-ai-boundary",
        strategy_id=result.strategy_ir.strategy_id,
        source_ids=result.strategy_ir.source_ids,
        claimed_evidence_ids=tuple(item.evidence_id for item in result.evidence_spans),
        candidate_ir=result.strategy_ir,
    )
    assert proposal.state == "PROPOSED"
    assert proposal.action == "RESEARCH_ONLY"
    assert proposal.ai_generated is True
    assert datetime(2026, 9, 2, tzinfo=UTC).tzinfo is UTC
