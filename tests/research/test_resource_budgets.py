from __future__ import annotations

from decimal import Decimal

import pytest

from aegisquant.research.budgets import (
    BudgetExceededError,
    ResourceRequest,
    evaluate_budget,
    require_budget,
    run_with_oom_recovery,
)
from tests.p08_helpers import budget


def test_budget_rejects_gpu_calls_and_cloud_cost_before_work() -> None:
    request = ResourceRequest(
        trials=1,
        gpu_memory_mb=Decimal("1"),
        news_calls=1,
        cloud_cost_usd=Decimal("0.01"),
    )
    decision = evaluate_budget(budget=budget(), request=request)
    assert decision.allowed is False
    assert set(decision.reason_codes) == {
        "AQ-BUDGET-GPU-MEMORY",
        "AQ-BUDGET-NEWS-CALLS",
        "AQ-BUDGET-CLOUD-COST",
    }
    with pytest.raises(BudgetExceededError):
        require_budget(budget=budget(), request=request)


def test_oom_recovery_halves_batch_and_does_not_swallow_other_errors() -> None:
    attempted: list[int] = []

    def bounded(batch_size: int) -> str:
        attempted.append(batch_size)
        if batch_size > 2:
            raise RuntimeError("CUDA out of memory (simulated contract)")
        return "ok"

    result = run_with_oom_recovery(bounded, initial_batch_size=8)
    assert result.value == "ok"
    assert result.batch_size == 2
    assert attempted == [8, 4, 2]

    with pytest.raises(RuntimeError, match="unrelated"):
        run_with_oom_recovery(
            lambda _batch: (_ for _ in ()).throw(RuntimeError("unrelated")),
            initial_batch_size=2,
        )
