from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.evidence import EvidenceTier
from aegisquant.domain.identifiers import ArtifactId, AssetId, EventId, InstrumentId
from aegisquant.research.causal import (
    EventResponseDataset,
    EventResponseRow,
    HistoricalState,
    build_event_response_dataset,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
ASSET = AssetId("asset:BTC")
INSTRUMENT = InstrumentId("BINANCE:SPOT:BTCUSDT")


def digest(label: str) -> str:
    return canonical_sha256({"fixture": label})


def response_row(index: int) -> EventResponseRow:
    decision = BASE + timedelta(days=index * 8)
    actual = Decimal("3.5") + Decimal(index) / Decimal("10")
    expected = Decimal("3.0")
    return EventResponseRow(
        event_id=EventId(f"event-p06-{index}"),
        event_revision_id=ArtifactId(digest(f"revision-{index}")),
        canonical_event_sha256=digest(f"canonical-event-{index}"),
        event_type="MACRO_RELEASE",
        asset=ASSET,
        instrument_id=INSTRUMENT,
        decision_time=decision,
        event_available_at=decision - timedelta(seconds=1),
        feature_available_at=decision,
        label_start_time=decision + timedelta(minutes=1),
        label_end_time=decision + timedelta(days=7),
        outcome_available_at=decision + timedelta(days=7, minutes=1),
        truth_probability_at_t=Decimal("0.97"),
        source_quality_at_t=Decimal("0.93"),
        novelty_at_t=Decimal("0.80"),
        market_reflection_at_t=Decimal("0.35"),
        actual=actual,
        expected=expected,
        surprise=actual - expected,
        regime="NEWS_SHOCK",
        pre_event_returns=(Decimal("-0.01"), Decimal("0"), Decimal("0.01")),
        pre_event_vol=Decimal("0.02"),
        spread=Decimal("0.0002"),
        depth=Decimal("1000000"),
        funding=Decimal("0.0001"),
        basis=Decimal("0.001"),
        open_interest=Decimal("5000000"),
        liquidations=Decimal("25000"),
        cross_asset_state=(Decimal("0.1"), Decimal("-0.1")),
        narrative_state=(Decimal("0.6"), Decimal("0.4")),
        return_5m=Decimal("0.001"),
        return_30m=Decimal("0.004"),
        return_4h=Decimal("0.009"),
        return_1d=Decimal("0.012"),
        return_7d=Decimal("0.018"),
        vol_delta=Decimal("0.003"),
        liquidity_delta=Decimal("-0.02"),
        tail_event=False,
        maximum_favorable_excursion=Decimal("0.025"),
        maximum_adverse_excursion=Decimal("-0.006"),
        source_dataset_ids=("official-events", "public-market"),
        feature_snapshot_sha256=digest(f"feature-{index}"),
        label_sha256=digest(f"label-{index}"),
        universe_snapshot_sha256=digest(f"universe-{index}"),
    )


def response_dataset() -> EventResponseDataset:
    rows = tuple(response_row(index) for index in range(4))
    as_of = rows[-1].outcome_available_at
    return build_event_response_dataset(
        dataset_id="p06-event-response-development",
        evidence_tier=EvidenceTier.DEVELOPMENT,
        as_of_time=as_of,
        created_at=as_of + timedelta(seconds=1),
        rows=rows,
        feature_definition_hashes=(digest("feature-definition"),),
        label_definition_hashes=(digest("label-definition"),),
        cost_policy_sha256=digest("cost-policy"),
    )


def historical_state(
    state_id: str,
    *,
    decision_time: datetime,
    covariates: tuple[Decimal, Decimal],
    pre_path: tuple[Decimal, Decimal, Decimal],
    outcome: Decimal,
    event_id: EventId | None = None,
) -> HistoricalState:
    return HistoricalState(
        state_id=state_id,
        event_id=event_id,
        asset=ASSET,
        instrument_id=INSTRUMENT,
        regime="NEWS_SHOCK",
        decision_time=decision_time,
        feature_available_at=decision_time,
        outcome_available_at=decision_time + timedelta(hours=1),
        covariate_names=("pre_return", "pre_vol"),
        covariates=covariates,
        pre_treatment_outcomes=pre_path,
        outcome=outcome,
        source_sha256=digest(f"state-{state_id}"),
    )
