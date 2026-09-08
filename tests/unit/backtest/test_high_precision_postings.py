from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aegisquant.backtest.models import PnLAttributionPoint
from aegisquant.domain.accounting import JournalEntry, LedgerPosting, PostingSide
from aegisquant.domain.identifiers import AccountId, AssetId, LedgerEntryId, PostingId
from aegisquant.domain.values import Money, exact_decimal_sum


def entry(last_credit: str) -> JournalEntry:
    values = ("1", "1e-30", "1", last_credit)
    sides = (PostingSide.DEBIT, PostingSide.DEBIT, PostingSide.CREDIT, PostingSide.CREDIT)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return JournalEntry(
        journal_entry_id=LedgerEntryId("precision"),
        event_time=now,
        recorded_at=now,
        description="exact high precision posted amount check",
        postings=tuple(
            LedgerPosting(
                posting_id=PostingId(f"p{i}"),
                account_id=AccountId(f"a{i}"),
                side=side,
                amount=Money(amount=Decimal(value), asset_id=AssetId("USDT")),
                memo="precision",
            )
            for i, (side, value) in enumerate(zip(sides, values, strict=True))
        ),
    )


def test_balanced_small_terms_are_not_lost_by_decimal_accumulation() -> None:
    assert len(entry("1e-30").postings) == 4


def test_even_sub_currency_unit_unbalanced_postings_are_rejected() -> None:
    with pytest.raises(ValueError, match="UNBALANCED"):
        entry("1e-29")


def test_attribution_exactly_inverts_high_precision_cost_sum() -> None:
    net, fee, slippage = (
        Decimal("1234.123456789123456789123456"),
        Decimal("0.123456789123456789"),
        Decimal("1e-30"),
    )
    gross = exact_decimal_sum((net, fee, slippage))
    point = PnLAttributionPoint(
        time=datetime(2026, 1, 1, tzinfo=UTC),
        gross_trading_pnl=gross,
        trading_fees=fee,
        slippage_cost=slippage,
        spread_cost=Decimal("0"),
        impact_cost=Decimal("0"),
        funding=Decimal("0"),
        borrow_interest=Decimal("0"),
        net_pnl=net,
    )
    assert point.net_pnl == net
