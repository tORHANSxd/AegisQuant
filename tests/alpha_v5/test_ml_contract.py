from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml

from aegisquant.data.hashing import canonical_sha256
from aegisquant.labels.episodes import BaseOpportunity, label_base_opportunities
from aegisquant.labels.models import CostAssumption, PricePathObservation
from aegisquant.research.models.baselines import BaselineDataset
from aegisquant.research.models.economic_filter import fit_economic_filter
from aegisquant.research.models.uncertainty import fit_split_conformal
from aegisquant.research.validation.calendar_walkforward import (
    CalendarIntervalFold,
    calendar_walkforward,
)
from aegisquant.research.validation.ml_contract import (
    FitProvenance,
    FoldRegistration,
    OOFPrediction,
    TransformFit,
    build_documents,
    nested_split_manifest,
    permit_ml_entry,
    planned_fit_ids,
    registered_synthetic_fit_check,
    validate_config,
    validate_oof_alignment,
)
from aegisquant.research.validation.splits import (
    SampleSpan,
    TemporalSplitPolicy,
    WalkForwardMode,
    purge_interval_partitions,
    walk_forward_splits,
)
from aegisquant.research.validation.statistics import (
    audited_deflated_sharpe_ratio,
    audited_probability_of_backtest_overfitting,
)

D = Decimal
NOW = datetime(2022, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def at(days: int) -> datetime:
    return NOW + timedelta(days=days)


def span(day: int, asset: str = "BTC", **updates: Any) -> SampleSpan:
    values: dict[str, Any] = {
        "sample_id": f"{asset}:{day}",
        "group_time": at(day),
        "label_start_time": at(day) + timedelta(minutes=1),
        "label_end_time": at(day) + timedelta(hours=1),
        "feature_dependency_start": at(day) - timedelta(hours=1),
        "label_available_time": at(day) + timedelta(hours=2),
        "episode_id": f"episode:{asset}:{day}",
    }
    return SampleSpan.model_validate({**values, **updates})


def fit_proof(**updates: Any) -> FitProvenance:
    values: dict[str, Any] = {
        "fold_id": "inner-1",
        "model_specification_sha256": HASH,
        "split_manifest_sha256": HASH,
        "training_payload_sha256": HASH,
        "label_contract_sha256": HASH,
        "training_spans": tuple(span(i) for i in range(4)),
        "transforms": (),
        "required_transform_names": (),
        "trained_at": at(4),
        "information_embargo_seconds": 3600,
    }
    return FitProvenance.model_validate({**values, **updates})


def register_proof(
    proof: FitProvenance, evaluated: tuple[SampleSpan, ...]
) -> tuple[FitProvenance, FoldRegistration]:
    registration = FoldRegistration(
        generation="synthetic-current",
        fold_id=proof.fold_id,
        outer_fold_id="outer-1",
        scope=proof.scope,
        training_spans=proof.training_spans,
        evaluation_spans=evaluated,
        label_contract={"version": "episode-v2", "base_policy_sha256": HASH},
        model_specification_sha256=proof.model_specification_sha256,
        transform_specification_hashes={
            item.name: item.specification_sha256 for item in proof.transforms
        },
        information_embargo_seconds=proof.information_embargo_seconds,
    )
    return FitProvenance.model_validate(
        {
            **dict(proof),
            "split_manifest_sha256": registration.manifest_sha256,
            "label_contract_sha256": registration.label_contract_sha256,
        }
    ), registration


def test_all_boundaries_long_spans_time_groups_and_episode_purge() -> None:
    raw = (
        (
            span(0),
            span(1, label_end_time=at(11), label_available_time=at(11)),
            span(1, "ETH"),
            span(2, episode_id="shared"),
        ),
        (span(10), span(11, label_available_time=at(21))),
        (span(20), span(21, label_end_time=at(31), label_available_time=at(31))),
        (span(30), span(31, episode_id="shared"), span(32, label_available_time=at(40))),
    )
    parts, removed = purge_interval_partitions(raw, ends=(at(10), at(20), at(30), at(40)))
    assert [[item.sample_id for item in part] for part in parts] == [
        ["BTC:0"],
        ["BTC:10"],
        ["BTC:20"],
        ["BTC:30", "BTC:31"],
    ]
    assert set(removed) == {"BTC:1", "ETH:1", "BTC:2", "BTC:11", "BTC:21", "BTC:32"}


def test_later_feature_lookback_purges_earlier_mature_label() -> None:
    kept, _ = purge_interval_partitions(
        ((span(0), span(4)), (span(10, feature_dependency_start=at(3)),)), ends=(at(10), at(20))
    )
    assert [item.sample_id for item in kept[0]] == ["BTC:0"]


def test_strict_metadata_required_and_legacy_payload_has_no_new_nulls() -> None:
    old = SampleSpan(
        sample_id="legacy", group_time=at(0), label_start_time=at(1), label_end_time=at(2)
    )
    assert "episode_id" not in old.model_dump(mode="json")
    with pytest.raises(ValueError, match="requires feature"):
        purge_interval_partitions(((old,),), ends=(at(5),))


def test_versioned_walkforward_purges_validation_calibration_and_full_group() -> None:
    rows = tuple(
        span(i, asset, **({"label_available_time": at(6)} if i == 4 and asset == "BTC" else {}))
        for i in range(10)
        for asset in ("BTC", "ETH")
    )
    policy = TemporalSplitPolicy(
        policy_id="strict",
        mode=WalkForwardMode.EXPANDING,
        train_groups=3,
        validation_groups=2,
        calibration_groups=2,
        test_groups=3,
        purge_groups=0,
        embargo_groups=0,
        step_groups=10,
        interval_policy="ALL_BOUNDARIES_INTERVAL_V2",
        labels_observed_through=at(11),
    )
    fold = walk_forward_splits(rows, policy)[0]
    assert fold.validation_ids == ("BTC:3", "ETH:3")
    assert {"BTC:4", "ETH:4"} <= set(fold.purged_ids)
    assert fold.interval_contract_sha256 is not None
    assert set(fold.test_ids) == {f"{asset}:{i}" for i in (7, 8, 9) for asset in ("BTC", "ETH")}


def test_calendar_strict_test_tail_is_mature_and_legacy_shape_stays() -> None:
    times = tuple(at(i) for i in range(90))
    rows = tuple(span(i) for i in range(90))
    kwargs: dict[str, Any] = {
        "available_times": times,
        "label_end_times": tuple(item.label_end_time for item in rows),
        "valid": (True,) * len(rows),
        "first_train_start": NOW,
        "development_end": datetime(2022, 4, 1, tzinfo=UTC),
        "train_months": 1,
        "validation_months": 1,
        "test_months": 1,
        "maximum_horizon_bars": 1,
        "purge_bars": 1,
        "embargo_bars": 1,
        "frequency_seconds": 3600,
    }
    legacy = calendar_walkforward(**kwargs)[0]
    assert "interval_contract_sha256" not in legacy.__dict__
    changed = (*rows[:-1], span(89, label_available_time=datetime(2022, 4, 2, tzinfo=UTC)))
    strict = calendar_walkforward(**kwargs, sample_spans=changed)[0]
    assert isinstance(strict, CalendarIntervalFold)
    assert 89 not in strict.test_indices and 89 in strict.purged_indices
    multi = tuple(
        span(
            i,
            asset,
            **(
                {"label_end_time": at(35), "label_available_time": at(36)}
                if i == 29 and asset == "BTC"
                else {}
            ),
        )
        for i in range(90)
        for asset in ("BTC", "ETH")
    )
    multi_kwargs: dict[str, Any] = {
        **kwargs,
        "available_times": tuple(item.group_time for item in multi),
        "label_end_times": tuple(item.label_end_time for item in multi),
        "valid": (True,) * len(multi),
        "sample_spans": multi,
    }
    grouped = calendar_walkforward(**multi_kwargs)[0]
    assert isinstance(grouped, CalendarIntervalFold)
    assert {58, 59} <= set(grouped.purged_indices)
    assert not {58, 59} & set(grouped.train_indices)


def test_nested_dates_cover_all_42_months_and_tail_rows_are_reported() -> None:
    absent = nested_split_manifest(None)
    assert absent["outer_months"] == 42
    folds = absent["folds"]
    assert folds[0]["test_start"].startswith("2022-04-01")
    assert folds[-1]["test_end"].startswith("2025-10-01")
    assert all(a["test_end"] == b["test_start"] for a, b in pairwise(folds))
    supplied = nested_split_manifest((span(0), span(90), span(1368)))
    assert all(row["status"] == "INSUFFICIENT" for row in supplied["folds"])
    assert supplied["statistical_sufficiency"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize(
    "change",
    [
        "same_episode",
        "future_label",
        "same_id",
        "outer_refit",
        "transform_val",
        "missing_transform",
    ],
)
def test_oof_leakage_is_rejected_before_any_fit(change: str) -> None:
    held = span(10)
    with pytest.raises(ValueError):
        proof = fit_proof()
        if change == "same_episode":
            proof = fit_proof(training_spans=(span(0, episode_id=held.episode_id),))
        elif change == "same_id":
            proof = fit_proof(training_spans=(span(0, sample_id=held.sample_id),))
        elif change == "future_label":
            proof = fit_proof(
                training_spans=(span(0, label_available_time=at(11)),), trained_at=at(12)
            )
        elif change == "outer_refit":
            proof = fit_proof(scope="PURGED_OUTER_TRAIN")
        elif change == "transform_val":
            proof = fit_proof(
                transforms=(
                    TransformFit(
                        name="scaler",
                        specification_sha256=HASH,
                        fit_sample_ids=(held.sample_id,),
                        fitted_at=at(4),
                    ),
                ),
                required_transform_names=("scaler",),
            )
        else:
            proof = fit_proof(required_transform_names=("selector",))
        OOFPrediction(sample=held, prediction=D(1), predicted_at=at(10), fit=proof)


def test_oof_alignment_and_conformal_temporal_limit() -> None:
    proof, registration = register_proof(fit_proof(), tuple(span(i) for i in range(10, 14)))
    rows = tuple(
        OOFPrediction(sample=span(i), prediction=D(i), predicted_at=at(i), fit=proof)
        for i in range(10, 14)
    )
    kwargs: dict[str, Any] = {
        "sample_ids": tuple(r.sample.sample_id for r in rows),
        "timestamps": tuple(r.sample.group_time for r in rows),
        "label_end_times": tuple(r.sample.label_end_time for r in rows),
        "consumed_at": at(20),
        "registrations": (registration,),
    }
    digest = validate_oof_alignment(rows, **kwargs)
    fitted = fit_split_conformal(
        predictions=tuple(r.prediction for r in rows),
        realized=(D(11), D(12), D(13), D(14)),
        alpha=D("0.2"),
        oof_predictions=rows,
        applied_at=at(20),
        registrations=(registration,),
    )
    assert fitted.oof_provenance_sha256 == digest and fitted.residual_quantile == 1
    assert fitted.coverage_contract is not None and "NOT_MEAN_CI" in fitted.coverage_contract
    with pytest.raises(ValueError, match="align"):
        validate_oof_alignment(rows[::-1], **kwargs)
    early: dict[str, Any] = {**kwargs, "consumed_at": at(13)}
    with pytest.raises(ValueError, match="unavailable"):
        validate_oof_alignment(rows, **early)


def test_economic_oof_binding_and_future_target_mutation_without_real_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no real model or calibration fit permitted")

    monkeypatch.setattr(
        "aegisquant.research.models.economic_filter.fit_predict_baseline", forbidden
    )
    monkeypatch.setattr("aegisquant.research.models.economic_filter.fit_predict_tree", forbidden)
    monkeypatch.setattr(
        "aegisquant.research.models.economic_filter.LogisticRegression.fit", forbidden
    )

    def dataset(days: tuple[int, ...]) -> BaselineDataset:
        return BaselineDataset(
            sample_ids=tuple(f"BTC:{i}" for i in days),
            timestamps=tuple(at(i) for i in days),
            feature_names=("trend",),
            features=((1.0,),) * len(days),
            targets=(1.0, 2.0, 3.0, 4.0) * (len(days) // 4),
        )

    train_days = (0, 1, 2, 3, 10, 11, 12, 13)
    train, validation, test = (
        dataset(train_days),
        dataset((10, 11, 12, 13)),
        dataset((20, 21, 22, 23)),
    )
    inner, inner_registration = register_proof(fit_proof(), tuple(span(i) for i in range(10, 14)))
    oof = tuple(
        OOFPrediction(sample=span(i), prediction=D(j), predicted_at=at(i), fit=inner)
        for j, i in enumerate(range(10, 14))
    )
    proof, outer_registration = register_proof(
        fit_proof(
            fold_id="outer-1",
            scope="PURGED_OUTER_TRAIN",
            training_spans=tuple(span(i) for i in train_days),
            trained_at=at(14),
            model_specification_sha256=canonical_sha256(
                {"family": "CONSTANT", "rule": "TRAIN_MEAN_SAME_CALIBRATION", "seed": 20260903}
            ),
            training_payload_sha256=canonical_sha256(
                {"ids": train.sample_ids, "features": train.features, "targets": train.targets}
            ),
        ),
        tuple(span(i) for i in range(20, 24)),
    )
    kwargs: dict[str, Any] = {
        "family": "CONSTANT",
        "train": train,
        "validation": validation,
        "test": test,
        "train_label_end_times": tuple(span(i).label_end_time for i in train_days),
        "validation_label_end_times": tuple(span(i).label_end_time for i in range(10, 14)),
        "validation_round_trip_costs": (D(0),) * 4,
        "oof_predictions": oof,
        "fit_provenance": proof,
        "evaluation_spans": tuple(span(i) for i in range(20, 24)),
        "registrations": (inner_registration, outer_registration),
    }
    result = fit_economic_filter(**kwargs)
    assert result.mean_bias == 1 and result.forecasts[0].expected_gross_return == D("3.5")
    assert result.oof_provenance_sha256 and result.fitted_model_provenance_sha256
    changed: dict[str, Any] = {
        **kwargs,
        "test": test.model_copy(update={"targets": (999.0, -500.0, 100.0, -20.0)}),
    }
    assert fit_economic_filter(**changed) == result
    bad: dict[str, Any] = {
        **kwargs,
        "fit_provenance": proof.model_copy(update={"training_payload_sha256": "b" * 64}),
    }
    with pytest.raises(ValueError, match="actual training payload"):
        fit_economic_filter(**bad)
    wrong: dict[str, Any] = {
        **kwargs,
        "fit_provenance": proof.model_copy(update={"split_manifest_sha256": "b" * 64}),
    }
    with pytest.raises(ValueError, match="registered fold content"):
        fit_economic_filter(**wrong)


def test_fit_failure_consumes_original_registry_slot(tmp_path: Path) -> None:
    ids = planned_fit_ids()
    assert len(ids) == len(set(ids)) == 150
    assert sum(item.startswith("MODEL:") for item in ids) == 144

    def fail() -> None:
        raise RuntimeError("synthetic fit failure")

    with pytest.raises(RuntimeError, match="synthetic"):
        registered_synthetic_fit_check(tmp_path, ids[0], fail)
    with pytest.raises(FileExistsError):
        registered_synthetic_fit_check(tmp_path, ids[0], lambda: None)
    events = [
        json.loads(line) for line in (tmp_path / "experiment_events.jsonl").read_text().splitlines()
    ]
    assert [row["event"]["event_type"] for row in events] == ["STARTED", "ERROR"]
    assert all(row["event"]["details"]["real_model_fits"] == 0 for row in events)


def test_synthetic_registry_wrapper_blocks_fit_before_its_body(tmp_path: Path) -> None:
    called = False

    def fit() -> None:
        nonlocal called
        called = True

    with pytest.raises(PermissionError, match="FORBIDDEN-CALL"):
        registered_synthetic_fit_check(tmp_path, planned_fit_ids()[0], fit)
    assert not called
    with pytest.raises(FileExistsError):
        registered_synthetic_fit_check(tmp_path, planned_fit_ids()[0], lambda: None)


def test_ml_cannot_veto_risk_reduction() -> None:
    assert permit_ml_entry(risk_reduction=True, model_available=False, accepted=False)
    assert not permit_ml_entry(risk_reduction=False, model_available=False, accepted=True)


def test_episode_complete_rejected_opportunities_costs_and_maturity() -> None:
    path = tuple(
        PricePathObservation(
            instrument_id="BTC",
            event_time=at(i),
            available_time=at(i) + timedelta(minutes=1),
            executable_price=D(price),
            source_dataset_id="synthetic",
        )
        for i, price in enumerate((100, 100, 90, 120, 110))
    )
    opportunities = tuple(
        BaseOpportunity(
            opportunity_id=f"o{i}",
            episode_id=f"e{i}",
            base_policy_sha256=HASH,
            instrument_id="BTC",
            decision_index=0,
            exit_index=3,
            feature_dependency_start=at(0),
            decision_time=path[0].available_time,
            exit_reason="RISK_EXIT",
            exit_reason_available_time=at(2),
            capital_committed=D(100),
            accepted_by_ml=accepted,
        )
        for i, accepted in enumerate((False, True))
    )
    kwargs: dict[str, Any] = {
        "opportunities": opportunities,
        "expected_opportunity_ids": ("o0", "o1"),
        "opportunity_set_sha256": canonical_sha256(["o0", "o1"]),
        "observations": {"BTC": path},
        "costs": {
            f"o{i}": CostAssumption(
                policy_version="frozen", long_entry_cost=D("0.01"), long_exit_cost=D("0.02")
            )
            for i in range(2)
        },
        "observed_through": at(4),
    }
    rows = label_base_opportunities(**kwargs)
    assert len(rows) == 2 and rows[0].opportunity.accepted_by_ml is False
    assert rows[0].return_path.net_return == D("0.17")
    assert rows[0].return_path.maximum_adverse_excursion == D("-0.1")
    assert rows[0].return_path.maximum_favorable_excursion == D("0.2")
    assert rows[0].evidence_kind == "COUNTERFACTUAL_FROZEN_BASE"
    assert rows[0].capital_seconds == D(100 * 2 * 86400)
    missing: dict[str, Any] = {**kwargs, "opportunities": opportunities[1:]}
    with pytest.raises(ValueError, match="unfiltered"):
        label_base_opportunities(**missing)
    early: dict[str, Any] = {**kwargs, "observed_through": at(3)}
    with pytest.raises(ValueError, match="matured"):
        label_base_opportunities(**early)


def test_missing_history_never_fabricates_dsr_or_pbo() -> None:
    result = audited_deflated_sharpe_ratio(
        observed_sharpe=D(1),
        observations=100,
        skewness=D(0),
        kurtosis=D(3),
        trial_sharpes=None,
        trial_ids=None,
        complete_trial_history=False,
        return_frequency=None,
        kurtosis_convention=None,
        sample_dependence=None,
        trial_correlation_policy=None,
        evidence_sha256=None,
    )
    assert result["status"] == "INSUFFICIENT" and result["probability"] is None
    pbo = audited_probability_of_backtest_overfitting(
        None,
        strategy_ids=None,
        score_id="MEAN_RETURN_V2",
        registered_selection_score_id="MEAN_RETURN_V2",
        complete_trial_history=False,
    )
    assert pbo["probability"] is None


@pytest.mark.parametrize("score", ["MEAN_RETURN_V2", "SHARPE_PER_PERIOD_V2"])
def test_pbo_ties_are_invariant_to_array_order_and_identical_is_unknown(score: Any) -> None:
    matrix = tuple(((D(i), D(i + 1)), (D(i), D(i + 1)), (D(4 - i), D(2 - i))) for i in range(4))
    kwargs: dict[str, Any] = {
        "score_id": score,
        "registered_selection_score_id": score,
        "complete_trial_history": True,
    }
    a = audited_probability_of_backtest_overfitting(matrix, strategy_ids=("a", "b", "c"), **kwargs)
    b = audited_probability_of_backtest_overfitting(
        tuple(tuple(segment[i] for i in (2, 0, 1)) for segment in matrix),
        strategy_ids=("c", "a", "b"),
        **kwargs,
    )
    assert a == b
    same = tuple(((D(i), D(i + 1)),) * 3 for i in range(4))
    result = audited_probability_of_backtest_overfitting(
        same, strategy_ids=("a", "b", "c"), **kwargs
    )
    assert result["status"] == "UNIDENTIFIABLE" and result["probability"] is None
    with pytest.raises(ValueError, match="registered selection"):
        audited_probability_of_backtest_overfitting(
            matrix,
            strategy_ids=("a", "b", "c"),
            score_id="SHARPE_PER_PERIOD_V2",
            registered_selection_score_id="MEAN_RETURN_V2",
            complete_trial_history=True,
        )


def test_protocol_report_cannot_claim_real_results_or_enable_training() -> None:
    config = yaml.safe_load(
        Path("configs/research/alpha_v5_ml_contract.yaml").read_text(encoding="utf-8")
    )
    validate_config(config)
    config["real_training_authorized"] = True
    with pytest.raises(ValueError, match="NOT-AUTHORIZED"):
        validate_config(config)
    docs = build_documents({"b2_safety": {"strict_data_quality": "INSUFFICIENT"}})
    assert docs["outer_metrics.json"]["rows"] is None
    assert docs["fit_and_calibration_log.json"]["real_model_fits"] == 0
    assert docs["candidate_freeze_draft.json"]["holdout_path"] is None
    assert "NO_PROVEN_ALPHA" in docs["report.md"]
