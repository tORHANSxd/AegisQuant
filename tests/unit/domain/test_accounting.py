"""Journal and position schema invariant tests."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.domain.accounting import JournalEntry, LedgerPosting, PostingSide
from aegisquant.domain.identifiers import AccountId, LedgerEntryId, PostingId
from tests.factories import NOW, balanced_journal, money


def test_balanced_journal_is_accepted() -> None:
    journal = balanced_journal("25.50")
    assert len(journal.postings) == 2


def test_unbalanced_journal_is_rejected_per_asset() -> None:
    debit = LedgerPosting(
        posting_id=PostingId("debit"),
        account_id=AccountId("cash"),
        side=PostingSide.DEBIT,
        amount=money("10"),
        memo="debit",
    )
    credit = LedgerPosting(
        posting_id=PostingId("credit"),
        account_id=AccountId("clearing"),
        side=PostingSide.CREDIT,
        amount=money("9"),
        memo="credit",
    )
    with pytest.raises(ValidationError, match="AQ-LEDGER-UNBALANCED"):
        JournalEntry(
            journal_entry_id=LedgerEntryId("entry"),
            event_time=NOW,
            recorded_at=NOW,
            description="unbalanced",
            postings=(debit, credit),
        )
    assert debit.amount.amount - credit.amount.amount == Decimal("1")
