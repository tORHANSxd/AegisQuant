"""R2 behavioral proofs; synthetic component checks are not return-model research."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import numpy as np
import pytest

from aegisquant.portfolio.economic_gate import (
    EconomicAction,
    EconomicGatePolicy,
    decide_economic_transition,
)
from aegisquant.portfolio.transition_costs import estimate_spot_transition_costs
from aegisquant.research.models.economic_filter import fit_economic_filter
from aegisquant.research.models.economic_gate import (
    CalibrationStatus,
    EconomicForecast,
    PointForecastStatus,
)
from aegisquant.research.strategies.cost_aware_trend import fit_training_scaler
from aegisquant.research.validation.cat_contract import CatAuditPolicy, audit_arms
from aegisquant.research.validation.cat_replay import replay_cat
from tests.integration.cat_helpers import ROOT, fixture
from tests.p06.helpers import NOW
from tests.unit.portfolio.test_dynamic_economic_gate import forecast
from tests.unit.research.test_calibration_train_validation_only import dataset


def component_forecast(*, probability: bool = True) -> EconomicForecast:
    return EconomicForecast.model_validate(
        {
            **forecast().model_dump(mode="python"),
            "trained_through": NOW - timedelta(days=100),
            "point_forecast_status": PointForecastStatus.AVAILABLE,
            "residual_calibration_status": CalibrationStatus.VALIDATION_CALIBRATED,
            "probability_calibration_status": CalibrationStatus.VALIDATION_CALIBRATED
            if probability
            else CalibrationStatus.UNAVAILABLE,
            "residual_calibrated_through": NOW - timedelta(days=60),
            "probability_calibrated_through": NOW - timedelta(days=60) if probability else None,
            "component_evidence_sha256": "b" * 64,
            "calibration_status": CalibrationStatus.VALIDATION_CALIBRATED
            if probability
            else CalibrationStatus.UNAVAILABLE,
        }
    )


def run_gate(
    arm: str,
    value: EconomicForecast | None,
    *,
    age: Decimal | None = None,
    weight: Decimal = Decimal("0"),
    market: bool = True,
):
    return decide_economic_transition(
        policy=EconomicGatePolicy(),
        forecast=value,
        costs=estimate_spot_transition_costs(
            available_time=NOW,
            natr=Decimal("0.01"),
            quote_volume=Decimal("1000000"),
            order_notional=Decimal("10000"),
            exit_latency_adverse_bps=Decimal("1"),
        ),
        decision_time=NOW,
        current_weight=weight,
        trend_candidate=True,
        trend_exit_confirmed=False,
        data_quality_passed=market,
        risk_allows_entry=True,
        annualized_volatility=Decimal("0.8"),
        audit_policy=audit_arms()[arm].model_copy(
            update={"version": "cat-audit-r2", "maximum_calibration_age_days": age}
        ),
    )


def test_mean_filter_does_not_require_disabled_probability_calibration() -> None:
    value = component_forecast(probability=False)
    assert run_gate("A3", value).action is EconomicAction.ENTER_LONG
    assert run_gate("A5", value).reason == "PROBABILITY_CALIBRATION_UNAVAILABLE"
    assert run_gate("A3", None).reason == "MODEL_MISSING"
    assert run_gate("A3", value, age=Decimal("30")).reason == "CALIBRATION_EXPIRED"
    assert run_gate("A3", None, weight=Decimal("0.2")).action is EconomicAction.HOLD_CURRENT
    assert (
        run_gate("A3", value, weight=Decimal("0.2"), market=False).action
        is EconomicAction.EXIT_LONG
    )
    assert run_gate("A3", value, weight=Decimal("0.2"), market=False).reason == "RISK_OR_DATA_VETO"


def test_distribution_risk_is_not_mean_estimation_uncertainty() -> None:
    value = EconomicForecast.model_validate(
        {
            **component_forecast().model_dump(mode="python"),
            "expected_gross_return": Decimal("0.01"),
            "q10_return": Decimal("-0.01"),
            "q50_return": Decimal("-0.01"),
            "q90_return": Decimal("0.04"),
            "p_net_positive": Decimal("0.4"),
        }
    )
    assert run_gate("A3", value).action is EconomicAction.ENTER_LONG
    assert run_gate("A5", value).reason == "PROBABILITY_ENTRY_REJECTED"
    penalized = run_gate("A6", value)
    assert penalized.q_long == Decimal("-0.0225")
    assert penalized.distribution_penalty == Decimal("0.0125")
    assert penalized.decision_value_kind == "MEDIAN_MINUS_PREDICTIVE_WIDTH"
    assert penalized.mean_estimation_uncertainty is None


def test_one_class_calibration_keeps_corrected_point_and_residual_components() -> None:
    train, validation, inference = dataset(0, 40), dataset(46, 40), dataset(94, 8)
    validation = validation.model_copy(update={"targets": (0.02,) * 40})
    result = fit_economic_filter(
        family="CONSTANT",
        train=train,
        validation=validation,
        test=inference,
        train_label_end_times=tuple(t + timedelta(hours=24) for t in train.timestamps),
        validation_label_end_times=tuple(t + timedelta(hours=24) for t in validation.timestamps),
        validation_round_trip_costs=(Decimal("0.002"),) * 40,
    )
    value = result.forecasts[0]
    assert value.expected_gross_return == Decimal("0.02")
    assert value.calibration_status is CalibrationStatus.UNAVAILABLE
    assert value.residual_calibration_status is CalibrationStatus.VALIDATION_CALIBRATED
    assert (
        value.component_failure(probability_required=False, decision_time=value.available_time)
        is None
    )
    assert (
        value.component_failure(probability_required=True, decision_time=value.available_time)
        == "PROBABILITY_CALIBRATION_UNAVAILABLE"
    )


def test_binary_safe_scaling_preserves_training_standardization_and_linear_prediction() -> None:
    # Optional new preprocessing; frozen real predictions are never recomputed here.
    from sklearn.linear_model import ElasticNet  # pyright: ignore[reportMissingTypeStubs]
    from sklearn.preprocessing import StandardScaler  # pyright: ignore[reportMissingTypeStubs]

    _, _, features = fixture()
    selected = np.arange(240, 320, dtype=np.int64)
    legacy = fit_training_scaler(features, selected, validation_start=features.available_times[321])
    safe = fit_training_scaler(
        features,
        selected,
        validation_start=features.available_times[321],
        contract_version="mad-binary-safe-r2",
    )
    assert safe.scale[-1] == 1 and safe.binary_indices == (16,)
    original = legacy.transform(features.values)[selected]
    changed = safe.transform(features.values)[selected]
    old_input = np.asarray(cast(Any, StandardScaler()).fit_transform(original), dtype=np.float64)
    new_input = np.asarray(cast(Any, StandardScaler()).fit_transform(changed), dtype=np.float64)
    np.testing.assert_allclose(old_input, new_input, rtol=1e-10, atol=1e-10)
    truth = np.sin(np.arange(len(selected))) * 0.01
    a = np.asarray(
        cast(Any, ElasticNet(alpha=0.001, l1_ratio=0.5)).fit(old_input, truth).predict(old_input),
        dtype=np.float64,
    )
    b = np.asarray(
        cast(Any, ElasticNet(alpha=0.001, l1_ratio=0.5)).fit(new_input, truth).predict(new_input),
        dtype=np.float64,
    )
    np.testing.assert_allclose(a, b, rtol=1e-10, atol=1e-10)
    poisoned = features.values.copy()
    poisoned[321:] = 1e30
    future = replace(features, values=poisoned)
    assert safe == fit_training_scaler(
        future,
        selected,
        validation_start=features.available_times[321],
        contract_version="mad-binary-safe-r2",
    )


def test_r2_estimates_planned_increment_without_using_future_fill() -> None:
    spec, bars, features = fixture()
    result, trace = replay_cat(
        root=ROOT,
        spec=spec,
        bars=bars,
        features=features,
        feature_indices={t: i for i, t in enumerate(features.available_times)},
        trend_by_time={b.available_time: True for b in bars},
        forecasts={},
        level="A1",
        audit_policy=CatAuditPolicy(version="cat-audit-r2"),
    )
    planned = [r for r in trace if r.get("order_id")]
    assert planned and all(r["estimate_uses_future_fill"] is False for r in planned)
    assert all(r["cost_estimate_available_time"] == r["decision_time"] for r in planned)
    assert all(Decimal(r["planned_increment_cost_usdt"]) >= 0 for r in planned)
    assert abs(result.cost_identity_residual) < result.cost_identity_tolerance
    assert result.positions[-1].quantity == 0


def test_component_boundary_cannot_be_forged_as_available() -> None:
    with pytest.raises(ValueError, match="component calibration must precede"):
        EconomicForecast.model_validate(
            {**component_forecast().model_dump(mode="python"), "residual_calibrated_through": NOW}
        )
