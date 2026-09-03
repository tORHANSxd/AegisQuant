"""PIT event conditioning and counterfactual forecast tests."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.intelligence import EventClusterStatus
from aegisquant.research.forecasting import (
    CouncilHorizon,
    EventConditionSnapshot,
    EventIncrement,
    compute_event_increment,
    create_event_condition_snapshot,
)
from tests.v5_p05.test_canonical_events import AS_OF, canonical
from tests.v5_p08.helpers import (
    digest,
    event_condition,
    forecast_pair,
    market_tensor,
)


def test_event_condition_snapshot_binds_truth_event_and_directional_gate() -> None:
    event = canonical()
    snapshot = event_condition()

    assert snapshot.canonical_event == event
    assert (
        snapshot.features.truth_probability_at_t == event.truth_assessment.claim_truth_probability
    )
    assert snapshot.features.independent_evidence_count == 2
    assert snapshot.features.evidence_dependency_score == Decimal("0.05")
    assert snapshot.features.novelty_at_t == Decimal("0.8")
    assert snapshot.features.surprise_at_t == Decimal("0.5")
    assert snapshot.features.market_reflection_at_t == Decimal("0.40")
    assert snapshot.directional_candidate_allowed is True
    assert snapshot.risk_overlay_only is False
    assert snapshot.fixed_horizon_scale_used is False


def test_event_condition_snapshot_rejects_future_event_revision() -> None:
    with pytest.raises(ValueError, match="LOOKAHEAD"):
        create_event_condition_snapshot(
            canonical_event=canonical(),
            instrument_id=event_condition().instrument_id,
            asset_id=event_condition().asset_id,
            decision_time=AS_OF - timedelta(seconds=1),
            asset_relationship_score=Decimal("0.9"),
            relationship_snapshot_sha256=digest("relationship"),
        )


def test_event_condition_snapshot_rejects_self_consistent_truth_feature_splice() -> None:
    payload = event_condition().model_dump(mode="json")
    payload["features"]["truth_probability_at_t"] = "0.10"
    payload["snapshot_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "snapshot_sha256"}
    )

    with pytest.raises(ValidationError, match="FEATURE-BINDING-MISMATCH"):
        EventConditionSnapshot.model_validate_json(json.dumps(payload))


def test_event_condition_snapshot_requires_real_asset_relationship() -> None:
    with pytest.raises(ValidationError, match="positive asset relationship"):
        create_event_condition_snapshot(
            canonical_event=canonical(),
            instrument_id=event_condition().instrument_id,
            asset_id=event_condition().asset_id,
            decision_time=AS_OF,
            asset_relationship_score=Decimal("0"),
            relationship_snapshot_sha256=digest("relationship"),
        )


def test_market_and_event_forecasts_share_exact_oos_inputs() -> None:
    market_only, event_conditioned = forecast_pair()

    assert market_only.lineage == event_conditioned.lineage
    assert market_only.inputs.market_state_tensor == event_conditioned.inputs.market_state_tensor
    assert market_only.inputs.calibrations == event_conditioned.inputs.calibrations
    assert market_only.inputs.capability == event_conditioned.inputs.capability
    assert market_only.event_features_used is False
    assert event_conditioned.event_features_used is True


def test_event_forecast_rejects_missing_market_or_derivatives_feature() -> None:
    with pytest.raises(ValidationError, match="MARKET-FEATURES-MISSING:funding"):
        forecast_pair(tensor=market_tensor(omit_feature="funding"))


def test_rumor_is_risk_overlay_only_and_directional_forecast_must_abstain() -> None:
    rumor = event_condition(status=EventClusterStatus.RUMOR)
    with pytest.raises(ValidationError, match="DIRECTIONAL-DENIAL-MUST-ABSTAIN"):
        forecast_pair(condition=rumor)

    _, accepted = forecast_pair(condition=rumor, event_should_abstain=True)
    assert accepted.event_condition.directional_candidate_allowed is False
    assert accepted.event_condition.risk_overlay_only is True
    assert accepted.inputs.forecast.should_abstain is True
    assert accepted.order_submission_enabled is False


def test_event_increment_is_recomputed_for_each_forecast_target() -> None:
    market_only, event_conditioned = forecast_pair()
    increment = compute_event_increment(
        market_only=market_only,
        event_conditioned=event_conditioned,
    )

    assert increment.by_horizon.horizon is CouncilHorizon.THIRTY_MINUTES
    assert increment.by_horizon.delta_expected_return == Decimal("0.005")
    assert increment.by_horizon.delta_return_quantiles.q50 == Decimal("0.005")
    assert increment.by_horizon.delta_up_probability == Decimal("0.05")
    assert increment.by_horizon.delta_realized_volatility == Decimal("0.02")
    assert increment.by_horizon.delta_tail_risk_probability == Decimal("0.03")
    assert increment.by_horizon.delta_liquidity == Decimal("-10")
    assert increment.by_horizon.delta_spread == Decimal("1")
    assert increment.by_horizon.delta_slippage == Decimal("1")
    assert increment.by_horizon.delta_abstain_probability == Decimal("0.02")
    assert increment.real_world_increment_claimed is False


def test_event_increment_rejects_lineage_and_input_splices() -> None:
    market_only, _ = forecast_pair()
    _, spliced = forecast_pair(fold_number=2)
    with pytest.raises(ValueError, match="LINEAGE-MISMATCH"):
        compute_event_increment(market_only=market_only, event_conditioned=spliced)


def test_event_increment_rejects_rehashed_forged_delta() -> None:
    market_only, event_conditioned = forecast_pair()
    increment = compute_event_increment(
        market_only=market_only,
        event_conditioned=event_conditioned,
    )
    payload = increment.model_dump(mode="json")
    payload["by_horizon"]["delta_expected_return"] = "0.50"
    payload["increment_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "increment_sha256"}
    )

    with pytest.raises(ValidationError, match="RECOMPUTATION-MISMATCH"):
        EventIncrement.model_validate_json(json.dumps(payload))


def test_event_forecast_artifacts_are_content_addressed() -> None:
    market_only, event_conditioned = forecast_pair(horizon=CouncilHorizon.FOUR_HOURS)
    forged = market_only.model_dump(mode="json")
    forged["lineage"]["resource_budget_sha256"] = digest("forged-budget")

    with pytest.raises(ValidationError, match="COMPARISON-HASH-MISMATCH"):
        type(market_only).model_validate_json(json.dumps(forged))
    assert market_only.artifact_sha256 != event_conditioned.artifact_sha256


def test_production_source_has_no_fixed_horizon_scale_table() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "aegisquant"
    offenders = tuple(
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.py")
        if "HORIZON_SCALE =" in path.read_text(encoding="utf-8")
    )
    assert offenders == ()
