"""PIT tensor, calibration, full forecast output, and lineage attack tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.identifiers import ArtifactId
from aegisquant.research.forecasting import (
    CouncilHorizon,
    DirectionProbabilitiesV2,
    ForecastEnvelope,
    ForecastQuantiles,
    HorizonForecast,
    bind_forecast_inputs,
    create_calibration_artifact,
    create_market_state_tensor,
    validate_market_state_tensor,
)
from tests.v5_p07.helpers import (
    calibration,
    capability,
    digest,
    forecast_envelope,
    horizon_forecast,
    instant,
    market_tensor,
)


def test_market_state_tensor_is_pit_rectangular_and_content_addressed() -> None:
    tensor = market_tensor()
    assert tensor.observed_at[-1] < tensor.decision_time
    assert all(value <= tensor.decision_time for value in tensor.available_at)
    assert len(tensor.tensor_sha256) == 64
    assert tensor.source_dataset_ids == tuple(sorted(tensor.source_dataset_ids))


def test_market_state_tensor_rejects_future_availability() -> None:
    tensor = market_tensor()
    with pytest.raises(ValidationError, match="MARKET-TENSOR-LOOKAHEAD"):
        create_market_state_tensor(
            tensor_id=tensor.tensor_id,
            instrument_id=tensor.instrument_id,
            asset_id=tensor.asset_id,
            window_start=tensor.window_start,
            decision_time=tensor.decision_time,
            observed_at=tensor.observed_at,
            available_at=(*tensor.available_at[:-1], tensor.decision_time + timedelta(seconds=1)),
            feature_names=tensor.feature_names,
            values=tensor.values,
            source_dataset_ids=tensor.source_dataset_ids,
            dataset_manifest_sha256=tensor.dataset_manifest_sha256,
            feature_snapshot_sha256=tensor.feature_snapshot_sha256,
        )


def test_market_state_tensor_rejects_an_entirely_missing_feature() -> None:
    tensor = market_tensor()
    values = tuple((row[0], None, row[2]) for row in tensor.values)
    with pytest.raises(ValidationError, match="entirely missing"):
        create_market_state_tensor(
            tensor_id=tensor.tensor_id,
            instrument_id=tensor.instrument_id,
            asset_id=tensor.asset_id,
            window_start=tensor.window_start,
            decision_time=tensor.decision_time,
            observed_at=tensor.observed_at,
            available_at=tensor.available_at,
            feature_names=tensor.feature_names,
            values=values,
            source_dataset_ids=tensor.source_dataset_ids,
            dataset_manifest_sha256=tensor.dataset_manifest_sha256,
            feature_snapshot_sha256=tensor.feature_snapshot_sha256,
        )


def test_market_state_tensor_copy_attack_is_revalidated() -> None:
    tensor = market_tensor()
    forged = tensor.model_copy(update={"tensor_sha256": digest("forged")})
    with pytest.raises(ValidationError, match="HASH-MISMATCH"):
        validate_market_state_tensor(forged)


def test_calibration_artifact_separates_calibration_and_test_samples() -> None:
    artifact = calibration()
    assert not set(artifact.calibration_sample_ids) & set(artifact.forbidden_test_sample_ids)
    assert len(artifact.artifact_sha256) == 64


def test_calibration_artifact_rejects_test_leakage() -> None:
    with pytest.raises(ValidationError, match="CALIBRATION-TEST-LEAKAGE"):
        create_calibration_artifact(
            calibration_id=ArtifactId("calibration-overlap"),
            method=calibration().method,
            asset_id=calibration().asset_id,
            horizon=CouncilHorizon.THIRTY_MINUTES,
            regime=calibration().regime,
            training_cutoff=instant(10),
            fitted_at=instant(11),
            available_at=instant(12),
            calibration_sample_ids=("sample-a", "sample-b"),
            forbidden_test_sample_ids=("sample-b",),
            split_sha256=digest("split-overlap"),
        )


def test_calibration_copy_attack_is_revalidated_at_forecast_boundary() -> None:
    tensor = market_tensor()
    artifact = calibration()
    forged = artifact.model_copy(update={"artifact_sha256": digest("forged-calibration")})
    forecast = forecast_envelope(tensor=tensor, artifact=artifact)
    with pytest.raises(ValidationError, match="CALIBRATION-HASH-MISMATCH"):
        bind_forecast_inputs(
            forecast=forecast,
            tensor=tensor,
            calibrations=(forged,),
            capability=capability("linear-baseline"),
        )


def test_full_horizon_forecast_contains_distribution_tail_cost_and_uncertainty() -> None:
    forecast = horizon_forecast()
    assert forecast.return_distribution.quantiles.q01 <= forecast.return_distribution.quantiles.q99
    assert (
        forecast.direction_probabilities.up
        + forecast.direction_probabilities.flat
        + forecast.direction_probabilities.down
        == Decimal("1")
    )
    assert forecast.maximum_adverse_excursion <= 0
    assert forecast.tail_risk_probability >= 0
    assert forecast.uncertainty.epistemic >= 0


def test_forecast_quantiles_and_direction_probabilities_fail_closed() -> None:
    values = horizon_forecast().return_distribution.quantiles.model_dump(mode="python")
    values["q01"] = Decimal("1")
    with pytest.raises(ValidationError, match="ordered"):
        ForecastQuantiles.model_validate(values)
    with pytest.raises(ValidationError, match="sum exactly"):
        DirectionProbabilitiesV2(up=Decimal("0.5"), flat=Decimal("0.3"), down=Decimal("0.3"))


def test_horizon_forecast_rejects_positive_mae_and_negative_volatility() -> None:
    base = horizon_forecast()
    with pytest.raises(ValidationError, match="non-positive"):
        HorizonForecast.model_validate(
            {**base.model_dump(mode="python"), "maximum_adverse_excursion": Decimal("0.01")}
        )
    volatility = base.realized_volatility_distribution.model_dump(mode="python")
    volatility_quantiles = base.realized_volatility_distribution.quantiles.model_dump(mode="python")
    volatility_quantiles["q01"] = Decimal("-0.01")
    volatility["quantiles"] = volatility_quantiles
    with pytest.raises(ValidationError, match="cannot be negative"):
        HorizonForecast.model_validate(
            {**base.model_dump(mode="python"), "realized_volatility_distribution": volatility}
        )


def test_forecast_binds_tensor_calibration_and_model_capability() -> None:
    tensor = market_tensor()
    artifact = calibration()
    candidate = capability("linear-baseline")
    forecast = forecast_envelope(tensor=tensor, artifact=artifact, candidate=candidate)
    bind_forecast_inputs(
        forecast=forecast,
        tensor=tensor,
        calibrations=(artifact,),
        capability=candidate,
    )


def test_forecast_rejects_tensor_capability_and_calibration_splicing() -> None:
    tensor = market_tensor()
    artifact = calibration()
    candidate = capability("linear-baseline")
    with pytest.raises(ValueError, match="TENSOR-BINDING-MISMATCH"):
        bind_forecast_inputs(
            forecast=forecast_envelope(
                tensor=tensor,
                artifact=artifact,
                candidate=candidate,
                market_state_tensor_sha256=digest("other-tensor"),
            ),
            tensor=tensor,
            calibrations=(artifact,),
            capability=candidate,
        )
    with pytest.raises(ValueError, match="CAPABILITY-BINDING-MISMATCH"):
        bind_forecast_inputs(
            forecast=forecast_envelope(
                tensor=tensor,
                artifact=artifact,
                candidate=candidate,
                model_capability_sha256=digest("other-capability"),
            ),
            tensor=tensor,
            calibrations=(artifact,),
            capability=candidate,
        )
    with pytest.raises(ValueError, match="CALIBRATION-BINDING-MISMATCH"):
        bind_forecast_inputs(
            forecast=forecast_envelope(
                tensor=tensor,
                artifact=artifact,
                candidate=candidate,
                calibration_artifact_sha256=digest("other-calibration"),
            ),
            tensor=tensor,
            calibrations=(artifact,),
            capability=candidate,
        )


def test_forecast_copy_attack_cannot_change_prediction_content_under_old_hash() -> None:
    forecast = forecast_envelope()
    changed_horizon = forecast.horizons[0].model_copy(
        update={"tail_risk_probability": Decimal("0.90")}
    )
    forged = forecast.model_copy(update={"horizons": (changed_horizon,)})
    with pytest.raises(ValidationError, match="ENVELOPE-HASH-MISMATCH"):
        ForecastEnvelope.model_validate_json(forged.model_dump_json())


def test_forecast_rejects_future_calibration_and_unsupported_horizon() -> None:
    tensor = market_tensor()
    candidate = capability("linear-baseline")
    future = calibration(available_at=tensor.decision_time + timedelta(seconds=1))
    forecast = forecast_envelope(tensor=tensor, artifact=future, candidate=candidate)
    with pytest.raises(ValueError, match="CALIBRATION-PIT-MISMATCH"):
        bind_forecast_inputs(
            forecast=forecast,
            tensor=tensor,
            calibrations=(future,),
            capability=candidate,
        )
    tcn = capability("tcn-candidate")
    short_artifact = calibration(horizon=CouncilHorizon.FIVE_SECONDS)
    unsupported = forecast_envelope(
        tensor=tensor,
        artifact=short_artifact,
        candidate=tcn,
        horizon=CouncilHorizon.FIVE_SECONDS,
    )
    with pytest.raises(ValueError, match="UNSUPPORTED-HORIZON"):
        bind_forecast_inputs(
            forecast=unsupported,
            tensor=tensor,
            calibrations=(short_artifact,),
            capability=tcn,
        )


def test_forecast_cannot_be_promoted_or_used_to_submit_orders() -> None:
    forecast = forecast_envelope()
    attacks = (
        {"alpha_promotion_eligible": True},
        {"order_submission_enabled": True},
        {"live_trading_locked": False},
    )
    for update in attacks:
        forged = forecast.model_copy(update=update)
        with pytest.raises(ValidationError):
            ForecastEnvelope.model_validate_json(forged.model_dump_json())


def test_forecast_abstain_reasons_are_sorted_unique_and_consistent() -> None:
    forecast = forecast_envelope()
    inconsistent = forecast.model_copy(update={"abstain_reasons": ("MISSING_DATA",)})
    with pytest.raises(ValidationError, match="flag and reasons"):
        ForecastEnvelope.model_validate_json(inconsistent.model_dump_json())
    duplicated = forecast.model_copy(
        update={
            "should_abstain": True,
            "abstain_reasons": ("OOD", "MISSING_DATA", "OOD"),
        }
    )
    with pytest.raises(ValidationError, match="sorted and unique"):
        ForecastEnvelope.model_validate_json(duplicated.model_dump_json())
