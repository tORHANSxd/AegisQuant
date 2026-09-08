"""Evidence integrity, non-training replay, and missing-data boundaries for Phase A."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import polars as pl
import pytest
import yaml

from aegisquant.bootstrap.live_lock import (
    LIVE_ADAPTERS,
    LIVE_TRADING,
    ORDER_SUBMISSION_ENABLED,
)
from scripts import audit_current_failure as audit


def write_export(path: Path, *, backwards: bool = False) -> None:
    columns = (
        "symbol",
        "sample_id",
        "decision_time_utc",
        "label_start_time_utc",
        "label_end_time_utc",
        "fold_id",
        "selected_candidate",
        "threshold",
        "positive_probability",
        "position",
        "realized_return",
        "gross_return",
        "cost_return",
        "net_return",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for hour, position, probability, realized, cost in (
                (0, 1.0, 0.6, 0.01, 0.0013),
                (1, 0.0, 0.5, -0.01, 0.0013),
            ):
                writer.writerow(
                    (
                        symbol,
                        f"{symbol}:{hour}",
                        f"2024-01-01T0{hour}:59:59.999Z",
                        f"2024-01-01T0{hour if backwards else hour + 1}:00:00Z",
                        f"2024-01-01T0{hour + 2}:00:00Z",
                        "fold:1",
                        "logistic_core",
                        0.5,
                        probability,
                        position,
                        realized,
                        position * realized,
                        cost,
                        position * realized - cost,
                    )
                )


def test_freeze_preserves_probabilities_and_separates_symbols(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    write_export(path)
    frame = audit.frozen_frame(path)
    assert frame.height == 4
    assert frame["prediction_raw"].to_list() == [0.6, 0.5, 0.6, 0.5]
    assert frame["prediction_direction"].to_list() == ["UP", "DOWN", "UP", "DOWN"]
    assert frame["current_position"].to_list() == [0.0, 1.0, 0.0, 1.0]
    assert frame["target_position"].to_list() == [1.0, 0.0, 1.0, 0.0]
    assert frame["order_quantity"].null_count() == 4
    assert frame["prediction_scope"].unique().to_list() == ["SELECTED_POLICY_ONLY"]


def test_freeze_rejects_nonexecutable_time(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    write_export(path, backwards=True)
    with pytest.raises(ValueError, match="strictly executable"):
        audit.frozen_frame(path)


def test_freeze_rejects_duplicate_sample_ids(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    write_export(path)
    frame = pl.read_csv(path)
    pl.concat([frame, frame.head(1)]).write_csv(path)
    with pytest.raises(ValueError, match="duplicate"):
        audit.frozen_frame(path)


def test_a0_replay_uses_original_signal_with_round_trip_costs(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    write_export(path)
    replay = audit.replay_selected(path)
    assert replay["model_retrained"] is False
    assert replay["performance"]["net_compound_return"] == pytest.approx(
        (1 + 0.01 - 0.0013) * (1 - 0.0013) - 1
    )
    assert replay["classification"]["direction_accuracy"] == 1.0


def test_a0_replay_rejects_changed_original_returns(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    write_export(path)
    frame = pl.read_csv(path).with_columns(pl.lit(0.1).alias("net_return"))
    frame.write_csv(path)
    with pytest.raises(ValueError, match="net_return cannot be reproduced"):
        audit.replay_selected(path)


def test_snapshot_cannot_be_silently_overwritten(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_source_read(*_args: object) -> None:
        raise AssertionError("existing snapshot must not rerun or read original data")

    monkeypatch.setattr(audit, "verify_evidence", forbid_source_read)
    manifest = audit.freeze(project_root, "different-current-commit")
    assert manifest["git_commit_sha"] == "558f5350247c29749d5bf3b8c92ab1e52a572361"
    assert manifest["frozen_prediction_rows"] == 60_480
    assert manifest["failed_candidate_predictions_frozen"] is False
    assert manifest["phase_a_status"] == "BLOCKED_MISSING_FAILED_PREDICTIONS"


def test_snapshot_integrity_rejects_tampering(project_root: Path, tmp_path: Path) -> None:
    directory = tmp_path / audit.OUTPUT
    shutil.copytree(project_root / audit.OUTPUT, directory)
    path = directory / "metric_lineage.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        audit.verify_frozen(tmp_path)


def test_metric_lineage_does_not_conflate_selected_and_failed_policy(project_root: Path) -> None:
    manifest = audit.verify_frozen(project_root)
    lineage = audit.read_json(project_root / audit.OUTPUT / "metric_lineage.json")
    assert lineage["metrics_are_from_different_policies"] is True
    assert lineage["direction_accuracy"]["value"] == pytest.approx(0.5008101851851852)
    assert manifest["compounded_return"] == pytest.approx(0.20637901344051524)
    assert lineage["loss_below_40_percent"]["value"] < -0.38
    assert lineage["loss_below_40_percent"]["original_per_sample_predictions_available"] is False


def test_v4_ssot_identity_and_safety_remain_explicit(project_root: Path) -> None:
    state = yaml.safe_load(
        (project_root / "state/ALPHA_V4_PROJECT_STATE.yaml").read_text(encoding="utf-8")
    )
    assert state["spec"] == audit.SPEC
    assert state["spec_sha256"] == audit.sha256(project_root / audit.SPEC)
    assert state["spec_lines"] == len(
        (project_root / audit.SPEC).read_text(encoding="utf-8").splitlines()
    )
    assert state["current_phase"] in {"A", "B", "C", "D", "E", "F", "G", "COMPLETE"}
    assert state["branch"] == "main" and state["branch_creation_allowed"] is False
    assert state["alpha_promotion_eligible"] is False
    assert state["model_retraining_scope"] == "original_baseline_reconstruction_only"
    assert state["final_holdout_access_count"] == 0
    assert LIVE_TRADING is False and ORDER_SUBMISSION_ENABLED is False and LIVE_ADAPTERS == ()
    assert audit.SPEC in (project_root / "CODEX_BOOTSTRAP.md").read_text(encoding="utf-8")
