"""Property checks for runtime event idempotency and bounded fill conservation."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from aegisquant.runtime.models import RuntimeMode
from aegisquant.runtime.paper import PaperEngine
from tests.p12_helpers import command
from tests.p13_helpers import market, paper_policy


@given(
    st.integers(min_value=1, max_value=1000),
    st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("4"),
        places=3,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_duplicate_market_event_never_creates_a_second_fill(
    sequence: int, available: Decimal
) -> None:
    observation = market(
        event_id=f"property-market-{sequence}",
        sequence=sequence,
        ask_quantity=available,
    )
    engine = PaperEngine(mode=RuntimeMode.PAPER, policy=paper_policy())
    engine.submit(command())
    first = engine.process(observation)
    second = engine.process(observation)
    assert second == ()
    assert len(engine.fills) == len(first)
    assert sum((item.quantity.amount for item in engine.fills), start=Decimal("0")) <= Decimal("1")


@given(st.integers(min_value=1, max_value=12))
def test_replayed_economic_command_remains_one_order(replay_count: int) -> None:
    engine = PaperEngine(mode=RuntimeMode.PAPER, policy=paper_policy())
    for _ in range(replay_count):
        engine.submit(command())
    assert engine.economic_order_count == 1
    assert len(engine.orders) == 1
