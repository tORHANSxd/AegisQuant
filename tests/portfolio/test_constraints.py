"""Portfolio grouping, turnover, impact, and capacity hard constraints."""

from __future__ import annotations

from decimal import Decimal

from aegisquant.portfolio.models import ExposureDimension
from tests.p11_helpers import BTC, ETH, construction_policy, proposal, signal


def test_all_required_exposure_dimensions_are_policy_controlled() -> None:
    assert {item.dimension for item in construction_policy().exposure_constraints} == set(
        ExposureDimension
    )


def test_capacity_impact_turnover_and_group_limits_only_reduce_targets() -> None:
    constrained = (
        signal(
            asset=BTC,
            instrument="BTC-USDT-PERP",
            raw_score=Decimal("1"),
            confidence=Decimal("1"),
            adv=Decimal("10000"),
            impact_bps=Decimal("100"),
        ),
        signal(
            asset=ETH,
            instrument="ETH-USDT-PERP",
            raw_score=Decimal("-1"),
            confidence=Decimal("1"),
            adv=Decimal("10000"),
            impact_bps=Decimal("100"),
        ),
    )
    result = proposal(custom_signals=constrained)
    assert result.turnover <= construction_policy().maximum_turnover
    assert all(abs(leg.delta_weight) <= leg.capacity_weight for leg in result.legs)
    assert all(
        leg.estimated_impact_bps <= construction_policy().maximum_impact_bps for leg in result.legs
    )
    assert sum(abs(leg.target_weight) for leg in result.legs) <= Decimal("0.45")
    assert any("AQ-PORTFOLIO-CAPACITY-CONSTRAINT" in leg.constraint_reasons for leg in result.legs)


def test_turnover_projection_does_not_overshoot_by_decimal_rounding() -> None:
    result = proposal(
        custom_signals=(
            signal(
                asset=BTC,
                instrument="BTC-USDT-PERP",
                raw_score=Decimal("0.439"),
                confidence=Decimal("0.360"),
                adv=Decimal("344017"),
                impact_bps=Decimal("79.99"),
            ),
            signal(
                asset=ETH,
                instrument="ETH-USDT-PERP",
                raw_score=Decimal("0.439"),
                confidence=Decimal("0.804"),
                adv=Decimal("344017"),
                impact_bps=Decimal("79.99"),
            ),
        )
    )

    assert result.turnover <= construction_policy().maximum_turnover
