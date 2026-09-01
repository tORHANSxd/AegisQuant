from __future__ import annotations

from decimal import Decimal

from aegisquant.research.models.uncertainty import (
    AbstainInputs,
    AbstainPolicy,
    AbstainReason,
    conformal_interval,
    decide_abstention,
    fit_split_conformal,
)


def test_split_conformal_is_ordered_and_abstain_reasons_are_explicit() -> None:
    calibration = fit_split_conformal(
        predictions=(Decimal("0"), Decimal("1"), Decimal("2"), Decimal("3")),
        realized=(Decimal("0.1"), Decimal("0.8"), Decimal("2.4"), Decimal("2.9")),
        alpha=Decimal("0.1"),
    )
    interval = conformal_interval(Decimal("1"), calibration)
    assert interval.lower <= interval.median <= interval.upper
    policy = AbstainPolicy(
        minimum_absolute_edge=Decimal("0.01"),
        maximum_uncertainty=Decimal("0.1"),
        maximum_disagreement=Decimal("0.1"),
        maximum_staleness_seconds=Decimal("60"),
        maximum_cost=Decimal("0.005"),
        maximum_ood_score=Decimal("2"),
    )
    decision = decide_abstention(
        policy=policy,
        inputs=AbstainInputs(
            expected_edge=Decimal("0"),
            uncertainty=Decimal("0.2"),
            disagreement=Decimal("0.2"),
            staleness_seconds=Decimal("61"),
            expected_cost=Decimal("0.006"),
            ood_score=Decimal("3"),
            risk_blocked=True,
        ),
    )
    assert decision.should_abstain is True
    assert set(decision.reasons) == set(AbstainReason)
