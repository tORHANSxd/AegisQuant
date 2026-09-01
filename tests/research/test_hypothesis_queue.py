from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisquant.research.hypotheses import (
    HypothesisAuthor,
    HypothesisProposal,
    HypothesisQueue,
    HypothesisSpec,
    ProposalState,
)
from tests.p08_helpers import NOW, budget


def _hypothesis() -> HypothesisSpec:
    return HypothesisSpec(
        hypothesis_id="hypothesis-p08-1",
        claim="事件证据改善开发期样本外方向预测",
        economic_rationale="独立一手证据可能降低事件状态不确定性",
        falsification_conditions=("开发期 OOS 不优于 market-only",),
        markets=("BTCUSDT",),
        horizons=("30m",),
        required_data=("market", "event_evidence"),
        feature_candidates=("event_credibility",),
        label_id="net-return-30m",
        baselines=("linear-market-only",),
        metrics=("mse", "net_return"),
        validation_policy_id="p07-walk-forward",
        compute_budget=budget(),
        search_space={"learning_rate": [0.01, 0.05]},
        expected_failure_modes=("event already priced",),
        source_lineage=("p04-source-policy",),
        created_by=HypothesisAuthor.AI,
        created_at_utc=NOW,
    )


def test_ai_hypothesis_requires_non_ai_approval_and_queue_is_hash_chained(
    tmp_path: Path,
) -> None:
    hypothesis = _hypothesis()
    queue = HypothesisQueue(tmp_path / "hypotheses.jsonl")
    queue.append(
        HypothesisProposal(
            proposal_id="proposal-1",
            hypothesis=hypothesis,
            state=ProposalState.PROPOSED,
            proposed_by="ai:local-test",
            recorded_at_utc=NOW,
        )
    )
    queue.append(
        HypothesisProposal(
            proposal_id="proposal-1",
            hypothesis=hypothesis,
            state=ProposalState.APPROVED,
            proposed_by="ai:local-test",
            reviewed_by="rule:schema-budget",
            decision_reason="schema and zero-external-call budget passed",
            recorded_at_utc=NOW,
        )
    )
    entries = queue.entries()
    assert len(entries) == 2
    assert entries[1].previous_hash == entries[0].entry_hash
    assert queue.approved() == (hypothesis,)

    with pytest.raises(ValidationError, match="AI cannot approve"):
        HypothesisProposal(
            proposal_id="proposal-2",
            hypothesis=hypothesis,
            state=ProposalState.APPROVED,
            proposed_by="ai:local-test",
            reviewed_by="ai",
            decision_reason="self approval",
            recorded_at_utc=NOW,
        )


def test_invalid_hypothesis_schema_is_rejected_before_queue(tmp_path: Path) -> None:
    payload = _hypothesis().model_dump(mode="python")
    payload["falsification_conditions"] = ()
    with pytest.raises(ValidationError):
        HypothesisSpec.model_validate(payload)
    assert not (tmp_path / "hypotheses.jsonl").exists()
    assert _hypothesis().compute_budget.max_cloud_cost_usd == Decimal("0")
