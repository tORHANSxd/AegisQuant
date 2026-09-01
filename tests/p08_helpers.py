from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.research.budgets import ResourceBudget, ResourceRequest
from aegisquant.research.models.baselines import BaselineDataset
from aegisquant.research.proposals import ApprovalState, ExperimentProposal

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def model_dataset(*, start: int, count: int) -> BaselineDataset:
    features = tuple(
        (
            float(index + start) / 10,
            float((index + start) % 5) / 5,
            float(((index + start) % 3) - 1),
            float((index + start) % 2),
        )
        for index in range(count)
    )
    targets = tuple(row[0] * 0.2 - row[1] * 0.1 + row[2] * 0.03 + row[3] * 0.01 for row in features)
    return BaselineDataset(
        sample_ids=tuple(f"sample-{start + index:03d}" for index in range(count)),
        timestamps=tuple(NOW + timedelta(hours=start + index) for index in range(count)),
        feature_names=("market_price", "market_liquidity", "event_score", "event_flag"),
        features=features,
        targets=targets,
    )


def budget(*, max_trials: int = 4) -> ResourceBudget:
    return ResourceBudget(
        max_trials=max_trials,
        max_train_seconds=Decimal("30"),
        max_inference_latency_ms=Decimal("1000"),
        max_ram_mb=Decimal("2048"),
        max_gpu_memory_mb=Decimal("0"),
        max_x_calls=0,
        max_news_calls=0,
        max_cloud_cost_usd=Decimal("0"),
    )


def approved_proposal(*, max_trials: int = 4) -> ExperimentProposal:
    return ExperimentProposal(
        proposal_id="proposal-p08-1",
        hypothesis_id="hypothesis-p08-1",
        model_id="model-p08-1",
        dataset_sha256="a" * 64,
        split_sha256="b" * 64,
        cost_policy_sha256="c" * 64,
        requested_resources=ResourceRequest(trials=max_trials),
        approved_budget=budget(max_trials=max_trials),
        ai_generated=True,
        state=ApprovalState.APPROVED,
        approved_by="rule:p08-budget-and-schema",
        created_at_utc=NOW,
    )
