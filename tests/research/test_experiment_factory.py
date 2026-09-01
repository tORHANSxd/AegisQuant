# pyright: reportUnknownMemberType=false
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import optuna
import pytest

from aegisquant.research.experiments.artifacts import ArtifactRegistry
from aegisquant.research.experiments.factory import ExperimentFactory
from aegisquant.research.experiments.journal import (
    ExperimentEvent,
    ExperimentEventJournal,
    ExperimentEventType,
)
from aegisquant.research.experiments.optimization import run_optuna_search
from aegisquant.research.experiments.tracking import MlflowProjection
from aegisquant.research.proposals import ApprovalState
from tests.p08_helpers import approved_proposal


def test_artifact_registry_event_journal_and_mlflow_projection(tmp_path: Path) -> None:
    artifact = ArtifactRegistry(tmp_path / "registry").put_bytes(b"p08-model")
    registry = ArtifactRegistry(tmp_path / "registry")
    assert registry.resolve(artifact.sha256).read_bytes() == b"p08-model"
    assert registry.put_bytes(b"p08-model") == artifact

    journal = ExperimentEventJournal(tmp_path / "events.jsonl")
    journal.append(
        ExperimentEvent(
            event_id="run-1-started",
            run_id="run-1",
            event_type=ExperimentEventType.STARTED,
            recorded_at_utc=datetime.now(UTC),
        )
    )
    journal.append(
        ExperimentEvent(
            event_id="run-1-succeeded",
            run_id="run-1",
            event_type=ExperimentEventType.SUCCEEDED,
            recorded_at_utc=datetime.now(UTC),
            details={"artifact": artifact.sha256},
        )
    )
    assert [item.event_type for item in journal.history("run-1")] == [
        ExperimentEventType.STARTED,
        ExperimentEventType.SUCCEEDED,
    ]

    projection = MlflowProjection(tmp_path / "mlflow")
    mlflow_run_id = projection.start_run(
        run_name="run-1", parameters={"seed": 7}, tags={"phase": "P08"}
    )
    projection.finish_run(
        mlflow_run_id=mlflow_run_id,
        succeeded=True,
        metrics={"loss": 0.1},
        artifact_hashes={"model": artifact.sha256},
    )
    run = projection.client.get_run(mlflow_run_id)
    assert run.info.status == "FINISHED"
    assert run.data.tags["artifact.sha256.model"] == artifact.sha256


def test_optuna_records_success_prune_and_error_trials(tmp_path: Path) -> None:
    journal = ExperimentEventJournal(tmp_path / "trial-events.jsonl")

    def objective(trial: optuna.Trial) -> float:
        trial.suggest_float("x", 0.0, 1.0)
        if trial.number == 1:
            raise optuna.TrialPruned("bounded prune")
        if trial.number == 2:
            raise ValueError("bounded failure")
        return 1.0

    study = run_optuna_search(
        search_id="search-p08",
        proposal=approved_proposal(max_trials=3),
        journal=journal,
        storage_path=tmp_path / "optuna.log",
        objective=objective,
        n_trials=3,
        seed=7,
    )
    terminal = {
        entry.event.event_type
        for entry in journal.entries()
        if entry.event.event_type is not ExperimentEventType.STARTED
    }
    assert len(study.trials) == 3
    assert terminal == {
        ExperimentEventType.SUCCEEDED,
        ExperimentEventType.PRUNED,
        ExperimentEventType.ERROR,
    }


def test_factory_rejects_unapproved_proposal_before_mlflow_run(tmp_path: Path) -> None:
    journal = ExperimentEventJournal(tmp_path / "factory-events.jsonl")
    projection = MlflowProjection(tmp_path / "factory-mlflow")
    factory = ExperimentFactory(journal=journal, projection=projection)
    proposal = approved_proposal().model_copy(
        update={"state": ApprovalState.PROPOSED, "approved_by": None}
    )
    with pytest.raises(PermissionError, match="NOT-APPROVED"):
        factory.start(
            proposal=proposal,
            run_id="must-not-start",
            occurred_at=datetime.now(UTC),
            parameters={"seed": 7},
        )
    assert journal.entries() == ()
    assert projection.client.search_runs([projection.experiment_id]) == []
