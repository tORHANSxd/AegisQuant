"""Fail-closed research budgets and bounded out-of-memory recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from pydantic import Field

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import NonNegativeDecimal


class ResourceBudget(DomainModel):
    max_trials: int = Field(ge=1)
    max_train_seconds: NonNegativeDecimal
    max_inference_latency_ms: NonNegativeDecimal
    max_ram_mb: NonNegativeDecimal
    max_gpu_memory_mb: NonNegativeDecimal
    max_x_calls: int = Field(ge=0)
    max_news_calls: int = Field(ge=0)
    max_cloud_cost_usd: NonNegativeDecimal


class ResourceRequest(DomainModel):
    trials: int = Field(ge=0)
    train_seconds: NonNegativeDecimal = Decimal("0")
    inference_latency_ms: NonNegativeDecimal = Decimal("0")
    ram_mb: NonNegativeDecimal = Decimal("0")
    gpu_memory_mb: NonNegativeDecimal = Decimal("0")
    x_calls: int = Field(default=0, ge=0)
    news_calls: int = Field(default=0, ge=0)
    cloud_cost_usd: NonNegativeDecimal = Decimal("0")


class BudgetDecision(DomainModel):
    allowed: bool
    reason_codes: tuple[str, ...]


class BudgetExceededError(RuntimeError):
    """Raised before work starts when a resource request exceeds approval."""


def evaluate_budget(*, budget: ResourceBudget, request: ResourceRequest) -> BudgetDecision:
    checks = (
        (request.trials <= budget.max_trials, "AQ-BUDGET-TRIALS"),
        (request.train_seconds <= budget.max_train_seconds, "AQ-BUDGET-TRAIN-TIME"),
        (
            request.inference_latency_ms <= budget.max_inference_latency_ms,
            "AQ-BUDGET-INFERENCE-LATENCY",
        ),
        (request.ram_mb <= budget.max_ram_mb, "AQ-BUDGET-RAM"),
        (request.gpu_memory_mb <= budget.max_gpu_memory_mb, "AQ-BUDGET-GPU-MEMORY"),
        (request.x_calls <= budget.max_x_calls, "AQ-BUDGET-X-CALLS"),
        (request.news_calls <= budget.max_news_calls, "AQ-BUDGET-NEWS-CALLS"),
        (request.cloud_cost_usd <= budget.max_cloud_cost_usd, "AQ-BUDGET-CLOUD-COST"),
    )
    reasons = tuple(code for passed, code in checks if not passed)
    return BudgetDecision(allowed=not reasons, reason_codes=reasons)


def require_budget(*, budget: ResourceBudget, request: ResourceRequest) -> None:
    decision = evaluate_budget(budget=budget, request=request)
    if not decision.allowed:
        raise BudgetExceededError(",".join(decision.reason_codes))


@dataclass(frozen=True, slots=True)
class OomRecoveryResult[T]:
    value: T
    batch_size: int
    attempts: int


def run_with_oom_recovery[T](
    operation: Callable[[int], T], *, initial_batch_size: int, minimum_batch_size: int = 1
) -> OomRecoveryResult[T]:
    """Retry only recognized OOM failures while halving the batch size."""
    if initial_batch_size < minimum_batch_size or minimum_batch_size < 1:
        raise ValueError("invalid OOM recovery batch bounds")
    batch_size = initial_batch_size
    attempts = 0
    while True:
        attempts += 1
        try:
            return OomRecoveryResult(
                value=operation(batch_size), batch_size=batch_size, attempts=attempts
            )
        except (MemoryError, RuntimeError) as error:
            is_oom = isinstance(error, MemoryError) or "out of memory" in str(error).casefold()
            if not is_oom or batch_size <= minimum_batch_size:
                raise
            batch_size = max(minimum_batch_size, batch_size // 2)
