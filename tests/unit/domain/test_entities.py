"""Reference entity and point-in-time instrument tests."""

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from aegisquant.domain.entities import DeploymentStage, Environment
from aegisquant.domain.identifiers import EnvironmentId
from tests.factories import NOW, instrument


def test_instrument_preserves_versioned_market_rules() -> None:
    contract = instrument()
    assert contract.valid_from == NOW
    assert contract.valid_to is None
    assert contract.price_tick.amount.as_tuple().exponent == -2


def test_instrument_rejects_mismatched_minimum_notional_unit() -> None:
    contract = instrument()
    payload = contract.model_dump(mode="json")
    payload["min_notional"] = {"amount": "5", "asset_id": "BTC"}
    with pytest.raises(ValidationError, match="minimum notional"):
        type(contract).model_validate_json(json.dumps(payload))


def test_instrument_validity_interval_must_increase() -> None:
    contract = instrument()
    payload = contract.model_dump(mode="json")
    payload["valid_to"] = (NOW - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="validity interval"):
        type(contract).model_validate_json(json.dumps(payload))


def test_environment_has_no_live_unlock_path() -> None:
    with pytest.raises(ValidationError, match="LIVE-LOCKED"):
        Environment(
            environment_id=EnvironmentId("live"),
            stage=DeploymentStage.LIVE,
            live_trading_locked=True,
        )
