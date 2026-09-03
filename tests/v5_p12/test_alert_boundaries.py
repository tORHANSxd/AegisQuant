"""V5-P12 external-alert and non-Live boundary tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from aegisquant.canary_readiness import (
    AlertDestinationKind,
    ExternalAlertDeliveryReceipt,
    create_external_alert_delivery_receipt,
)
from aegisquant.domain.evidence import EvidenceTier
from tests.v5_p11.helpers import START, digest
from tests.v5_p12.helpers import make_alert_receipt, make_complete_fixture


def test_loopback_delivery_is_explicitly_development_only() -> None:
    receipt = make_alert_receipt(external=False)
    assert receipt.evidence_tier is EvidenceTier.DEVELOPMENT
    assert receipt.loopback_destination is True
    assert receipt.durable_receipt_persisted is False
    assert receipt.immutable_audit_anchor_present is False


def test_external_delivery_requires_testnet_forward_tier() -> None:
    with pytest.raises(ValidationError, match="TESTNET_FORWARD"):
        create_external_alert_delivery_receipt(
            evidence_tier=EvidenceTier.DEVELOPMENT,
            destination_kind=AlertDestinationKind.EXTERNAL_NON_LOOPBACK,
            candidate_id="candidate-1",
            strategy_id="strategy-1",
            run_id="run-1",
            account_scope_id="scope-1",
            alert_event_id="alert-1",
            correlation_id="correlation-1",
            destination_id="external-receiver",
            attempted_at=START,
            acknowledged_at=START + timedelta(seconds=1),
            attempted_channel_count=1,
            delivered_channel_count=1,
            https_transport=True,
            loopback_destination=False,
            http_status_code=200,
            payload_sha256=digest("payload"),
            acknowledgment_sha256=digest("ack"),
            remote_acknowledged=True,
            durable_receipt_persisted=True,
            immutable_audit_anchor_present=True,
        )


def test_partial_delivery_cannot_claim_remote_acknowledgment() -> None:
    receipt = make_alert_receipt(external=True)
    with pytest.raises(ValidationError, match="ACKNOWLEDGMENT-INCONSISTENT"):
        ExternalAlertDeliveryReceipt.model_validate(
            {
                **receipt.model_dump(mode="python"),
                "attempted_channel_count": 2,
            }
        )


def test_readiness_models_have_no_live_unlock_field_that_can_be_enabled() -> None:
    fixture = make_complete_fixture()
    assessment_fields = type(fixture.bundle).model_fields
    assert "live_account_connected" not in assessment_fields
    assert fixture.testnet.live_account_connected is False
    assert fixture.testnet.live_domain_used is False
    assert fixture.testnet.withdrawals_enabled is False
    assert fixture.risk.authorization_scope == "TESTNET_ONLY"
    assert fixture.risk.live_order_authorized is False
    assert fixture.risk.manual_live_unlock_received is False
