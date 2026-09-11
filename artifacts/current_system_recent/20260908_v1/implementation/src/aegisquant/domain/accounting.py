"""Double-entry schema and invariants without a complete accounting engine."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import (
    AccountId,
    InstrumentId,
    LedgerEntryId,
    PositionLotId,
    PostingId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import Money, Price, Quantity, exact_decimal_sum


class PostingSide(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LotSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class LedgerPosting(DomainModel):
    posting_id: PostingId
    account_id: AccountId
    side: PostingSide
    amount: Money
    memo: str

    @model_validator(mode="after")
    def amount_is_positive(self) -> LedgerPosting:
        if self.amount.amount <= 0:
            raise ValueError("ledger posting amount must be positive")
        return self


class JournalEntry(DomainModel):
    journal_entry_id: LedgerEntryId
    event_time: UtcDateTime
    recorded_at: UtcDateTime
    description: str
    postings: tuple[LedgerPosting, ...]
    reconciliation_adjustment: bool = False
    supersedes_entry_id: LedgerEntryId | None = None

    @model_validator(mode="after")
    def postings_balance_by_asset(self) -> JournalEntry:
        if len(self.postings) < 2:
            raise ValueError("journal entry requires at least two postings")
        posting_ids = {posting.posting_id for posting in self.postings}
        if len(posting_ids) != len(self.postings):
            raise ValueError("journal posting ids must be unique")
        balances: dict[str, list[Decimal]] = defaultdict(list)
        for posting in self.postings:
            amount = posting.amount.amount
            balances[str(posting.amount.asset_id)].append(
                amount if posting.side is PostingSide.DEBIT else amount.copy_negate()
            )
        if any(exact_decimal_sum(balance) != 0 for balance in balances.values()):
            raise ValueError("AQ-LEDGER-UNBALANCED: debits and credits must balance per asset")
        if self.recorded_at < self.event_time:
            raise ValueError("journal entry cannot be recorded before its event")
        if self.reconciliation_adjustment != (self.supersedes_entry_id is not None):
            raise ValueError("reconciliation adjustment must explicitly reference prior history")
        return self


class PositionLot(DomainModel):
    position_lot_id: PositionLotId
    account_id: AccountId
    instrument_id: InstrumentId
    side: LotSide
    opened_quantity: Quantity
    remaining_quantity: Quantity
    entry_price: Price
    opening_fees: Money
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_lot(self) -> PositionLot:
        if self.opened_quantity.amount <= 0:
            raise ValueError("position lot opened quantity must be positive")
        if self.remaining_quantity.amount < 0:
            raise ValueError("position lot remaining quantity cannot be negative")
        if self.remaining_quantity.amount > self.opened_quantity.amount:
            raise ValueError("position lot remaining quantity cannot exceed opened quantity")
        if self.remaining_quantity.asset_id != self.opened_quantity.asset_id:
            raise ValueError("position lot quantity units must agree")
        is_closed = self.remaining_quantity.amount == 0
        if is_closed != (self.closed_at is not None):
            raise ValueError("closed lot requires zero remaining quantity and closed_at")
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("position lot close cannot precede open")
        return self
