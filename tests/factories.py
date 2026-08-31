"""Small deterministic domain fixtures shared by P01 tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.domain.accounting import JournalEntry, LedgerPosting, PostingSide
from aegisquant.domain.entities import (
    AssetClass,
    ContractDirection,
    Instrument,
    InstrumentStatus,
    InstrumentType,
)
from aegisquant.domain.execution import OrderIntent, OrderSide, OrderType, TimeInForce
from aegisquant.domain.identifiers import (
    AccountId,
    ArtifactId,
    AssetId,
    ForecastId,
    IdempotencyKey,
    InstrumentId,
    LedgerEntryId,
    ModelVersionId,
    OrderIntentId,
    PostingId,
    ProviderId,
    RiskDecisionId,
    SignalId,
    SourcePolicyId,
    StrategyVersionId,
    VenueId,
)
from aegisquant.domain.intelligence import (
    AlphaSignal,
    DirectionProbabilities,
    ForecastBundle,
    ForecastDistribution,
    ForecastHorizon,
    ForecastTarget,
    ForecastUncertainty,
    SignalDirection,
)
from aegisquant.domain.policy import (
    AccessMethod,
    CloudInferenceMode,
    DerivedStorageMode,
    DisplayMode,
    FineTuningMode,
    PiiMode,
    PolicyStatus,
    RawStorageMode,
    RedistributionMode,
    SourceProcessingPolicy,
)
from aegisquant.domain.values import Money, Price, Quantity

NOW = datetime(2026, 8, 31, 8, tzinfo=UTC)
BTC = AssetId("BTC")
USDT = AssetId("USDT")
INSTRUMENT = InstrumentId("BINANCE:PERP:BTCUSDT")


def money(amount: str = "100") -> Money:
    return Money(amount=Decimal(amount), asset_id=USDT)


def quantity(amount: str = "1") -> Quantity:
    return Quantity(amount=Decimal(amount), asset_id=BTC)


def price(amount: str = "50000") -> Price:
    return Price(amount=Decimal(amount), base_asset_id=BTC, quote_asset_id=USDT)


def instrument() -> Instrument:
    return Instrument(
        instrument_id=INSTRUMENT,
        venue_id=VenueId("BINANCE"),
        venue_symbol="BTCUSDT",
        asset_class=AssetClass.CRYPTO,
        instrument_type=InstrumentType.PERPETUAL,
        base_asset_id=BTC,
        quote_asset_id=USDT,
        settlement_asset_id=USDT,
        contract_size=quantity("1"),
        linear_inverse=ContractDirection.LINEAR,
        price_tick=price("0.10"),
        quantity_step=quantity("0.001"),
        min_quantity=quantity("0.001"),
        min_notional=money("5"),
        status=InstrumentStatus.TRADING,
        valid_from=NOW,
        source_snapshot_id=ArtifactId("instrument-snapshot-1"),
    )


def approved_policy() -> SourceProcessingPolicy:
    return SourceProcessingPolicy(
        source_policy_id=SourcePolicyId("official-feed-v1"),
        provider_id=ProviderId("official-feed"),
        policy_status=PolicyStatus.APPROVED,
        access_method=AccessMethod.OFFICIAL_API,
        approved_use_case="private market event analysis",
        content_scope="public announcements",
        raw_storage=RawStorageMode.ENCRYPTED_LOCAL,
        derived_storage=DerivedStorageMode.ALLOWED,
        cloud_inference=CloudInferenceMode.ALLOWED,
        fine_tuning=FineTuningMode.PROHIBITED,
        display_mode=DisplayMode.DERIVED_ONLY,
        deletion_sync_required=True,
        revision_sync_required=True,
        redistribution=RedistributionMode.IDS_ONLY,
        retention_days=30,
        pii_mode=PiiMode.MINIMIZE_AND_PSEUDONYMIZE,
        policy_checked_at=NOW,
        terms_version_hash="a" * 64,
    )


def forecast_bundle() -> ForecastBundle:
    return ForecastBundle(
        forecast_id=ForecastId("forecast-1"),
        model_version_id=ModelVersionId("model-version-1"),
        instrument_id=INSTRUMENT,
        as_of_time=NOW,
        horizon=ForecastHorizon.ONE_HOUR,
        target=ForecastTarget.NET_RETURN,
        distribution=ForecastDistribution(
            mean=Decimal("0.01"),
            std=Decimal("0.02"),
            q05=Decimal("-0.02"),
            q50=Decimal("0.01"),
            q95=Decimal("0.04"),
        ),
        probabilities=DirectionProbabilities(
            up=Decimal("0.55"), flat=Decimal("0.15"), down=Decimal("0.30")
        ),
        calibration_version="calibration-1",
        uncertainty=ForecastUncertainty(
            epistemic=Decimal("0.01"),
            aleatoric=Decimal("0.02"),
            ensemble_disagreement=Decimal("0.01"),
        ),
        regime_id="trend",
        feature_snapshot_id=ArtifactId("feature-snapshot-1"),
        dataset_manifest_hash="b" * 64,
        code_commit="c" * 40,
        should_abstain=False,
    )


def alpha_signal() -> AlphaSignal:
    return AlphaSignal(
        signal_id=SignalId("signal-1"),
        strategy_version_id=StrategyVersionId("strategy-version-1"),
        instrument_id=INSTRUMENT,
        as_of_time=NOW,
        valid_until=NOW + timedelta(minutes=5),
        expected_gross_return=Decimal("0.012"),
        expected_cost=Decimal("0.002"),
        expected_net_return=Decimal("0.010"),
        expected_risk=Decimal("0.020"),
        confidence=Decimal("0.75"),
        score=Decimal("1.25"),
        direction=SignalDirection.LONG,
        capacity_notional=money("10000"),
        source_forecast_ids=(ForecastId("forecast-1"),),
        reason_codes=("POSITIVE_NET_RETURN",),
    )


def order_intent() -> OrderIntent:
    return OrderIntent(
        order_intent_id=OrderIntentId("intent-1"),
        risk_decision_id=RiskDecisionId("risk-1"),
        instrument_id=INSTRUMENT,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity("0.01"),
        limit_price=price("50000"),
        time_in_force=TimeInForce.GOOD_TIL_CANCELED,
        reduce_only=False,
        created_at=NOW,
        valid_until=NOW + timedelta(minutes=1),
        idempotency_key=IdempotencyKey("intent-key-1"),
    )


def balanced_journal(amount: str = "10") -> JournalEntry:
    debit = LedgerPosting(
        posting_id=PostingId("posting-debit"),
        account_id=AccountId("cash"),
        side=PostingSide.DEBIT,
        amount=money(amount),
        memo="asset received",
    )
    credit = LedgerPosting(
        posting_id=PostingId("posting-credit"),
        account_id=AccountId("clearing"),
        side=PostingSide.CREDIT,
        amount=money(amount),
        memo="clearing credited",
    )
    return JournalEntry(
        journal_entry_id=LedgerEntryId("journal-1"),
        event_time=NOW,
        recorded_at=NOW,
        description="balanced fixture",
        postings=(debit, credit),
    )
