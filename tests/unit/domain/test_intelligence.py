"""Forecast, signal, and event intelligence invariant tests."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.identifiers import EventId
from aegisquant.domain.intelligence import DirectionProbabilities, MarketEvent
from tests.factories import NOW, alpha_signal, forecast_bundle


def test_forecast_distribution_and_probabilities_are_coherent() -> None:
    forecast = forecast_bundle()
    assert (
        forecast.probabilities.up + forecast.probabilities.flat + forecast.probabilities.down == 1
    )
    with pytest.raises(ValidationError, match="sum exactly"):
        DirectionProbabilities(up=Decimal("0.5"), flat=Decimal("0.2"), down=Decimal("0.2"))


def test_alpha_signal_has_no_order_semantics_and_net_return_is_explicit() -> None:
    signal = alpha_signal()
    assert signal.expected_net_return == Decimal("0.010")
    assert all("order" not in name.lower() for name in type(signal).model_fields)
    payload = signal.model_dump(mode="json")
    payload["expected_net_return"] = "0.011"
    with pytest.raises(ValidationError, match="gross return minus cost"):
        type(signal).model_validate_json(json.dumps(payload))


def test_market_event_enforces_available_ingest_processed_order() -> None:
    valid = MarketEvent(
        event_id=EventId("event-1"),
        event_type="EXCHANGE_ANNOUNCEMENT",
        event_time=NOW,
        available_time=NOW,
        ingest_time=NOW + timedelta(seconds=1),
        processed_time=NOW + timedelta(seconds=2),
    )
    assert valid.processed_time > valid.available_time
    payload = valid.model_dump(mode="json")
    payload["ingest_time"] = (NOW - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="monotonic"):
        type(valid).model_validate_json(json.dumps(payload))
