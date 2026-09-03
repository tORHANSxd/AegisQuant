"""Fair OOS event modality ablation and permutation tests."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.data.hashing import canonical_sha256
from aegisquant.research.forecasting import (
    CouncilHorizon,
    EventAblationArm,
    EventAblationEvaluation,
    EventForecastAblationReport,
    FoldEvaluationState,
    create_event_ablation_evaluation,
    evaluate_event_forecast_ablation,
)
from tests.v5_p05.test_canonical_events import AS_OF
from tests.v5_p08.helpers import (
    DEFAULT_ABLATION_LOSSES,
    ablation_evaluations,
    ablation_spec,
    comparison_lineage,
    digest,
    event_condition,
    metrics,
)


def test_ablation_reports_all_four_modes_and_all_placebos_by_horizon() -> None:
    report = evaluate_event_forecast_ablation(
        spec=ablation_spec(),
        event_condition=event_condition(),
        evaluations=ablation_evaluations(),
    )
    result = report.results[0]

    assert set(result.mean_primary_loss_by_arm) == set(EventAblationArm)
    assert EventAblationArm.EVENT_ONLY in result.mean_net_return_after_cost_by_arm
    assert EventAblationArm.RISK_ONLY in result.mean_net_return_after_cost_by_arm
    assert result.market_event_beats_market_only is True
    assert result.truth_permutation_degrades is False
    assert result.event_permutation_degrades is True
    assert result.text_permutation_degrades is True
    assert result.timestamp_placebo_degrades is True
    assert result.asset_placebo_degrades is True
    assert result.event_increment_gate_passed_in_fixture is False
    assert "TRUTH_PERMUTATION_NOT_DEGRADED" in result.reason_codes
    assert report.fixture_supported_horizons == ()
    assert report.real_world_event_increment_claimed is False


def test_ablation_fixture_gate_requires_every_permutation_to_degrade() -> None:
    losses = dict(DEFAULT_ABLATION_LOSSES)
    losses[EventAblationArm.TRUTH_PERMUTED] = Decimal("0.25")
    report = evaluate_event_forecast_ablation(
        spec=ablation_spec(),
        event_condition=event_condition(),
        evaluations=ablation_evaluations(losses=losses),
    )

    assert report.results[0].event_increment_gate_passed_in_fixture is True
    assert report.fixture_supported_horizons == (CouncilHorizon.THIRTY_MINUTES,)
    assert report.alpha_promotion_eligible is False
    assert report.multiple_testing_passed is False


@pytest.mark.parametrize(
    "arm",
    [
        EventAblationArm.EVENT_PERMUTED,
        EventAblationArm.TEXT_PERMUTED,
        EventAblationArm.TIMESTAMP_PLACEBO,
        EventAblationArm.ASSET_PLACEBO,
    ],
)
def test_each_event_or_mapping_placebo_can_independently_fail(arm: EventAblationArm) -> None:
    losses = dict(DEFAULT_ABLATION_LOSSES)
    losses[EventAblationArm.TRUTH_PERMUTED] = Decimal("0.25")
    losses[arm] = Decimal("0.205")
    report = evaluate_event_forecast_ablation(
        spec=ablation_spec(),
        event_condition=event_condition(),
        evaluations=ablation_evaluations(losses=losses),
    )

    assert report.results[0].event_increment_gate_passed_in_fixture is False


def test_ablation_rejects_unequal_oos_folds() -> None:
    evaluations = tuple(
        item
        for item in ablation_evaluations()
        if not (item.arm is EventAblationArm.EVENT_ONLY and item.lineage.fold_id == "fold-2")
    )
    with pytest.raises(ValueError, match="UNEQUAL-OOS-FOLDS"):
        evaluate_event_forecast_ablation(
            spec=ablation_spec(),
            event_condition=event_condition(),
            evaluations=evaluations,
        )


def test_ablation_rejects_same_fold_with_different_split_or_samples() -> None:
    evaluations = list(ablation_evaluations())
    target = next(
        item
        for item in evaluations
        if item.arm is EventAblationArm.EVENT_ONLY and item.lineage.fold_id == "fold-1"
    )
    replacement = create_event_ablation_evaluation(
        arm=target.arm,
        lineage=comparison_lineage(fold_number=1, split_label="spliced-split"),
        event_condition_snapshot_sha256=target.event_condition_snapshot_sha256,
        permutation_plan_sha256=None,
        prediction_artifact_sha256=target.prediction_artifact_sha256,
        state=target.state,
        metrics=target.metrics,
        abstain_or_failure_reason=None,
    )
    evaluations[evaluations.index(target)] = replacement

    with pytest.raises(ValueError, match="LINEAGE-SPLICE"):
        evaluate_event_forecast_ablation(
            spec=ablation_spec(),
            event_condition=event_condition(),
            evaluations=tuple(evaluations),
        )


def test_ablation_rejects_prediction_artifact_reuse() -> None:
    evaluations = list(ablation_evaluations())
    first, second = evaluations[:2]
    evaluations[1] = create_event_ablation_evaluation(
        arm=second.arm,
        lineage=second.lineage,
        event_condition_snapshot_sha256=second.event_condition_snapshot_sha256,
        permutation_plan_sha256=second.permutation_plan_sha256,
        prediction_artifact_sha256=first.prediction_artifact_sha256,
        state=second.state,
        metrics=second.metrics,
        abstain_or_failure_reason=second.abstain_or_failure_reason,
    )
    with pytest.raises(ValueError, match="PREDICTION-REUSE"):
        evaluate_event_forecast_ablation(
            spec=ablation_spec(),
            event_condition=event_condition(),
            evaluations=tuple(evaluations),
        )


def test_ablation_rejects_future_evaluation() -> None:
    spec = ablation_spec().model_copy(update={"evaluation_cutoff": AS_OF + timedelta(hours=1)})
    with pytest.raises(ValueError, match="FUTURE-EVALUATION"):
        evaluate_event_forecast_ablation(
            spec=spec,
            event_condition=event_condition(),
            evaluations=ablation_evaluations(),
        )


def test_permuted_arm_requires_a_precommitted_plan() -> None:
    with pytest.raises(ValidationError, match="PERMUTATION-PLAN-MISMATCH"):
        create_event_ablation_evaluation(
            arm=EventAblationArm.TRUTH_PERMUTED,
            lineage=comparison_lineage(),
            event_condition_snapshot_sha256=event_condition().snapshot_sha256,
            permutation_plan_sha256=None,
            prediction_artifact_sha256=digest("prediction"),
            state=FoldEvaluationState.EVALUATED,
            metrics=metrics(Decimal("0.3")),
            abstain_or_failure_reason=None,
        )


def test_failed_arm_is_preserved_and_fails_closed() -> None:
    report = evaluate_event_forecast_ablation(
        spec=ablation_spec(),
        event_condition=event_condition(),
        evaluations=ablation_evaluations(failed_arm=EventAblationArm.EVENT_PERMUTED),
    )
    result = report.results[0]

    assert result.failed_arms == (EventAblationArm.EVENT_PERMUTED,)
    assert result.event_increment_gate_passed_in_fixture is False
    assert "ABLATION_ARM_FAILURE" in result.reason_codes


def test_report_rejects_rehashed_forged_gate_result() -> None:
    report = evaluate_event_forecast_ablation(
        spec=ablation_spec(),
        event_condition=event_condition(),
        evaluations=ablation_evaluations(),
    )
    payload = report.model_dump(mode="json")
    payload["results"][0]["truth_permutation_degrades"] = True
    payload["results"][0]["event_increment_gate_passed_in_fixture"] = True
    payload["results"][0]["reason_codes"] = ["EVENT_INCREMENT_FIXTURE_GATE_PASSED"]
    payload["report_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "report_sha256"}
    )

    with pytest.raises(ValidationError, match="REPORT-RECOMPUTATION-MISMATCH"):
        EventForecastAblationReport.model_validate_json(json.dumps(payload))


def test_ablation_evaluation_hash_rejects_mutation() -> None:
    evaluation = ablation_evaluations()[0]
    payload = evaluation.model_dump(mode="json")
    payload["prediction_artifact_sha256"] = digest("other-prediction")

    with pytest.raises(ValidationError, match="EVALUATION-HASH-MISMATCH"):
        EventAblationEvaluation.model_validate_json(json.dumps(payload))
