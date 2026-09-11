# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Local MLflow projection; the append-only journal remains authoritative."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from mlflow.entities import RunStatus
from mlflow.tracking import MlflowClient
from pydantic import JsonValue

SECRET_KEYS: Final = frozenset({"password", "secret", "cookie", "token", "api_key", "apikey"})


def _safe_metadata(values: dict[str, JsonValue]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in values.items():
        normalized = key.casefold().replace("-", "_")
        if any(blocked in normalized for blocked in SECRET_KEYS):
            raise ValueError("AQ-MLFLOW-SECRET-METADATA-REJECTED")
        output[key] = str(value)
    return output


class MlflowProjection:
    def __init__(self, root: Path, *, experiment_name: str = "aegisquant-p08") -> None:
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise ValueError("MLflow root cannot be a symlink")
        database_path = (root / "mlflow.db").resolve()
        artifact_root = (root / "artifacts").resolve()
        artifact_root.mkdir(parents=True, exist_ok=True)
        self.tracking_uri = f"sqlite:///{database_path.as_posix()}"
        self.client = MlflowClient(tracking_uri=self.tracking_uri)
        experiment = self.client.get_experiment_by_name(experiment_name)
        self.experiment_id: str = str(
            experiment.experiment_id
            if experiment is not None
            else self.client.create_experiment(
                experiment_name, artifact_location=artifact_root.as_uri()
            )
        )

    def start_run(
        self, *, run_name: str, parameters: dict[str, JsonValue], tags: dict[str, JsonValue]
    ) -> str:
        safe_parameters = _safe_metadata(parameters)
        safe_tags = _safe_metadata(tags)
        run = self.client.create_run(
            self.experiment_id,
            tags={"mlflow.runName": run_name, **safe_tags},
        )
        for key, value in safe_parameters.items():
            self.client.log_param(run.info.run_id, key, value)
        return str(run.info.run_id)

    def finish_run(
        self,
        *,
        mlflow_run_id: str,
        succeeded: bool,
        metrics: dict[str, float],
        artifact_hashes: dict[str, str],
        failure_reason: str | None = None,
    ) -> None:
        for key, value in metrics.items():
            self.client.log_metric(mlflow_run_id, key, value)
        for key, value in artifact_hashes.items():
            self.client.set_tag(mlflow_run_id, f"artifact.sha256.{key}", value)
        if failure_reason is not None:
            self.client.set_tag(mlflow_run_id, "failure.reason", failure_reason[:500])
        status = RunStatus.to_string(RunStatus.FINISHED if succeeded else RunStatus.FAILED)
        self.client.set_terminated(mlflow_run_id, status=status)
