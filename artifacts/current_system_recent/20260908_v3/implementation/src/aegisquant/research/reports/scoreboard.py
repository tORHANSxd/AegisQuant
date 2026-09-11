"""Baseline scoreboard that exposes gross/net economics and negative results."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import (
    FiniteDecimal,
    NonNegativeDecimal,
    UnitInterval,
    canonical_result,
)
from aegisquant.research.models import ResearchModality


class CandidateStatus(StrEnum):
    PASSED_DEVELOPMENT = "PASSED_DEVELOPMENT"
    HELD = "HELD"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ScoreboardEntry(DomainModel):
    candidate_id: str
    candidate_name: str
    modality: ResearchModality | None
    gross_return: FiniteDecimal
    fee_cost: NonNegativeDecimal
    spread_cost: NonNegativeDecimal
    slippage_cost: NonNegativeDecimal
    impact_cost: NonNegativeDecimal
    funding_cost: FiniteDecimal
    borrow_cost: NonNegativeDecimal
    net_return: FiniteDecimal
    sharpe: FiniteDecimal | None
    psr: UnitInterval | None
    dsr: UnitInterval | None
    pbo: UnitInterval | None
    maximum_drawdown: UnitInterval
    positive_folds: int = Field(ge=0)
    total_folds: int = Field(gt=0)
    event_incremental_net: FiniteDecimal | None
    total_trials: int = Field(gt=0)
    status: CandidateStatus
    negative_result: str | None
    final_holdout_opened: bool = False

    @model_validator(mode="after")
    def validate_entry(self) -> ScoreboardEntry:
        costs = (
            self.fee_cost
            + self.spread_cost
            + self.slippage_cost
            + self.impact_cost
            + self.funding_cost
            + self.borrow_cost
        )
        if self.net_return != canonical_result(self.gross_return - costs):
            raise ValueError("scoreboard net return must reconcile all cost components")
        if self.positive_folds > self.total_folds:
            raise ValueError("positive folds cannot exceed total folds")
        if (
            self.status in {CandidateStatus.REJECTED, CandidateStatus.FAILED}
            and not self.negative_result
        ):
            raise ValueError("rejected and failed candidates require a negative result")
        return self


def _format(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def render_baseline_scoreboard(entries: tuple[ScoreboardEntry, ...]) -> str:
    if not entries:
        raise ValueError("baseline scoreboard requires candidates")
    if not any(item.negative_result for item in entries):
        raise ValueError("baseline scoreboard must retain negative results")
    status_rank = {
        CandidateStatus.PASSED_DEVELOPMENT: 3,
        CandidateStatus.HELD: 2,
        CandidateStatus.REJECTED: 1,
        CandidateStatus.FAILED: 0,
    }
    ordered = sorted(
        entries,
        key=lambda item: (
            status_rank[item.status],
            item.net_return,
            item.dsr or Decimal("-1"),
            -item.maximum_drawdown,
            item.candidate_id,
        ),
        reverse=True,
    )
    lines = [
        "# P07 Baseline Scoreboard",
        "",
        "开发期 OOS 结果；最终 holdout 未开启。本表按状态、净收益、DSR 和回撤综合排序，"
        "不以单一 Sharpe 排名。所有金额均为归一化收益率。",
        "",
        "| Candidate | Modality | Gross | Fee | Spread | Slippage | Impact | Funding | Borrow | Net | Sharpe | PSR | DSR | PBO | Max DD | Positive folds | Event increment | Trials | Status |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in ordered:
        lines.append(
            "| "
            + " | ".join(
                (
                    item.candidate_name,
                    item.modality.value if item.modality else "STRATEGY",
                    _format(item.gross_return),
                    _format(item.fee_cost),
                    _format(item.spread_cost),
                    _format(item.slippage_cost),
                    _format(item.impact_cost),
                    _format(item.funding_cost),
                    _format(item.borrow_cost),
                    _format(item.net_return),
                    _format(item.sharpe),
                    _format(item.psr),
                    _format(item.dsr),
                    _format(item.pbo),
                    _format(item.maximum_drawdown),
                    f"{item.positive_folds}/{item.total_folds}",
                    _format(item.event_incremental_net),
                    str(item.total_trials),
                    item.status.value,
                )
            )
            + " |"
        )
    lines.extend(("", "## Negative results", ""))
    for item in sorted(entries, key=lambda value: value.candidate_id):
        if item.negative_result:
            lines.append(f"- `{item.candidate_id}`: {item.negative_result}")
    lines.extend(
        (
            "",
            "## Holdout",
            "",
            "所有条目的 `final_holdout_opened=false`。冻结前不可读取最终 holdout；本表不能作为实盘晋升证据。",
            "",
        )
    )
    return "\n".join(lines)


def write_baseline_scoreboard(path: Path, entries: tuple[ScoreboardEntry, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_baseline_scoreboard(entries), encoding="utf-8", newline="\n")
