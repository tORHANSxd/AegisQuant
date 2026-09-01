from __future__ import annotations

from decimal import Decimal

import pytest

from aegisquant.research.council import CandidateState, CouncilCandidate, run_model_council
from aegisquant.research.models.baselines import ResearchModality


def _candidate(
    model_id: str, family: str, modality: ResearchModality, loss: str
) -> CouncilCandidate:
    return CouncilCandidate(
        model_id=model_id,
        family=family,
        modality=modality,
        target="net_return_30m",
        split_sha256="a" * 64,
        cost_policy_sha256="b" * 64,
        search_budget_sha256="c" * 64,
        seed=7,
        state=CandidateState.EVALUATED,
        primary_loss=Decimal(loss),
        net_return=Decimal("0"),
        train_seconds=Decimal("1"),
        peak_memory_mb=Decimal("100"),
    )


def test_complex_model_is_eliminated_without_incremental_oos_improvement() -> None:
    candidates = (
        _candidate("linear", "LINEAR", ResearchModality.MARKET_ONLY, "0.10"),
        _candidate("event-tree", "LIGHTGBM", ResearchModality.EVENT_ONLY, "0.12"),
        _candidate("fused-deep", "TCN", ResearchModality.FUSED, "0.099"),
    )
    report = run_model_council(
        candidates=candidates,
        baseline_model_id="linear",
        minimum_incremental_improvement=Decimal("0.01"),
    )
    assert report.selected_model_id == "linear"
    assert report.complexity_privilege is False
    assert report.final_holdout_opened is False

    unfair = candidates[1].model_copy(update={"split_sha256": "d" * 64})
    with pytest.raises(ValueError, match="share split"):
        run_model_council(
            candidates=(candidates[0], unfair, candidates[2]),
            baseline_model_id="linear",
            minimum_incremental_improvement=Decimal("0.01"),
        )
