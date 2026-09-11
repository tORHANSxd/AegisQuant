"""Deterministic research reports."""

from aegisquant.research.reports.scoreboard import (
    CandidateStatus,
    ScoreboardEntry,
    render_baseline_scoreboard,
    write_baseline_scoreboard,
)

__all__ = [
    "CandidateStatus",
    "ScoreboardEntry",
    "render_baseline_scoreboard",
    "write_baseline_scoreboard",
]
