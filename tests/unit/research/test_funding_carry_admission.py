from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.research.models.funding_forecast import FundingObservation, forecast_funding
from aegisquant.research.strategies.funding_basis_carry import (
    CarryAdmissionEvidence,
    CarryCosts,
    evaluate_carry,
)


def test_funding_only_uses_settled_known_observations_and_missing_evidence_blocks_entry() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    observations = tuple(
        FundingObservation(
            settlement_time=now - timedelta(hours=8 * i + 1),
            available_time=now - timedelta(hours=8 * i),
            rate=Decimal("0.01"),
            calendar_version="synthetic-8h",
        )
        for i in range(21)
    )
    forecast = forecast_funding(observations, as_of=now, calendar_version="synthetic-8h")
    costs = CarryCosts(
        spot_entry_exit=Decimal("0.0028"),
        perp_entry_exit=Decimal("0.0028"),
        borrow_financing=Decimal("0"),
        legging=Decimal("0.0002"),
        capital_charge=Decimal("0.0001"),
        tail_risk_buffer=Decimal("0.001"),
        uncertainty_buffer=Decimal("0.0002"),
    )
    blocked = evaluate_carry(
        forecast=forecast,
        costs=costs,
        evidence=CarryAdmissionEvidence(evidence_reference="unverified"),
        expected_basis_convergence=Decimal("0"),
        decision_time=now,
    )
    assert blocked.expected_net_carry > blocked.entry_hurdle
    assert blocked.action == "NO_TRADE"
    assert not blocked.allow_combination_with_trend
    with pytest.raises(ValueError, match="future"):
        forecast_funding(
            observations, as_of=now - timedelta(hours=1), calendar_version="synthetic-8h"
        )


def test_negative_funding_and_basis_expansion_exit_existing_carry() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    observations = tuple(
        FundingObservation(
            settlement_time=now - timedelta(hours=8 * i + 1),
            available_time=now - timedelta(hours=8 * i),
            rate=Decimal("-0.001"),
            calendar_version="v1",
        )
        for i in range(21)
    )
    costs = CarryCosts.model_validate({name: Decimal("0.001") for name in CarryCosts.model_fields})
    result = evaluate_carry(
        forecast=forecast_funding(observations, as_of=now, calendar_version="v1"),
        costs=costs,
        evidence=CarryAdmissionEvidence(evidence_reference="missing"),
        expected_basis_convergence=Decimal("0"),
        decision_time=now,
        holding=True,
        basis_expansion=Decimal("0.03"),
    )
    assert result.action == "EXIT_AND_FLATTEN"
    assert "FUNDING_REVERSAL" in result.reasons and "BASIS_EXPANSION_RISK" in result.reasons
