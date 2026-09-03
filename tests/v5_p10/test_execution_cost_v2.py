"""ExecutionCostModelV2 completeness, queue, calibration, and lineage tests."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.data.hashing import canonical_sha256
from aegisquant.decision import (
    CostCalibrationState,
    ExecutionCostComponent,
    ExecutionCostDistribution,
    ExecutionCostModelV2,
    MakerQueueMode,
    ReplayQueueInputs,
    create_execution_cost_model_v2,
)
from tests.v5_p10.helpers import cost_distribution, cost_model, digest


def test_cost_model_covers_every_required_component_and_environment() -> None:
    model = cost_model()
    assert model.components == tuple(ExecutionCostComponent)
    assert model.environments == ("BACKTEST", "PAPER", "LIVE")
    assert model.real_world_tca_claimed is False


def test_cost_scenario_total_and_distribution_mean_are_recomputed() -> None:
    distribution = cost_distribution()
    assert distribution.expected_cost == Decimal("0.002000")
    payload = distribution.model_dump(mode="json")
    payload["expected_cost"] = "0.000001"
    payload["distribution_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "distribution_sha256"}
    )
    with pytest.raises(ValidationError, match="EXPECTED-COST-RECOMPUTATION"):
        ExecutionCostDistribution.model_validate_json(json.dumps(payload))


def test_missing_cost_component_cannot_hide_behind_recomputed_hash() -> None:
    model = cost_model()
    payload = model.model_dump(mode="json")
    payload["components"] = payload["components"][:-1]
    payload["model_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "model_sha256"}
    )
    with pytest.raises(ValidationError, match="COST-COMPONENT-SET-MISMATCH"):
        ExecutionCostModelV2.model_validate_json(json.dumps(payload))


def test_replay_queue_requires_all_six_content_bindings() -> None:
    with pytest.raises(ValidationError, match="REPLAY-QUEUE-INPUT-BINDING"):
        create_execution_cost_model_v2(
            version="replay-without-inputs",
            queue_mode=MakerQueueMode.REPLAY_QUEUE,
            replay_inputs=None,
            calibration_state=CostCalibrationState.UNVERIFIED,
            tca_artifact_sha256=None,
            tca_sample_count=0,
            cost_confidence=Decimal("0.70"),
        )

    replay = ReplayQueueInputs(
        l2_snapshots_sha256=digest("l2-snapshots"),
        l2_deltas_sha256=digest("l2-deltas"),
        trades_sha256=digest("trades"),
        order_arrival_sha256=digest("arrival"),
        cancel_replace_sha256=digest("cancel-replace"),
        queue_ahead_sha256=digest("queue-ahead"),
    )
    model = create_execution_cost_model_v2(
        version="replay-bound",
        queue_mode=MakerQueueMode.REPLAY_QUEUE,
        replay_inputs=replay,
        calibration_state=CostCalibrationState.UNVERIFIED,
        tca_artifact_sha256=None,
        tca_sample_count=0,
        cost_confidence=Decimal("0.70"),
    )
    assert model.replay_inputs == replay


def test_tca_state_requires_evidence_and_miscalibration_reduces_confidence() -> None:
    with pytest.raises(ValidationError, match="CALIBRATION-EVIDENCE-MISSING"):
        create_execution_cost_model_v2(
            version="fake-calibrated",
            queue_mode=MakerQueueMode.CONSERVATIVE_QUEUE,
            replay_inputs=None,
            calibration_state=CostCalibrationState.WITHIN_TOLERANCE,
            tca_artifact_sha256=None,
            tca_sample_count=0,
            cost_confidence=Decimal("1"),
        )
    with pytest.raises(ValidationError, match="MUST-REDUCE-CONFIDENCE"):
        create_execution_cost_model_v2(
            version="miscalibrated-no-haircut",
            queue_mode=MakerQueueMode.CONSERVATIVE_QUEUE,
            replay_inputs=None,
            calibration_state=CostCalibrationState.MISCALIBRATED,
            tca_artifact_sha256=digest("miscalibrated-tca"),
            tca_sample_count=10,
            cost_confidence=Decimal("1"),
        )


def test_scenario_collections_have_a_bounded_validation_surface() -> None:
    schema = ExecutionCostDistribution.model_json_schema()
    scenario_schema = schema["properties"]["scenarios"]
    assert scenario_schema["minItems"] == 3
    assert scenario_schema["maxItems"] == 4096
