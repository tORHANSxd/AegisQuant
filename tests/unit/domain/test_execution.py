"""Order intent, venue evidence, and recovery contract tests."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.execution import VenueOrder, VenueOrderStatus
from aegisquant.domain.identifiers import ClientOrderId, OrderIntentId, VenueId
from aegisquant.domain.values import Quantity
from tests.factories import BTC, NOW, order_intent


def test_order_intent_is_risk_bound_and_expiring() -> None:
    intent = order_intent()
    assert intent.risk_decision_id.value == "risk-1"
    assert intent.valid_until > intent.created_at


def test_local_send_never_implies_venue_acceptance() -> None:
    submitted = VenueOrder(
        venue_order_id=None,
        client_order_id=ClientOrderId("client-1"),
        order_intent_id=OrderIntentId("intent-1"),
        venue_id=VenueId("BINANCE"),
        status=VenueOrderStatus.SUBMITTED,
        locally_sent_at=NOW,
        cumulative_filled_quantity=Quantity(amount=Decimal("0"), asset_id=BTC),
    )
    assert submitted.status is VenueOrderStatus.SUBMITTED
    payload = submitted.model_dump(mode="json")
    payload["status"] = VenueOrderStatus.ACCEPTED
    payload["last_venue_update_at"] = (NOW + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="venue evidence"):
        type(submitted).model_validate_json(json.dumps(payload))
