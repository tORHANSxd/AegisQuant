from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aegisquant.research.experiments import (
    ExperimentLedger,
    ExperimentRecord,
    ExperimentStatus,
    PromotionDecision,
)
from aegisquant.research.models import ResearchModality
from aegisquant.research.reports import (
    CandidateStatus,
    ScoreboardEntry,
    render_baseline_scoreboard,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def experiment(run_id: str, status: ExperimentStatus) -> ExperimentRecord:
    failed = status is not ExperimentStatus.SUCCEEDED
    return ExperimentRecord(
        run_id=run_id,
        status=status,
        code_commit="a" * 40,
        environment_sha256="1" * 64,
        dataset_sha256="2" * 64,
        feature_set_sha256="3" * 64,
        label_set_sha256="4" * 64,
        universe_sha256="5" * 64,
        split_sha256="6" * 64,
        cost_policy_sha256="7" * 64,
        model_id="linear-v1",
        hyperparameters={"alpha": 0.1},
        seed=7,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=2),
        cpu_seconds=Decimal("1.2"),
        peak_memory_mb=Decimal("100"),
        metrics={} if failed else {"net_return": Decimal("0.01")},
        artifact_hashes={} if failed else {"predictions": "8" * 64},
        ai_proposed=False,
        failure_reason="expected research failure" if failed else None,
        promotion_decision=(PromotionDecision.REJECT if failed else PromotionDecision.HOLD),
    )


def scoreboard_entry(
    candidate_id: str,
    *,
    status: CandidateStatus,
    sharpe: Decimal,
    net: Decimal,
    negative: str | None,
) -> ScoreboardEntry:
    total_cost = Decimal("0.006")
    return ScoreboardEntry(
        candidate_id=candidate_id,
        candidate_name=candidate_id,
        modality=ResearchModality.FUSED,
        gross_return=net + total_cost,
        fee_cost=Decimal("0.001"),
        spread_cost=Decimal("0.001"),
        slippage_cost=Decimal("0.001"),
        impact_cost=Decimal("0.001"),
        funding_cost=Decimal("0.001"),
        borrow_cost=Decimal("0.001"),
        net_return=net,
        sharpe=sharpe,
        psr=Decimal("0.8"),
        dsr=Decimal("0.7"),
        pbo=Decimal("0.2"),
        maximum_drawdown=Decimal("0.1"),
        positive_folds=4,
        total_folds=5,
        event_incremental_net=Decimal("0.001"),
        total_trials=10,
        status=status,
        negative_result=negative,
        final_holdout_opened=False,
    )


def test_experiment_ledger_retains_success_failure_error_and_detects_tampering(
    tmp_path: Path,
) -> None:
    path = tmp_path / "experiments.jsonl"
    ledger = ExperimentLedger(path)
    for status in ExperimentStatus:
        ledger.append(experiment(status.value.lower(), status))
    assert [item.status for item in ledger.query()] == list(ExperimentStatus)
    assert len(ledger.query(status=ExperimentStatus.FAILED)) == 1
    with pytest.raises(ValueError, match="RUN-ID-DUPLICATE"):
        ledger.append(experiment("failed", ExperimentStatus.FAILED))

    tampered = path.read_text(encoding="utf-8").replace("linear-v1", "linear-v2", 1)
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        ledger.entries()


def test_scoreboard_reports_costs_robust_statistics_negative_results_and_locked_holdout() -> None:
    high_sharpe_rejected = scoreboard_entry(
        "high-sharpe-rejected",
        status=CandidateStatus.REJECTED,
        sharpe=Decimal("3"),
        net=Decimal("-0.01"),
        negative="failed cost stress and fold consistency",
    )
    lower_sharpe_passed = scoreboard_entry(
        "lower-sharpe-passed",
        status=CandidateStatus.PASSED_DEVELOPMENT,
        sharpe=Decimal("1"),
        net=Decimal("0.02"),
        negative=None,
    )
    report = render_baseline_scoreboard((high_sharpe_rejected, lower_sharpe_passed))
    assert report.index("lower-sharpe-passed") < report.index("high-sharpe-rejected")
    assert "PSR" in report and "DSR" in report and "PBO" in report
    assert "Negative results" in report
    assert "final_holdout_opened=false" in report
    assert "Fee" in report and "Spread" in report and "Impact" in report
