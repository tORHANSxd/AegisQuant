"""Point-in-time legality and complete P06 stress-scenario coverage."""

from datetime import timedelta
from decimal import Decimal

import pytest

from aegisquant.backtest.models import (
    FundingEvent,
    StressScenario,
    StressType,
)
from aegisquant.backtest.rules import HistoricalRuleBook
from aegisquant.backtest.stress import apply_stress
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import (
    BacktestEventId,
    InstrumentRuleId,
    StressScenarioId,
)
from tests.p06.helpers import (
    BTC,
    NOW,
    PERP_ID,
    USDT,
    VENUE,
    bars,
    l2_book,
    order,
    policy,
)


def test_historical_rule_change_alters_legality_at_exact_effective_time() -> None:
    base = policy().instrument_rules[0]
    cutoff = NOW + timedelta(seconds=2)
    earlier = base.model_copy(
        update={
            "instrument_rule_id": InstrumentRuleId("rule-before-halt"),
            "version": "rule-before-halt",
            "effective_to": cutoff,
            "trading_enabled": True,
        }
    )
    later = base.model_copy(
        update={
            "instrument_rule_id": InstrumentRuleId("rule-after-halt"),
            "version": "rule-after-halt",
            "effective_from": cutoff,
            "effective_to": None,
            "trading_enabled": False,
        }
    )
    book = HistoricalRuleBook((earlier, later))
    before = order(
        sequence=1,
        side=OrderSide.BUY,
        submitted_at=cutoff - timedelta(microseconds=1),
    )
    after = order(
        sequence=2,
        side=OrderSide.BUY,
        submitted_at=cutoff,
    )

    assert book.validate_order(before, reference_price=Decimal("100")).valid is True
    decision = book.validate_order(after, reference_price=Decimal("100"))
    assert decision.valid is False
    assert decision.rejection_code == "AQ-BACKTEST-RULE-TRADING-DISABLED"
    assert decision.rule.version == "rule-after-halt"


def test_historical_rule_gap_is_rejected_instead_of_silently_approximated() -> None:
    base = policy().instrument_rules[0]
    earlier = base.model_copy(update={"effective_to": NOW})
    later = base.model_copy(
        update={
            "instrument_rule_id": InstrumentRuleId("rule-after-gap"),
            "effective_from": NOW + timedelta(seconds=1),
        }
    )
    with pytest.raises(ValueError, match="AQ-BACKTEST-RULE-GAP"):
        HistoricalRuleBook((earlier, later))


@pytest.mark.parametrize("stress_type", tuple(StressType))
def test_every_required_stress_scenario_has_an_explicit_effect(stress_type: StressType) -> None:
    selected = policy()
    delayed_bar = bars()[1].model_copy(
        update={"available_time": bars()[1].event_time + timedelta(milliseconds=1)}
    )
    market_events = (delayed_bar, l2_book(sequence=2))
    funding_event = FundingEvent(
        event_id=BacktestEventId("funding-stress"),
        instrument_id=PERP_ID,
        venue_id=VENUE,
        base_asset_id=BTC,
        quote_asset_id=USDT,
        event_time=NOW + timedelta(seconds=1),
        available_time=NOW + timedelta(seconds=1),
        funding_rate=Decimal("0.0001"),
        mark_price=Decimal("100"),
    )
    multiplier = (
        Decimal("0.8")
        if stress_type
        in {
            StressType.CORRELATION_SHOCK,
            StressType.LIQUIDITY_FACTOR,
            StressType.STABLECOIN_DEPEG,
        }
        else Decimal("2")
    )
    scenario = StressScenario(
        stress_scenario_id=StressScenarioId(f"stress-{stress_type.value.lower()}"),
        stress_type=stress_type,
        multiplier=multiplier,
        starts_at=NOW,
        ends_at=NOW + timedelta(seconds=4),
        source="P06 deterministic stress fixture",
    )
    application = apply_stress(
        scenario=scenario,
        market_events=market_events,
        funding_events=(funding_event,),
        cost_schedules=selected.cost_schedules,
        latency_policy=selected.latency_policy,
    )

    changed = any(
        (
            application.market_events != market_events,
            application.funding_events != (funding_event,),
            application.cost_schedules != selected.cost_schedules,
            application.latency_policy != selected.latency_policy,
            bool(application.faults),
            not application.model_available,
            not application.strategy_enabled,
            application.correlation_target is not None,
            application.historical_replay_required,
        )
    )
    assert application.scenario == scenario
    assert changed is True
