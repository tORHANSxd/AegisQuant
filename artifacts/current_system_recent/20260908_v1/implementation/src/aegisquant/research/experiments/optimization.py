# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Bounded Optuna search that journals every trial, including failures."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import optuna
from optuna.storages import JournalStorage
from optuna.storages.journal import JournalFileBackend

from aegisquant.research.experiments.journal import (
    ExperimentEvent,
    ExperimentEventJournal,
    ExperimentEventType,
)
from aegisquant.research.proposals import ExperimentProposal, assert_experiment_launchable


def run_optuna_search(
    *,
    search_id: str,
    proposal: ExperimentProposal,
    journal: ExperimentEventJournal,
    storage_path: Path,
    objective: Callable[[optuna.Trial], float],
    n_trials: int,
    timeout_seconds: float | None = None,
    seed: int = 0,
) -> optuna.Study:
    assert_experiment_launchable(proposal)
    if n_trials < 1 or n_trials > proposal.approved_budget.max_trials:
        raise ValueError("AQ-OPTUNA-SEARCH-BUDGET-EXCEEDED")
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage = JournalStorage(JournalFileBackend(str(storage_path)))
    study = optuna.create_study(
        study_name=search_id,
        storage=storage,
        load_if_exists=False,
        sampler=optuna.samplers.TPESampler(seed=seed),
        direction="maximize",
    )

    def audited_objective(trial: optuna.Trial) -> float:
        run_id = f"{search_id}-trial-{trial.number}"
        now = datetime.now(UTC)
        journal.append(
            ExperimentEvent(
                event_id=f"{run_id}-started",
                run_id=run_id,
                trial_number=trial.number,
                event_type=ExperimentEventType.STARTED,
                recorded_at_utc=now,
                details={"search_id": search_id},
            )
        )
        try:
            value = float(objective(trial))
        except optuna.TrialPruned as error:
            journal.append(
                ExperimentEvent(
                    event_id=f"{run_id}-pruned",
                    run_id=run_id,
                    trial_number=trial.number,
                    event_type=ExperimentEventType.PRUNED,
                    recorded_at_utc=datetime.now(UTC),
                    details={"reason": str(error) or "trial pruned"},
                )
            )
            raise
        except Exception as error:
            journal.append(
                ExperimentEvent(
                    event_id=f"{run_id}-error",
                    run_id=run_id,
                    trial_number=trial.number,
                    event_type=ExperimentEventType.ERROR,
                    recorded_at_utc=datetime.now(UTC),
                    details={"reason": f"{type(error).__name__}: {error}"[:500]},
                )
            )
            raise
        journal.append(
            ExperimentEvent(
                event_id=f"{run_id}-succeeded",
                run_id=run_id,
                trial_number=trial.number,
                event_type=ExperimentEventType.SUCCEEDED,
                recorded_at_utc=datetime.now(UTC),
                details={"objective": value, "parameters": trial.params},
            )
        )
        return value

    study.optimize(
        audited_objective,
        n_trials=n_trials,
        timeout=timeout_seconds,
        catch=(Exception,),
    )
    return study
