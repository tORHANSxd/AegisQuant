"""Fail-closed launcher that couples approval, audit journal, and MLflow projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue

from aegisquant.research.experiments.journal import (
    ExperimentEvent,
    ExperimentEventJournal,
    ExperimentEventType,
)
from aegisquant.research.experiments.tracking import MlflowProjection
from aegisquant.research.proposals import ExperimentProposal, assert_experiment_launchable


@dataclass(frozen=True, slots=True)
class TrackedRun:
    run_id: str
    mlflow_run_id: str


class ExperimentFactory:
    def __init__(self, *, journal: ExperimentEventJournal, projection: MlflowProjection) -> None:
        self.journal = journal
        self.projection = projection

    def start(
        self,
        *,
        proposal: ExperimentProposal,
        run_id: str,
        occurred_at: datetime,
        parameters: dict[str, JsonValue],
    ) -> TrackedRun:
        assert_experiment_launchable(proposal)
        self.journal.append(
            ExperimentEvent(
                event_id=f"{run_id}-started",
                run_id=run_id,
                event_type=ExperimentEventType.STARTED,
                recorded_at_utc=occurred_at,
                details={"proposal_id": proposal.proposal_id},
            )
        )
        try:
            mlflow_run_id = self.projection.start_run(
                run_name=run_id,
                parameters=parameters,
                tags={
                    "proposal_id": proposal.proposal_id,
                    "hypothesis_id": proposal.hypothesis_id,
                    "ai_proposed": proposal.ai_generated,
                },
            )
        except Exception as error:
            self.journal.append(
                ExperimentEvent(
                    event_id=f"{run_id}-projection-error",
                    run_id=run_id,
                    event_type=ExperimentEventType.ERROR,
                    recorded_at_utc=occurred_at,
                    details={"reason": f"MLflow projection failed: {type(error).__name__}"},
                )
            )
            raise
        return TrackedRun(run_id=run_id, mlflow_run_id=mlflow_run_id)

    def finish(
        self,
        *,
        run: TrackedRun,
        occurred_at: datetime,
        succeeded: bool,
        metrics: dict[str, float],
        artifact_hashes: dict[str, str],
        failure_reason: str | None = None,
    ) -> None:
        if succeeded == (failure_reason is not None):
            raise ValueError("experiment success and failure reason disagree")
        try:
            self.projection.finish_run(
                mlflow_run_id=run.mlflow_run_id,
                succeeded=succeeded,
                metrics=metrics,
                artifact_hashes=artifact_hashes,
                failure_reason=failure_reason,
            )
        except Exception as error:
            self.journal.append(
                ExperimentEvent(
                    event_id=f"{run.run_id}-projection-error",
                    run_id=run.run_id,
                    event_type=ExperimentEventType.ERROR,
                    recorded_at_utc=occurred_at,
                    details={"reason": f"MLflow projection failed: {type(error).__name__}"},
                )
            )
            raise
        event_type = ExperimentEventType.SUCCEEDED if succeeded else ExperimentEventType.FAILED
        metric_values: dict[str, JsonValue] = dict(metrics)
        artifact_values: dict[str, JsonValue] = dict(artifact_hashes)
        details: dict[str, JsonValue] = {
            "metrics": metric_values,
            "artifacts": artifact_values,
        }
        if failure_reason is not None:
            details["reason"] = failure_reason
        self.journal.append(
            ExperimentEvent(
                event_id=f"{run.run_id}-{event_type.value.casefold()}",
                run_id=run.run_id,
                event_type=event_type,
                recorded_at_utc=occurred_at,
                details=details,
            )
        )
