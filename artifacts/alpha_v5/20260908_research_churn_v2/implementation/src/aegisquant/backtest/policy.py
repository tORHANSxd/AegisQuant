"""Repository-owned P06 policy loading without implicit numeric coercion."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import cast

import yaml
from pydantic import Field, model_validator

from aegisquant.backtest.models import (
    CostSchedule,
    HistoricalInstrumentRule,
    LatencyPolicy,
    MarginPolicy,
)
from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import NonNegativeDecimal, UnitInterval


class BenchmarkPolicy(DomainModel):
    vector_bars: int = Field(gt=0)
    event_count: int = Field(gt=0)
    maximum_vector_seconds: NonNegativeDecimal
    maximum_event_seconds: NonNegativeDecimal
    maximum_peak_memory_mib: NonNegativeDecimal
    stability_replays: int = Field(gt=1)


class BacktestPolicy(DomainModel):
    policy_version: str
    mutation_score_threshold: UnitInterval
    latency_policy: LatencyPolicy
    cost_schedules: tuple[CostSchedule, ...]
    instrument_rules: tuple[HistoricalInstrumentRule, ...]
    margin_policies: tuple[MarginPolicy, ...]
    benchmark: BenchmarkPolicy

    @model_validator(mode="after")
    def validate_policy(self) -> BacktestPolicy:
        if not self.cost_schedules or not self.instrument_rules or not self.margin_policies:
            raise ValueError("P06 policy requires cost, rule and margin versions")
        if self.mutation_score_threshold < Decimal("0.90"):
            raise ValueError("P06 mutation threshold cannot be below 90%")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> BacktestPolicy:
        loaded = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
        if not isinstance(loaded, dict):
            raise ValueError("backtest policy YAML must contain a mapping")
        # JSON-mode strict validation permits ISO timestamps and exact decimal strings while
        # continuing to reject YAML floats at the domain boundary.
        return cls.model_validate_json(
            json.dumps(loaded, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        )


def load_backtest_policy(path: Path) -> BacktestPolicy:
    """Load and strictly validate the repository-owned P06 policy."""

    return BacktestPolicy.from_yaml(path)
