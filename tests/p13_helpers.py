"""Deterministic, non-network P13 runtime fixtures."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.values import Price, Quantity
from aegisquant.runtime.models import MarketObservation, PredictionTrace
from aegisquant.runtime.paper import PaperFillPolicy
from aegisquant.runtime.runner import RuntimeCommandBundle
from tests.p12_helpers import (
    BTC,
    INSTRUMENT,
    NOW,
    STRATEGY,
    USDT,
    command,
)


def prediction() -> PredictionTrace:
    return PredictionTrace(
        prediction_id="prediction-p13",
        strategy_id=STRATEGY,
        model_version_id="model-p13-v1",
        risk_decision_id=command().risk_decision_id,
        instrument_id=INSTRUMENT,
        side=command().side,
        predicted_return=Decimal("0.012"),
        confidence=Decimal("0.72"),
        target_quantity=command().quantity,
        expected_price=Price(amount=Decimal("50000"), base_asset_id=BTC, quote_asset_id=USDT),
        generated_at=NOW + timedelta(seconds=2),
        valid_until=NOW + timedelta(minutes=4),
        source_event_ids=("market-p13-source",),
    )


def market(
    *,
    event_id: str = "market-p13-1",
    sequence: int = 1,
    seconds: int = 3,
    ask_quantity: Decimal = Decimal("2"),
    bid_quantity: Decimal = Decimal("2"),
    ask_price: Decimal = Decimal("49990"),
    bid_price: Decimal = Decimal("49980"),
) -> MarketObservation:
    payload = {
        "event_id": event_id,
        "sequence": sequence,
        "ask_quantity": str(ask_quantity),
        "bid_quantity": str(bid_quantity),
        "ask_price": str(ask_price),
        "bid_price": str(bid_price),
    }
    event_time = NOW + timedelta(seconds=seconds, milliseconds=-200)
    available_at = NOW + timedelta(seconds=seconds)
    received_at = NOW + timedelta(seconds=seconds, milliseconds=50)
    return MarketObservation(
        event_id=event_id,
        source_id="p13-public-market-fixture",
        source_sha256=canonical_sha256(payload),
        instrument_id=INSTRUMENT,
        venue_id=command().command.venue_id,
        sequence=sequence,
        event_time=event_time,
        available_at=available_at,
        received_at=received_at,
        bid_price=Price(amount=bid_price, base_asset_id=BTC, quote_asset_id=USDT),
        bid_quantity=Quantity(amount=bid_quantity, asset_id=BTC),
        ask_price=Price(amount=ask_price, base_asset_id=BTC, quote_asset_id=USDT),
        ask_quantity=Quantity(amount=ask_quantity, asset_id=BTC),
        last_price=Price(
            amount=(bid_price + ask_price) / Decimal("2"),
            base_asset_id=BTC,
            quote_asset_id=USDT,
        ),
    )


def paper_policy(*, participation_rate: Decimal = Decimal("0.25")) -> PaperFillPolicy:
    return PaperFillPolicy(
        acknowledgement_latency_ms=100,
        participation_rate=participation_rate,
        taker_slippage_bps=Decimal("2"),
        fee_bps=Decimal("4"),
    )


def bundle() -> RuntimeCommandBundle:
    return RuntimeCommandBundle(
        bundle_id="runtime-bundle-p13",
        prediction=prediction(),
        command=command(),
    )
