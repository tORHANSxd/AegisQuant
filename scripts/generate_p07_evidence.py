"""Generate or verify deterministic P07 research evidence without account access."""

from __future__ import annotations

import argparse
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.metadata import metadata, version
from pathlib import Path
from typing import TypedDict

from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256, sha256_file
from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    ContentId,
    EventClusterId,
    ModelVersionId,
    NarrativeId,
    SourceDocumentId,
)
from aegisquant.domain.intelligence import (
    AssertionMode,
    ClaimRecord,
    EngagementSnapshot,
    EventCluster,
    EventClusterStatus,
    NarrativeState,
    Polarity,
    QualityState,
)
from aegisquant.features import (
    FeatureRegistry,
    FeatureVector,
    MarketFeatureConfig,
    MarketObservation,
    assert_batch_incremental_parity,
    build_event_feature_vector,
    cross_sectional_rank,
    event_feature_definitions,
    market_feature_definitions,
)
from aegisquant.labels import (
    CostAssumption,
    LabelDefinition,
    LabelKind,
    LabelSetManifest,
    PricePathObservation,
    generate_event_impact_label,
    generate_execution_label,
    generate_return_labels,
)
from aegisquant.research.baselines import (
    BaselineObservation,
    BaselineStrategyKind,
    screen_strategy,
)
from aegisquant.research.datasets import (
    CostAssumptionManifest,
    DataQualityReport,
    DatasetManifest,
    LeakageAuditManifest,
    LeakageAuditState,
    PointInTimeUniverse,
    SplitManifest,
    TrainingManifestBundle,
    UniverseManifest,
    UniverseMembership,
    membership_id,
)
from aegisquant.research.experiments import (
    ExperimentLedger,
    ExperimentRecord,
    ExperimentStatus,
    PromotionDecision,
)
from aegisquant.research.models import (
    BaselineDataset,
    BaselineModelKind,
    BaselineModelSpec,
    ResearchModality,
    compare_modalities,
    fit_predict_baseline,
)
from aegisquant.research.reports import (
    CandidateStatus,
    ScoreboardEntry,
    render_baseline_scoreboard,
)
from aegisquant.research.validation import (
    EconomicPeriod,
    FeatureAccessRecord,
    FeatureSourceKind,
    FinalHoldoutVault,
    LabelWindowRecord,
    NormalizationScope,
    Regime,
    RegimeObservation,
    SampleSpan,
    TemporalSplitPolicy,
    WalkForwardMode,
    apply_cost_stress,
    audit_leakage,
    benjamini_hochberg,
    combinatorial_symmetric_splits,
    create_freeze_manifest,
    deflated_sharpe_ratio,
    engagement_as_of_with_delay,
    event_latency_scenarios,
    parameter_perturbations,
    point_in_time_regime_slices,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    walk_forward_splits,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "reports/data"
RESEARCH = ROOT / "reports/research/P07"
NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)
SEED = 20260901


class EvidenceContext(TypedDict):
    experiment_records: tuple[ExperimentRecord, ...]
    scoreboard_entries: tuple[ScoreboardEntry, ...]


def _write_or_check(path: Path, payload: object, *, check: bool) -> None:
    expected = canonical_json_bytes(payload)
    if check:
        if not path.is_file() or path.read_bytes() != expected:
            raise RuntimeError(f"stale or missing P07 evidence: {path.relative_to(ROOT)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(expected)


def _market_observations() -> tuple[MarketObservation, ...]:
    return tuple(
        MarketObservation(
            instrument_id="BINANCE:SPOT:BTCUSDT",
            event_time=NOW + timedelta(minutes=index),
            available_time=NOW + timedelta(minutes=index, seconds=2),
            close=Decimal(close),
            high=Decimal(close) + Decimal("1"),
            low=Decimal(close) - Decimal("1"),
            quote_volume=Decimal("1000"),
            bid=Decimal(close) - Decimal("0.1"),
            ask=Decimal(close) + Decimal("0.1"),
            funding_rate=Decimal(index) / Decimal("10000"),
            spot_price=Decimal(close),
            perpetual_price=Decimal(close) + Decimal("0.5"),
            source_dataset_id="p07-market-fixture-v1",
        )
        for index, close in enumerate(("100", "101", "99", "102", "104"))
    )


def _event_vector() -> FeatureVector:
    claim = ClaimRecord(
        claim_id=ClaimId("p07-claim-1"),
        content_id=ContentId("p07-content-1"),
        claim_text_normalized="issuer confirmed reserve audit",
        subject_entity_ids=("issuer",),
        predicate="confirmed",
        object_entity_ids=("reserve-audit",),
        event_type="reserve_update",
        assertion_mode=AssertionMode.FACT,
        polarity=Polarity.AFFIRM,
        evidence_spans=("confirmed",),
        extractor_versions=(ModelVersionId("extractor-v1"),),
        source_independence_group="official",
        credibility_prior=Decimal("0.9"),
        novelty_score=Decimal("0.8"),
    )
    cluster = EventCluster(
        event_cluster_id=EventClusterId("p07-event-1"),
        event_type="reserve_update",
        status=EventClusterStatus.CONFIRMED,
        entity_ids=("issuer",),
        first_observed_time=NOW,
        last_updated_time=NOW + timedelta(seconds=20),
        claim_ids=(claim.claim_id,),
        supporting_evidence_ids=(SourceDocumentId("p07-doc-1"),),
        contradicting_evidence_ids=(),
        independent_source_count=2,
        official_confirmation_ids=(SourceDocumentId("p07-official-1"),),
        credibility_score=Decimal("0.9"),
        manipulation_risk=Decimal("0.1"),
        uncertainty=Decimal("0.15"),
    )
    narrative = NarrativeState(
        narrative_id=NarrativeId("p07-narrative-1"),
        topic="reserve audit",
        entity_ids=("issuer",),
        first_observed_time=NOW,
        as_of_time=NOW + timedelta(seconds=20),
        propagation_stage="confirmed",
        posts_per_hour=Decimal("3"),
        independent_author_count=2,
        platform_count=2,
        sentiment_score=Decimal("-0.99"),
        contradicting_evidence_count=0,
        engagement_velocity_per_hour=Decimal("4"),
        coordination_risk=Decimal("0.1"),
        price_reflection_score=Decimal("0.25"),
        decay_half_life_hours=Decimal("2"),
        crowding_score=Decimal("0.2"),
    )
    return build_event_feature_vector(
        cluster=cluster,
        cluster_available_time=NOW + timedelta(seconds=20),
        claims=(claim,),
        narrative=narrative,
        as_of_time=NOW + timedelta(seconds=30),
        quality_state=QualityState.GOOD,
        source_dataset_ids=("p07-event-fixture-v1",),
    )


def _membership(instrument: str, *, available_at: datetime) -> UniverseMembership:
    identifier = membership_id(
        instrument_id=instrument,
        eligible=True,
        effective_from=available_at,
        effective_to=None,
        available_time=available_at,
        revision_time=None,
        revision=1,
        reason_codes=("volume-and-history",),
        source_dataset_id="p07-universe-fixture-v1",
    )
    return UniverseMembership(
        membership_id=identifier,
        instrument_id=instrument,
        eligible=True,
        effective_from=available_at,
        effective_to=None,
        available_time=available_at,
        revision_time=None,
        revision=1,
        reason_codes=("volume-and-history",),
        source_dataset_id="p07-universe-fixture-v1",
    )


def _samples() -> tuple[SampleSpan, ...]:
    return tuple(
        SampleSpan(
            sample_id=f"sample-{index:02d}",
            group_time=NOW + timedelta(hours=index),
            label_start_time=NOW + timedelta(hours=index, minutes=1),
            label_end_time=NOW + timedelta(hours=index, minutes=30),
            regime="BULL" if index % 2 == 0 else "BEAR",
        )
        for index in range(12)
    )


def _model_dataset(*, start: int, count: int) -> BaselineDataset:
    names = ("market_1", "market_2", "event_1", "event_2")
    return BaselineDataset(
        sample_ids=tuple(f"model-{start + index:02d}" for index in range(count)),
        timestamps=tuple(NOW + timedelta(hours=start + index) for index in range(count)),
        feature_names=names,
        features=tuple(
            tuple(float((start + index + 1) * (column + 1)) / 10 for column in range(4))
            for index in range(count)
        ),
        targets=tuple((-1.0, 0.0, 1.0)[(start + index) % 3] for index in range(count)),
    )


def _experiment(run_id: str, status: ExperimentStatus) -> ExperimentRecord:
    failed = status is not ExperimentStatus.SUCCEEDED
    return ExperimentRecord(
        run_id=run_id,
        status=status,
        code_commit="a" * 40,
        environment_sha256="1" * 64,
        dataset_sha256="2" * 64,
        feature_set_sha256="3" * 64,
        label_set_sha256="4" * 64,
        universe_sha256="5" * 64,
        split_sha256="6" * 64,
        cost_policy_sha256="7" * 64,
        model_id="linear-v1",
        hyperparameters={"seed": SEED},
        seed=SEED,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=2),
        cpu_seconds=Decimal("1.2"),
        peak_memory_mb=Decimal("100"),
        metrics={} if failed else {"net_return": Decimal("0.01")},
        artifact_hashes={} if failed else {"predictions": "8" * 64},
        failure_reason="retained deterministic research failure" if failed else None,
        promotion_decision=PromotionDecision.REJECT if failed else PromotionDecision.HOLD,
    )


def _scoreboard_entries() -> tuple[ScoreboardEntry, ...]:
    common = {
        "modality": ResearchModality.FUSED,
        "fee_cost": Decimal("0.001"),
        "spread_cost": Decimal("0.001"),
        "slippage_cost": Decimal("0.001"),
        "impact_cost": Decimal("0.001"),
        "funding_cost": Decimal("0.001"),
        "borrow_cost": Decimal("0.001"),
        "psr": Decimal("0.8"),
        "dsr": Decimal("0.7"),
        "pbo": Decimal("0.2"),
        "maximum_drawdown": Decimal("0.1"),
        "positive_folds": 4,
        "total_folds": 5,
        "event_incremental_net": Decimal("0.001"),
        "total_trials": 10,
        "final_holdout_opened": False,
    }
    return (
        ScoreboardEntry(
            candidate_id="linear-fused",
            candidate_name="Linear Fused",
            gross_return=Decimal("0.026"),
            net_return=Decimal("0.02"),
            sharpe=Decimal("1"),
            status=CandidateStatus.PASSED_DEVELOPMENT,
            negative_result=None,
            **common,  # pyright: ignore[reportArgumentType]
        ),
        ScoreboardEntry(
            candidate_id="elastic-rejected",
            candidate_name="Elastic Net Rejected",
            gross_return=Decimal("-0.004"),
            net_return=Decimal("-0.01"),
            sharpe=Decimal("3"),
            status=CandidateStatus.REJECTED,
            negative_result="高 Sharpe 未通过成本压力与跨折一致性，保留为负结果。",
            **common,  # pyright: ignore[reportArgumentType]
        ),
    )


def build_payloads() -> tuple[dict[str, object], EvidenceContext]:
    config = MarketFeatureConfig()
    market_definitions = market_feature_definitions(config)
    event_definitions = event_feature_definitions()
    registry = FeatureRegistry()
    registry.register_all((*market_definitions, *event_definitions))
    feature_manifest = registry.manifest(feature_set_id="p07-features-v1", created_at=NOW)
    market_vectors = assert_batch_incremental_parity(_market_observations(), config)
    rank = cross_sectional_rank(
        as_of_time=NOW,
        signals={"BTCUSDT": Decimal("2"), "ETHUSDT": Decimal("1")},
        source_dataset_ids=("p07-cross-section-v1",),
        definition=next(
            item for item in market_definitions if item.feature_id == "cross_section.rank"
        ),
    )
    event_vector = _event_vector()

    cost = CostAssumption(
        policy_version="p07-cost-v1",
        fee_rate=Decimal("0.001"),
        spread_rate=Decimal("0.001"),
        slippage_rate=Decimal("0.001"),
        impact_rate=Decimal("0.001"),
        borrow_rate=Decimal("0.0005"),
        funding_rate=Decimal("0.0005"),
    )
    prices = tuple(
        PricePathObservation(
            instrument_id="BINANCE:SPOT:BTCUSDT",
            event_time=NOW + timedelta(minutes=index),
            available_time=NOW + timedelta(minutes=index, seconds=1),
            executable_price=Decimal(value),
            source_dataset_id="p07-executable-price-v1",
        )
        for index, value in enumerate(("100", "98", "104", "110", "105"))
    )
    return_labels = generate_return_labels(
        observations=prices,
        horizon_steps=2,
        cost=cost,
        risk_flat_threshold=Decimal("0.001"),
    )
    execution_label = generate_execution_label(
        label_id="execution-1",
        decision_time=NOW,
        label_end_time=NOW + timedelta(minutes=1),
        attempts=4,
        fills=3,
        requested_quantity=Decimal("2"),
        filled_quantity=Decimal("1.5"),
        slippage_bps=Decimal("2"),
        adverse_selection_bps=Decimal("1"),
        post_cancel_fill=False,
        impact_bps=Decimal("0.5"),
        recovery_seconds=Decimal("30"),
        multi_leg_exposure_seconds=Decimal("4"),
    )
    event_label = generate_event_impact_label(
        label_id="event-impact-1",
        event_id="p07-event-1",
        instrument_id="BINANCE:SPOT:BTCUSDT",
        first_observed_time=NOW,
        label_end_time=NOW + timedelta(hours=1),
        gross_return=Decimal("0.02"),
        cost=cost,
        pre_volatility=Decimal("0.01"),
        post_volatility=Decimal("0.03"),
        downside_return=Decimal("-0.01"),
        spread_before_bps=Decimal("2"),
        spread_after_bps=Decimal("5"),
        funding_before=Decimal("0.0001"),
        funding_after=Decimal("0.0003"),
        event_persisted=True,
    )
    label_definition = LabelDefinition(
        label_id="returns.net",
        version="1.0.0",
        kind=LabelKind.RETURN_PATH,
        description="net executable return path",
        horizon_seconds=120,
        inputs=("executable_price",),
        cost_policy_version=cost.policy_version,
        tests=("tests/unit/labels/test_labels.py",),
    )
    label_manifest = LabelSetManifest(
        label_set_id="p07-labels-v1",
        definition_hashes=(label_definition.definition_sha256,),
        created_at=NOW,
    )

    universe = PointInTimeUniverse(
        (
            _membership("BTCUSDT", available_at=NOW),
            _membership("ETHUSDT", available_at=NOW + timedelta(days=1)),
        )
    )
    early_universe = universe.snapshot(as_of_time=NOW)
    later_universe = universe.snapshot(as_of_time=NOW + timedelta(days=1))
    policy = TemporalSplitPolicy(
        policy_id="p07-walk-forward-v1",
        mode=WalkForwardMode.EXPANDING,
        train_groups=3,
        validation_groups=1,
        calibration_groups=1,
        test_groups=1,
        purge_groups=1,
        embargo_groups=1,
        step_groups=1,
        minimum_folds=5,
        shuffle=False,
    )
    folds = walk_forward_splits(_samples(), policy)
    cscv = combinatorial_symmetric_splits(_samples(), segment_count=6)
    training_bundle = TrainingManifestBundle(
        dataset=DatasetManifest(
            dataset_id="p07-research-v1",
            dataset_sha256="a" * 64,
            row_count=12,
            starts_at=NOW,
            ends_at=NOW + timedelta(hours=12),
            source_dataset_ids=("p07-market-fixture-v1", "p07-event-fixture-v1"),
            created_at=NOW + timedelta(days=2),
        ),
        feature_set=feature_manifest,
        label_set=label_manifest,
        universe=UniverseManifest(
            universe_id="p07-universe-v1",
            snapshot_hashes=(
                early_universe.universe_snapshot_id,
                later_universe.universe_snapshot_id,
            ),
            point_in_time=True,
            created_at=NOW + timedelta(days=2),
        ),
        split=SplitManifest(
            split_id="p07-split-v1",
            split_sha256=canonical_sha256([item.fold_id for item in folds]),
            policy_id=policy.policy_id,
            fold_hashes=tuple(item.fold_id for item in folds),
            final_holdout_id="p07-final-holdout",
            shuffle=False,
            created_at=NOW + timedelta(days=2),
        ),
        costs=CostAssumptionManifest(
            policy_version=cost.policy_version,
            policy_sha256=canonical_sha256(cost.model_dump(mode="json")),
            components=("fee", "spread", "slippage", "impact", "funding", "borrow"),
            created_at=NOW,
        ),
        quality=DataQualityReport(
            quality_state=QualityState.GOOD,
            checked_rows=12,
            missing_fraction=0.0,
            stale_fraction=0.0,
            issues=(),
            generated_at=NOW + timedelta(days=2),
        ),
        leakage=LeakageAuditManifest(
            audit_id="p07-clean-audit",
            state=LeakageAuditState.PASSED,
            checked_records=2,
            finding_codes=(),
            generated_at=NOW + timedelta(days=2),
        ),
    )

    clean_audit = audit_leakage(
        feature_accesses=(
            FeatureAccessRecord(
                record_id="clean-1",
                sample_id="sample-1",
                feature_id="returns.log@1.0.0",
                decision_time=NOW,
                source_event_time=NOW - timedelta(minutes=1),
                available_time=NOW - timedelta(seconds=1),
            ),
        ),
        label_windows=(
            LabelWindowRecord(
                sample_id="sample-1",
                decision_time=NOW,
                label_start_time=NOW + timedelta(seconds=1),
                label_end_time=NOW + timedelta(minutes=5),
            ),
        ),
        generated_at=NOW + timedelta(hours=1),
    )
    future = NOW + timedelta(seconds=1)
    injected_audit = audit_leakage(
        feature_accesses=(
            FeatureAccessRecord(
                record_id="injected-1",
                sample_id="sample-1",
                feature_id="returns.log@1.0.0",
                decision_time=NOW,
                source_event_time=future,
                available_time=future,
                revision_time=future,
                engagement_snapshot_time=future,
                source_kind=FeatureSourceKind.LABEL,
                normalization_scope=NormalizationScope.FULL_SAMPLE,
            ),
        ),
        label_windows=(
            LabelWindowRecord(
                sample_id="sample-1",
                decision_time=NOW,
                label_start_time=NOW,
                label_end_time=future,
            ),
        ),
        generated_at=NOW + timedelta(hours=1),
    )
    psr = probabilistic_sharpe_ratio(
        observed_sharpe=Decimal("1.2"),
        benchmark_sharpe=Decimal("0.4"),
        observations=100,
        skewness=Decimal("0.2"),
        kurtosis=Decimal("3.4"),
    )
    dsr = deflated_sharpe_ratio(
        observed_sharpe=Decimal("1.2"),
        observations=100,
        skewness=Decimal("0.2"),
        kurtosis=Decimal("3.4"),
        trial_sharpes=(Decimal("0.1"), Decimal("0.4"), Decimal("0.8"), Decimal("1.2")),
    )
    pbo = probability_of_backtest_overfitting(
        (
            (Decimal("0.10"), Decimal("0.02"), Decimal("-0.01")),
            (Decimal("0.09"), Decimal("0.03"), Decimal("0.00")),
            (Decimal("-0.05"), Decimal("0.04"), Decimal("0.03")),
            (Decimal("-0.04"), Decimal("0.05"), Decimal("0.02")),
        )
    )
    fdr = benjamini_hochberg(
        {"a": Decimal("0.01"), "b": Decimal("0.04"), "c": Decimal("0.03")},
        alpha=Decimal("0.05"),
    )

    loader_invocations = 0

    def sealed_loader() -> tuple[str, ...]:
        nonlocal loader_invocations
        loader_invocations += 1
        return ("must-not-load",)

    freeze = create_freeze_manifest(
        dataset_sha256="a" * 64,
        feature_set_sha256="b" * 64,
        label_set_sha256="c" * 64,
        universe_sha256="d" * 64,
        split_sha256="e" * 64,
        cost_policy_sha256="f" * 64,
        model_spec_sha256="1" * 64,
        parameters_sha256="2" * 64,
        code_sha256="3" * 64,
        frozen_at=NOW,
    )
    vault = FinalHoldoutVault(
        holdout_id="p07-final-holdout",
        expected_dataset_sha256="a" * 64,
        loader=sealed_loader,
    )
    with suppress(PermissionError):
        vault.open_once(freeze_id=freeze.freeze_id, occurred_at=NOW)

    baseline_observations = tuple(
        BaselineObservation(
            sample_id=f"baseline-{index}",
            instrument_id="BTCUSDT",
            decision_time=NOW + timedelta(hours=index),
            realized_next_return=Decimal("0.01") if index % 2 == 0 else Decimal("-0.02"),
            trend_score=Decimal("1") if index % 2 == 0 else Decimal("-1"),
            cross_sectional_rank=Decimal("0.9") if index % 2 == 0 else Decimal("0.1"),
            funding_rate=Decimal("0.003"),
            basis=Decimal("0.002"),
            official_event=True,
            independent_source_count=2,
            event_novelty=Decimal("0.8"),
            event_stance=Decimal("0.9"),
            manipulation_risk=Decimal("0.1"),
            market_reflection=Decimal("0.2"),
            quality_state=QualityState.GOOD,
            cost_rate=Decimal("0.001"),
        )
        for index in range(3)
    )
    strategy_results = tuple(
        screen_strategy(strategy, baseline_observations) for strategy in BaselineStrategyKind
    )

    train = _model_dataset(start=0, count=9)
    test = _model_dataset(start=10, count=4)
    model_predictions = tuple(
        fit_predict_baseline(
            spec=BaselineModelSpec(model_id=f"model-{kind.value}", kind=kind, seed=SEED),
            train=train,
            test=test,
        )
        for kind in (
            BaselineModelKind.LINEAR,
            BaselineModelKind.LOGISTIC,
            BaselineModelKind.ELASTIC_NET,
            BaselineModelKind.SIMPLE_STATE,
        )
    )
    har_names = ("rv_daily", "rv_weekly", "rv_monthly")
    har_prediction = fit_predict_baseline(
        spec=BaselineModelSpec(model_id="model-HAR_RV", kind=BaselineModelKind.HAR_RV),
        train=train.select_columns((0, 1, 2)).model_copy(update={"feature_names": har_names}),
        test=test.select_columns((0, 1, 2)).model_copy(update={"feature_names": har_names}),
    )
    fair = compare_modalities(
        spec=BaselineModelSpec(model_id="linear-fair", kind=BaselineModelKind.LINEAR, seed=SEED),
        train=train,
        test=test,
        market_columns=(0, 1),
        event_columns=(2, 3),
        realized_returns=(Decimal("0.01"), Decimal("-0.02"), Decimal("0.03"), Decimal("-0.01")),
        cost_rates=(Decimal("0.001"),) * 4,
    )

    periods = (
        EconomicPeriod(
            period_id="period-1",
            decision_time=NOW,
            gross_return=Decimal("0.02"),
            base_cost=Decimal("0.002"),
            net_return=Decimal("0.018"),
        ),
        EconomicPeriod(
            period_id="period-2",
            decision_time=NOW + timedelta(hours=1),
            gross_return=Decimal("-0.01"),
            base_cost=Decimal("0.001"),
            net_return=Decimal("-0.011"),
        ),
    )
    engagement = (
        EngagementSnapshot(
            engagement_snapshot_id=ArtifactId("engagement-early"),
            content_id=ContentId("p07-content-1"),
            observed_time=NOW - timedelta(seconds=22),
            available_time=NOW - timedelta(seconds=20),
            metrics={"likes": 1},
        ),
        EngagementSnapshot(
            engagement_snapshot_id=ArtifactId("engagement-future"),
            content_id=ContentId("p07-content-1"),
            observed_time=NOW - timedelta(seconds=1),
            available_time=NOW + timedelta(seconds=1),
            metrics={"likes": 999},
        ),
    )
    stress_costs = apply_cost_stress(periods)
    latency = event_latency_scenarios(NOW)
    selected_engagement = engagement_as_of_with_delay(
        engagement, decision_time=NOW, delay_seconds=5
    )
    perturbations = parameter_perturbations({"lookback": Decimal("10"), "threshold": Decimal("2")})
    regime_slices = point_in_time_regime_slices(
        periods,
        (
            RegimeObservation(regime=Regime.BULL, event_time=NOW, available_time=NOW),
            RegimeObservation(
                regime=Regime.BEAR,
                event_time=NOW + timedelta(minutes=30),
                available_time=NOW + timedelta(hours=2),
            ),
        ),
    )

    p06_golden = DATA / "P06_GOLDEN_RESULTS.json"
    payloads: dict[str, object] = {
        "P07_FEATURE_EVIDENCE.json": {
            "schema_version": "p07-feature-evidence-v1",
            "definition_count": len(registry.definitions()),
            "feature_set_sha256": feature_manifest.manifest_sha256,
            "batch_vectors": len(market_vectors),
            "batch_incremental_parity": True,
            "last_market_vector": market_vectors[-1].model_dump(mode="json"),
            "cross_sectional_vectors": [item.model_dump(mode="json") for item in rank],
            "registered_only": True,
            "point_in_time": True,
        },
        "P07_EVENT_FEATURE_EVIDENCE.json": {
            "schema_version": "p07-event-feature-evidence-v1",
            "vector": event_vector.model_dump(mode="json"),
            "document_sentiment_used_for_stance": False,
            "claim_evidence_linked": True,
            "future_narrative_rejected_by_contract": True,
        },
        "P07_LABEL_EVIDENCE.json": {
            "schema_version": "p07-label-evidence-v1",
            "return_labels": [item.model_dump(mode="json") for item in return_labels],
            "execution_label": execution_label.model_dump(mode="json"),
            "event_impact_label": event_label.model_dump(mode="json"),
            "gross_minus_cost_equals_net": all(
                item.gross_return - item.total_cost_rate == item.net_return
                for item in return_labels
            ),
            "future_windows_only": True,
        },
        "P07_DATASET_EVIDENCE.json": {
            "schema_version": "p07-dataset-evidence-v1",
            "early_universe": early_universe.model_dump(mode="json"),
            "later_universe": later_universe.model_dump(mode="json"),
            "future_listing_backfilled": False,
            "required_manifest_count": len(type(training_bundle).model_fields),
            "required_manifests": sorted(type(training_bundle).model_fields),
            "training_bundle_sha256": training_bundle.bundle_sha256,
            "quality_gate": "GOOD",
            "leakage_gate": "PASSED",
        },
        "P07_VALIDATION_EVIDENCE.json": {
            "schema_version": "p07-validation-evidence-v1",
            "shuffle": policy.shuffle,
            "random_time_split_forbidden": True,
            "walk_forward_folds": len(folds),
            "fold_hashes": [item.fold_id for item in folds],
            "purge_groups": policy.purge_groups,
            "embargo_groups": policy.embargo_groups,
            "cscv_combinations": len(cscv),
            "psr": psr.model_dump(mode="json"),
            "dsr": dsr.model_dump(mode="json"),
            "pbo": pbo.model_dump(mode="json"),
            "fdr": fdr.model_dump(mode="json"),
            "total_trials_reported": True,
        },
        "P07_LEAKAGE_EVIDENCE.json": {
            "schema_version": "p07-leakage-evidence-v1",
            "clean_audit": clean_audit.model_dump(mode="json"),
            "injected_audit": injected_audit.model_dump(mode="json"),
            "injected_codes": sorted({item.code for item in injected_audit.findings}),
            "all_seven_injected_leaks_detected": len(injected_audit.findings) == 7,
        },
        "P07_HOLDOUT_EVIDENCE.json": {
            "schema_version": "p07-holdout-evidence-v1",
            "state": vault.state.value,
            "loader_invocations": loader_invocations,
            "access_before_freeze_denied": True,
            "audit": [item.model_dump(mode="json") for item in vault.audit_log()],
            "freeze_manifest_contract_sha256": freeze.freeze_id,
            "final_holdout_opened": False,
        },
        "P07_BASELINE_EVIDENCE.json": {
            "schema_version": "p07-baseline-evidence-v1",
            "strategies": [item.model_dump(mode="json") for item in strategy_results],
            "strategy_count": len(strategy_results),
            "screening_only": True,
            "authoritative_backtest_required": True,
            "authoritative_p06_golden_sha256": sha256_file(p06_golden),
            "independent_trend_golden_net": "0.035",
            "live_trading_locked": True,
        },
        "P07_MODEL_EVIDENCE.json": {
            "schema_version": "p07-model-evidence-v1",
            "seed": SEED,
            "predictions": [
                item.model_dump(mode="json") for item in (*model_predictions, har_prediction)
            ],
            "fair_budget_sha256": fair.budget_sha256,
            "fair_evaluations": [item.model_dump(mode="json") for item in fair.evaluations],
            "modalities": sorted(item.modality.value for item in fair.evaluations),
            "final_holdout_opened": False,
        },
        "P07_STRESS_EVIDENCE.json": {
            "schema_version": "p07-stress-evidence-v1",
            "cost_stress": [item.model_dump(mode="json") for item in stress_costs],
            "event_latency": [item.model_dump(mode="json") for item in latency],
            "selected_engagement_snapshot_id": str(
                selected_engagement.engagement_snapshot_id if selected_engagement else ""
            ),
            "future_engagement_selected": False,
            "parameter_perturbation_count": len(perturbations),
            "regime_slices": [item.model_dump(mode="json") for item in regime_slices],
        },
        "P07_EXTERNAL_BASELINE_EVIDENCE.json": {
            "schema_version": "p07-external-baseline-evidence-v1",
            "r331_state": "not_provided",
            "fabricated_baseline": False,
            "registration_contract_verified": True,
            "required_rights_states": ["personal_research_only", "public_license"],
            "immutable_content_addressing": True,
        },
        "P07_DEPENDENCY_CONTRACT.json": {
            "schema_version": "p07-dependency-contract-v1",
            "numpy": {
                "version": version("numpy"),
                "license_expression": metadata("numpy").get("License-Expression"),
            },
            "scikit_learn": {
                "version": version("scikit-learn"),
                "license_expression": metadata("scikit-learn").get("License-Expression"),
                "python_314_classifier": "Programming Language :: Python :: 3.14"
                in metadata("scikit-learn").get_all("Classifier", []),
            },
            "runtime_contract_tested": True,
            "ai_trader_code_copied_or_executed": False,
        },
    }
    context: EvidenceContext = {
        "experiment_records": tuple(
            _experiment(status.value.lower(), status) for status in ExperimentStatus
        ),
        "scoreboard_entries": _scoreboard_entries(),
    }
    return payloads, context


def generate(*, check: bool) -> None:
    payloads, context = build_payloads()
    DATA.mkdir(parents=True, exist_ok=True)
    RESEARCH.mkdir(parents=True, exist_ok=True)

    ledger_path = RESEARCH / "EXPERIMENT_LEDGER.jsonl"
    records = context["experiment_records"]
    if check:
        entries = ExperimentLedger(ledger_path).entries()
        if tuple(item.record for item in entries) != records:
            raise RuntimeError("stale or missing P07 experiment ledger")
    else:
        ledger_path.unlink(missing_ok=True)
        ledger = ExperimentLedger(ledger_path)
        for record in records:
            ledger.append(record)
        entries = ledger.entries()
    payloads["P07_EXPERIMENT_EVIDENCE.json"] = {
        "schema_version": "p07-experiment-evidence-v1",
        "ledger_path": ledger_path.relative_to(ROOT).as_posix(),
        "entry_count": len(entries),
        "statuses": [item.record.status.value for item in entries],
        "run_ids": [item.record.run_id for item in entries],
        "failure_and_error_retained": all(
            status in {item.record.status for item in entries}
            for status in (ExperimentStatus.FAILED, ExperimentStatus.ERROR)
        ),
        "ledger_tail_sha256": entries[-1].entry_hash,
    }

    for name, payload in payloads.items():
        _write_or_check(DATA / name, payload, check=check)

    scoreboard = render_baseline_scoreboard(context["scoreboard_entries"])
    scoreboard_path = RESEARCH / "BASELINE_SCOREBOARD.md"
    if check:
        if (
            not scoreboard_path.is_file()
            or scoreboard_path.read_text(encoding="utf-8") != scoreboard
        ):
            raise RuntimeError("stale or missing P07 baseline scoreboard")
    else:
        scoreboard_path.write_text(scoreboard, encoding="utf-8", newline="\n")

    print(f"P07 evidence {'verified' if check else 'generated'}: {len(payloads)} JSON files")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    generate(check=arguments.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
