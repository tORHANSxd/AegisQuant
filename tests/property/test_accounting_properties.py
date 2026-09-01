"""Property tests for accounting balance, FIFO replay, and idempotency."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from aegisquant.domain.accounting import PostingSide
from aegisquant.domain.execution import OrderSide
from tests.p05.helpers import engine, fill, linear_instrument


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from((OrderSide.BUY, OrderSide.SELL)),
            st.integers(min_value=1, max_value=5),
            st.integers(min_value=50, max_value=150),
        ),
        min_size=1,
        max_size=30,
    )
)
def test_random_fill_sequences_are_balanced_idempotent_and_rebuildable(
    events: list[tuple[OrderSide, int, int]],
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    spec = linear_instrument()
    ledger = engine(project_root)
    for sequence, (side, quantity, price) in enumerate(events, start=1):
        event = fill(
            spec,
            sequence=sequence,
            side=side,
            quantity=str(quantity),
            price=str(price),
        )
        first = ledger.process_fill(event, spec)
        replay = ledger.process_fill(event, spec)
        assert first.inserted is True
        assert replay.inserted is False
    for record in ledger.records:
        by_asset: dict[str, Decimal] = {}
        for posting in record.journal_entry.postings:
            sign = Decimal("1") if posting.side is PostingSide.DEBIT else Decimal("-1")
            asset = str(posting.amount.asset_id)
            by_asset[asset] = by_asset.get(asset, Decimal("0")) + sign * posting.amount.amount
        assert set(by_asset.values()) == {Decimal("0")}
    assert ledger.rebuild().state_digest() == ledger.state_digest()
