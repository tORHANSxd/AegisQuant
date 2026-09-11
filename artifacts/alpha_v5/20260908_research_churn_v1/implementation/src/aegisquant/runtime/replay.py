"""Normalized historical-event morphology replay without raw-tick claims."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.values import Price, Quantity, canonical_result
from aegisquant.runtime.models import MarketObservation, RuntimeMode
from aegisquant.runtime.paper import PaperEngine, PaperFillPolicy
from aegisquant.runtime.runner import RuntimeCommandBundle


class HistoricalRuntimeScenario(DomainModel):
    scenario_id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)
    source_description: str = Field(min_length=1)
    source_sha256: str
    normalized_fixture: bool
    raw_tick_data_claimed: bool
    observations: tuple[MarketObservation, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_scenario(self) -> HistoricalRuntimeScenario:
        ensure_sha256(self.source_sha256, field_name="source_sha256")
        if not self.normalized_fixture or self.raw_tick_data_claimed:
            raise ValueError("P13 scenario must disclose normalized, non-raw-tick evidence")
        sequences = [item.sequence for item in self.observations]
        available = [item.available_at for item in self.observations]
        if len(sequences) != len(set(sequences)) or sequences != sorted(sequences):
            raise ValueError("historical scenario sequence must be unique and increasing")
        if available != sorted(available):
            raise ValueError("historical scenario availability must be monotonic")
        return self


class HistoricalReplayResult(DomainModel):
    scenario_id: str
    mode: RuntimeMode
    observation_count: int = Field(ge=1)
    economic_order_count: int = Field(ge=0)
    fill_ids: tuple[str, ...]
    checkpoint_sha256: str
    normalized_fixture: bool
    raw_tick_data_claimed: bool
    duplicate_order_count: int = Field(ge=0)
    duplicate_fill_count: int = Field(ge=0)
    venue_network_requests_performed: int = Field(ge=0)
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result(self) -> HistoricalReplayResult:
        ensure_sha256(self.checkpoint_sha256, field_name="checkpoint_sha256")
        if self.mode is not RuntimeMode.HISTORICAL_REPLAY:
            raise ValueError("historical replay result has the wrong mode")
        if (
            not self.normalized_fixture
            or self.raw_tick_data_claimed
            or self.duplicate_order_count
            or self.duplicate_fill_count
            or self.venue_network_requests_performed
        ):
            raise ValueError("historical replay contains an unsupported claim")
        return self


def build_normalized_liquidity_scenario(*, anchor: MarketObservation) -> HistoricalRuntimeScenario:
    """Create a disclosed spread-widening/liquidity-drop morphology around an anchor quote."""
    observations: list[MarketObservation] = []
    shapes = (
        (Decimal("1"), Decimal("1"), Decimal("1")),
        (Decimal("0.97"), Decimal("0.971"), Decimal("0.30")),
        (Decimal("0.93"), Decimal("0.934"), Decimal("0.12")),
        (Decimal("0.95"), Decimal("0.952"), Decimal("0.45")),
    )
    for offset, (bid_factor, ask_factor, liquidity_factor) in enumerate(shapes):
        event_time = anchor.event_time + timedelta(minutes=offset)
        available_at = anchor.available_at + timedelta(minutes=offset)
        received_at = anchor.received_at + timedelta(minutes=offset)
        bid = Price(
            amount=canonical_result(anchor.bid_price.amount * bid_factor),
            base_asset_id=anchor.bid_price.base_asset_id,
            quote_asset_id=anchor.bid_price.quote_asset_id,
        )
        ask = Price(
            amount=canonical_result(anchor.ask_price.amount * ask_factor),
            base_asset_id=anchor.ask_price.base_asset_id,
            quote_asset_id=anchor.ask_price.quote_asset_id,
        )
        last = Price(
            amount=canonical_result((bid.amount + ask.amount) / Decimal("2")),
            base_asset_id=bid.base_asset_id,
            quote_asset_id=bid.quote_asset_id,
        )
        source = {
            "scenario": "normalized-liquidity-dislocation-v1",
            "anchor_source_sha256": anchor.source_sha256,
            "offset": offset,
            "bid_factor": str(bid_factor),
            "ask_factor": str(ask_factor),
            "liquidity_factor": str(liquidity_factor),
        }
        observations.append(
            MarketObservation(
                event_id=f"normalized-liquidity-{offset}",
                source_id="p13-normalized-public-history-fixture",
                source_sha256=canonical_sha256(source),
                instrument_id=anchor.instrument_id,
                venue_id=anchor.venue_id,
                sequence=anchor.sequence + offset,
                event_time=event_time,
                available_at=available_at,
                received_at=received_at,
                bid_price=bid,
                bid_quantity=Quantity(
                    amount=canonical_result(anchor.bid_quantity.amount * liquidity_factor),
                    asset_id=anchor.bid_quantity.asset_id,
                ),
                ask_price=ask,
                ask_quantity=Quantity(
                    amount=canonical_result(anchor.ask_quantity.amount * liquidity_factor),
                    asset_id=anchor.ask_quantity.asset_id,
                ),
                last_price=last,
            )
        )
    descriptor = {
        "scenario_id": "normalized-liquidity-dislocation-v1",
        "method": "deterministic spread and liquidity morphology",
        "raw_tick_data_claimed": False,
        "observations": [item.source_sha256 for item in observations],
    }
    return HistoricalRuntimeScenario(
        scenario_id="normalized-liquidity-dislocation-v1",
        label="重大加密资产流动性错位形态（归一化夹具）",
        source_description=(
            "公开历史重大波动的一般化价差扩张与深度下降形态；不是交易所逐笔原始数据"
        ),
        source_sha256=canonical_sha256(descriptor),
        normalized_fixture=True,
        raw_tick_data_claimed=False,
        observations=tuple(observations),
    )


def replay_historical_scenario(
    *,
    bundle: RuntimeCommandBundle,
    scenario: HistoricalRuntimeScenario,
    paper_policy: PaperFillPolicy,
) -> HistoricalReplayResult:
    engine = PaperEngine(mode=RuntimeMode.HISTORICAL_REPLAY, policy=paper_policy)
    engine.submit(bundle.command)
    for observation in scenario.observations:
        engine.process(observation)
    checkpoint = engine.checkpoint()
    fill_ids = tuple(item.fill_id for item in engine.fills)
    return HistoricalReplayResult(
        scenario_id=scenario.scenario_id,
        mode=RuntimeMode.HISTORICAL_REPLAY,
        observation_count=len(scenario.observations),
        economic_order_count=engine.economic_order_count,
        fill_ids=fill_ids,
        checkpoint_sha256=checkpoint.payload_sha256,
        normalized_fixture=scenario.normalized_fixture,
        raw_tick_data_claimed=scenario.raw_tick_data_claimed,
        duplicate_order_count=0,
        duplicate_fill_count=len(fill_ids) - len(set(fill_ids)),
        venue_network_requests_performed=0,
        reason_codes=("AQ-RUNTIME-HISTORICAL-NORMALIZED-REPLAY",),
    )
