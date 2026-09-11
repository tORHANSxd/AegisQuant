"""Deterministic double-entry ledger with FIFO lots and native-asset balances."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aegisquant.accounting.models import (
    AccountBalance,
    AccountDefinition,
    AccountingInstrument,
    AccountRole,
    AccountType,
    AppliedFill,
    CashflowDirection,
    CashflowEvent,
    CashflowType,
    ChartOfAccounts,
    EntryTemplate,
    EquitySnapshot,
    FxRate,
    LedgerRecord,
    LedgerStateDigest,
    LotAction,
    LotChange,
    LotValuation,
    NormalBalance,
    PnLBreakdown,
    PositionLotState,
    QuantityUnit,
    SettlementEvent,
    ValuationQuote,
    ValuationSnapshot,
)
from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.market import ContractForm, InstrumentType
from aegisquant.domain.accounting import JournalEntry, LedgerPosting, LotSide, PostingSide
from aegisquant.domain.execution import Fill
from aegisquant.domain.identifiers import (
    AccountId,
    AccountSnapshotId,
    AssetId,
    EntryTemplateId,
    IdempotencyKey,
    InstrumentId,
    LedgerEntryId,
    LedgerSnapshotId,
    PositionLotId,
    PostingId,
    ValuationSnapshotId,
)
from aegisquant.domain.time import UtcDateTime, ensure_utc
from aegisquant.domain.values import Money, canonical_result, exact_decimal_sum

ZERO_HASH: Final = "0" * 64


class AccountingPolicy(BaseModel):
    """Versioned policy loaded from the repository-owned accounting config."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_version: str
    chart_version: str
    template_version: str
    lot_policy: str
    valuation_priority: tuple[str, ...]
    mutation_score_threshold: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    spot_fee_policy: Literal["SPOT_NATIVE_FEES_V2"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def supported_policy(self) -> AccountingPolicy:
        if self.lot_policy != "FIFO":
            raise ValueError("P05 authoritative lot policy must be FIFO")
        if self.valuation_priority != ("MARK", "MID", "LAST", "INDEX"):
            raise ValueError("valuation priority differs from ADR-0009")
        if self.spot_fee_policy is not None and not self.policy_version.endswith(":native-fees-v2"):
            raise ValueError("native fee accounting requires a distinct versioned policy")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> AccountingPolicy:
        loaded = cast(object, yaml.safe_load(path.read_text(encoding="utf-8")))
        if not isinstance(loaded, dict):
            raise ValueError("accounting policy YAML must contain a mapping")
        raw = cast(dict[str, object], loaded)
        priority = raw.get("valuation_priority")
        threshold = raw.get("mutation_score_threshold")
        if not isinstance(priority, list):
            raise ValueError("valuation_priority must be a YAML sequence")
        priority_values: list[str] = []
        for item in cast(list[object], priority):
            if not isinstance(item, str):
                raise ValueError("valuation_priority values must be strings")
            priority_values.append(item)
        if not isinstance(threshold, str):
            raise ValueError("mutation_score_threshold must be an exact decimal string")
        raw["valuation_priority"] = tuple(priority_values)
        raw["mutation_score_threshold"] = Decimal(threshold)
        return cls.model_validate(raw)


ROLE_METADATA: Final[dict[AccountRole, tuple[AccountType, NormalBalance, bool]]] = {
    AccountRole.CASH: (AccountType.ASSET, NormalBalance.DEBIT, True),
    AccountRole.MARGIN_COLLATERAL: (AccountType.ASSET, NormalBalance.DEBIT, True),
    AccountRole.POSITION_COST: (AccountType.MEMO, NormalBalance.DEBIT, False),
    AccountRole.POSITION_CLEARING: (AccountType.MEMO, NormalBalance.CREDIT, False),
    AccountRole.INVENTORY_CLEARING: (AccountType.MEMO, NormalBalance.CREDIT, False),
    AccountRole.BORROWED_ASSET: (AccountType.LIABILITY, NormalBalance.CREDIT, True),
    AccountRole.ACCRUED_INTEREST: (AccountType.LIABILITY, NormalBalance.CREDIT, True),
    AccountRole.OWNER_CAPITAL: (AccountType.EQUITY, NormalBalance.CREDIT, False),
    AccountRole.TRADING_REALIZED_PNL: (AccountType.INCOME, NormalBalance.CREDIT, False),
    AccountRole.TRADING_LOSS: (AccountType.EXPENSE, NormalBalance.DEBIT, False),
    AccountRole.FUNDING_INCOME: (AccountType.INCOME, NormalBalance.CREDIT, False),
    AccountRole.FUNDING_EXPENSE: (AccountType.EXPENSE, NormalBalance.DEBIT, False),
    AccountRole.TRADING_FEE: (AccountType.EXPENSE, NormalBalance.DEBIT, False),
    AccountRole.TRADING_FEE_REBATE: (AccountType.INCOME, NormalBalance.CREDIT, False),
    AccountRole.BORROW_INTEREST: (AccountType.EXPENSE, NormalBalance.DEBIT, False),
    AccountRole.TRANSFER_FEE: (AccountType.EXPENSE, NormalBalance.DEBIT, False),
    AccountRole.RECONCILIATION_RESERVE: (AccountType.EQUITY, NormalBalance.CREDIT, False),
}


class ChartRuntime:
    """Materialize deterministic scoped accounts from the versioned chart roles."""

    def __init__(self, *, version: str, effective_from: datetime) -> None:
        self.version = version
        self.effective_from = ensure_utc(effective_from)
        self._definitions: dict[AccountId, AccountDefinition] = {}

    def account(self, role: AccountRole, *, venue: str, subject: str) -> AccountDefinition:
        account_id = AccountId(f"{role.value.lower()}:{venue}:{subject}")
        existing = self._definitions.get(account_id)
        if existing is not None:
            return existing
        account_type, normal_balance, economic = ROLE_METADATA[role]
        definition = AccountDefinition(
            account_id=account_id,
            role=role,
            account_type=account_type,
            normal_balance=normal_balance,
            venue=venue,
            subject=subject,
            economic_balance=economic,
            version=self.version,
        )
        self._definitions[account_id] = definition
        return definition

    def definition(self, account_id: AccountId) -> AccountDefinition:
        try:
            return self._definitions[account_id]
        except KeyError as error:
            raise KeyError(f"unknown ledger account: {account_id}") from error

    def snapshot(self) -> ChartOfAccounts:
        return ChartOfAccounts(
            version=self.version,
            effective_from=self.effective_from,
            definitions=tuple(
                sorted(self._definitions.values(), key=lambda item: str(item.account_id))
            ),
        )


TEMPLATE_ROLES: Final[dict[str, tuple[AccountRole, ...]]] = {
    "SPOT_FILL": (
        AccountRole.CASH,
        AccountRole.INVENTORY_CLEARING,
        AccountRole.POSITION_COST,
    ),
    "DERIVATIVE_FILL": (
        AccountRole.POSITION_COST,
        AccountRole.POSITION_CLEARING,
    ),
    "CONTRACT_SETTLEMENT": (
        AccountRole.POSITION_COST,
        AccountRole.POSITION_CLEARING,
    ),
    "FUNDING_INCOME": (AccountRole.CASH, AccountRole.FUNDING_INCOME),
    "FUNDING_EXPENSE": (AccountRole.CASH, AccountRole.FUNDING_EXPENSE),
    "BORROW": (AccountRole.CASH, AccountRole.BORROWED_ASSET),
    "REPAY": (AccountRole.CASH, AccountRole.BORROWED_ASSET),
    "BORROW_INTEREST": (AccountRole.CASH, AccountRole.BORROW_INTEREST),
    "EXTERNAL_TRANSFER": (AccountRole.CASH, AccountRole.OWNER_CAPITAL),
    "TRANSFER_FEE": (AccountRole.CASH, AccountRole.TRANSFER_FEE),
    "RECONCILIATION_ADJUSTMENT": (
        AccountRole.CASH,
        AccountRole.RECONCILIATION_RESERVE,
    ),
}


def entry_templates(*, version: str, effective_from: datetime) -> tuple[EntryTemplate, ...]:
    return tuple(
        EntryTemplate(
            entry_template_id=EntryTemplateId(name.lower().replace("_", "-")),
            version=version,
            event_type=name,
            required_roles=roles,
            effective_from=ensure_utc(effective_from),
        )
        for name, roles in sorted(TEMPLATE_ROLES.items())
    )


@dataclass(frozen=True, slots=True)
class _PostingDraft:
    account: AccountDefinition
    side: PostingSide
    amount: Decimal
    asset_id: AssetId
    memo: str


@dataclass(frozen=True, slots=True)
class FillCommand:
    fill: Fill
    instrument: AccountingInstrument


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    record: LedgerRecord
    inserted: bool


@dataclass(frozen=True, slots=True)
class FillApplyOutcome:
    applied_fill: AppliedFill
    inserted: bool


LedgerCommand = FillCommand | CashflowEvent | SettlementEvent


def _side_sign(side: LotSide) -> Decimal:
    return Decimal("1") if side is LotSide.LONG else Decimal("-1")


def calculate_contract_pnl(
    *,
    side: LotSide,
    quantity: Decimal,
    entry_price: Decimal,
    exit_price: Decimal,
    instrument: AccountingInstrument,
) -> Money:
    """Calculate exact native-settlement PnL for spot, linear, and inverse exposure."""
    if quantity <= 0 or entry_price <= 0 or exit_price <= 0:
        raise ValueError("PnL quantity and prices must be positive")
    signed_quantity = _side_sign(side) * quantity
    if instrument.contract_form is ContractForm.INVERSE:
        amount = (
            signed_quantity
            * instrument.contract_multiplier
            * (Decimal("1") / entry_price - Decimal("1") / exit_price)
        )
    else:
        amount = signed_quantity * instrument.contract_multiplier * (exit_price - entry_price)
    return Money(amount=canonical_result(amount), asset_id=instrument.settlement_asset_id)


def _position_basis(
    *, quantity: Decimal, price: Decimal, instrument: AccountingInstrument
) -> Decimal:
    if quantity <= 0 or price <= 0:
        raise ValueError("position basis quantity and price must be positive")
    if instrument.contract_form is ContractForm.INVERSE:
        return quantity * instrument.contract_multiplier / price
    return quantity * instrument.contract_multiplier * price


class LedgerEngine:
    """Append-only accounting engine whose state is fully rebuildable from commands."""

    def __init__(self, *, policy: AccountingPolicy, effective_from: datetime) -> None:
        self.policy = policy
        self.chart = ChartRuntime(version=policy.chart_version, effective_from=effective_from)
        self.templates = {
            template.event_type: template
            for template in entry_templates(
                version=policy.template_version, effective_from=effective_from
            )
        }
        self._records: list[LedgerRecord] = []
        self._balances: dict[tuple[AccountId, AssetId], Decimal] = {}
        self._lots: dict[InstrumentId, list[PositionLotState]] = {}
        self._instrument_by_id: dict[InstrumentId, AccountingInstrument] = {}
        self._fill_by_id: dict[str, AppliedFill] = {}
        self._record_by_key: dict[IdempotencyKey, LedgerRecord] = {}
        self._command_hash_by_key: dict[IdempotencyKey, str] = {}
        self._command_hash_by_fill: dict[str, str] = {}
        self._commands: list[LedgerCommand] = []

    @property
    def records(self) -> tuple[LedgerRecord, ...]:
        return tuple(self._records)

    @property
    def commands(self) -> tuple[LedgerCommand, ...]:
        return tuple(self._commands)

    def open_lots(self, instrument_id: InstrumentId | None = None) -> tuple[PositionLotState, ...]:
        lots = (
            self._lots.get(instrument_id, [])
            if instrument_id is not None
            else [lot for values in self._lots.values() for lot in values]
        )
        return tuple(sorted(lots, key=lambda item: (item.opened_at, str(item.position_lot_id))))

    def _account(self, role: AccountRole, *, venue: str, subject: str) -> AccountDefinition:
        return self.chart.account(role, venue=venue, subject=subject)

    def _pair(
        self,
        drafts: list[_PostingDraft],
        *,
        debit: AccountDefinition,
        credit: AccountDefinition,
        amount: Decimal,
        asset_id: AssetId,
        memo: str,
    ) -> None:
        amount = canonical_result(amount)
        if amount <= 0:
            raise ValueError("ledger pair amount must be positive")
        drafts.extend(
            (
                _PostingDraft(debit, PostingSide.DEBIT, amount, asset_id, memo),
                _PostingDraft(credit, PostingSide.CREDIT, amount, asset_id, memo),
            )
        )

    def _fee_postings(self, drafts: list[_PostingDraft], fill: Fill, venue: str) -> None:
        fee = fill.fee.amount
        if fee == 0:
            return
        cash = self._account(AccountRole.CASH, venue=venue, subject=str(fill.fee.asset_id))
        if fee > 0:
            expense = self._account(
                AccountRole.TRADING_FEE, venue=venue, subject=str(fill.fee.asset_id)
            )
            self._pair(
                drafts,
                debit=expense,
                credit=cash,
                amount=fee,
                asset_id=fill.fee.asset_id,
                memo=f"trading fee for {fill.fill_id}",
            )
        else:
            income = self._account(
                AccountRole.TRADING_FEE_REBATE,
                venue=venue,
                subject=str(fill.fee.asset_id),
            )
            self._pair(
                drafts,
                debit=cash,
                credit=income,
                amount=-fee,
                asset_id=fill.fee.asset_id,
                memo=f"trading fee rebate for {fill.fill_id}",
            )

    def _validate_native_spot_fee(self, fill: Fill, instrument: AccountingInstrument) -> None:
        """V2 is funded long/flat spot; validate before any lot/chart mutation."""
        if any(lot.side is LotSide.SHORT for lot in self.open_lots(instrument.instrument_id)):
            raise ValueError("AQ-LEDGER-NATIVE-FEE-REQUIRES-LONG-FLAT-SPOT")
        balances: dict[AssetId, Decimal] = {}
        for balance in self.native_balances():
            definition = self.chart.definition(balance.account_id)
            if definition.role is AccountRole.CASH and definition.venue == instrument.venue:
                balances[balance.asset_id] = (
                    balances.get(balance.asset_id, Decimal("0")) + balance.amount
                )
        base_quantity = fill.quantity.amount * instrument.contract_multiplier
        notional = base_quantity * fill.price.amount
        buy = fill.side.value == "BUY"
        deltas = {
            instrument.base_asset_id: base_quantity if buy else -base_quantity,
            instrument.quote_asset_id: -notional if buy else notional,
        }
        deltas[fill.fee.asset_id] = deltas.get(fill.fee.asset_id, Decimal("0")) - max(
            Decimal("0"), fill.fee.amount
        )
        if any(balances.get(asset, Decimal("0")) + delta < 0 for asset, delta in deltas.items()):
            raise ValueError("AQ-LEDGER-NATIVE-FEE-OR-TRADE-BALANCE-INSUFFICIENT")
        if fill.fee.amount != 0:
            for other in self._instrument_by_id.values():
                if (
                    other.instrument_id != instrument.instrument_id
                    and other.base_asset_id == fill.fee.asset_id
                    and self.open_lots(other.instrument_id)
                ):
                    raise ValueError("AQ-LEDGER-THIRD-ASSET-FEE-OPEN-LOT-VALUATION-REQUIRED")
        fee_quantity = (
            max(Decimal("0"), fill.fee.amount) / instrument.contract_multiplier
            if fill.fee.asset_id == instrument.base_asset_id
            else Decimal("0")
        )
        available_lots = sum(
            (lot.remaining_quantity for lot in self.open_lots(instrument.instrument_id)),
            Decimal("0"),
        )
        if available_lots + (fill.quantity.amount if buy else -fill.quantity.amount) < fee_quantity:
            raise ValueError("AQ-LEDGER-NATIVE-BASE-FEE-LOT-INSUFFICIENT")

    def _native_spot_fee_lots(
        self,
        fill: Fill,
        instrument: AccountingInstrument,
        drafts: list[_PostingDraft],
        changes: list[LotChange],
    ) -> Decimal:
        """Dispose positive base fees FIFO; base rebates create a lot at the fill mark."""
        if fill.fee.asset_id != instrument.base_asset_id or fill.fee.amount == 0:
            return Decimal("0")
        quantity = abs(fill.fee.amount) / instrument.contract_multiplier
        cost = self._account(
            AccountRole.POSITION_COST, venue=instrument.venue, subject=str(instrument.instrument_id)
        )
        clearing = self._account(
            AccountRole.POSITION_CLEARING,
            venue=instrument.venue,
            subject=str(instrument.instrument_id),
        )
        if fill.fee.amount > 0:
            remaining, _, consumed = self._consume_fifo(
                fill=fill,
                instrument=instrument,
                incoming_side=LotSide.SHORT,
                quantity=quantity,
                drafts=drafts,
            )
            if remaining != 0:
                raise RuntimeError("prechecked native fee lot changed during consumption")
            changes.extend(consumed)
            basis = sum(
                (
                    change.affected_quantity
                    * instrument.contract_multiplier
                    * change.lot_before.entry_price
                    for change in consumed
                    if change.lot_before is not None
                ),
                Decimal("0"),
            )
            self._pair(
                drafts,
                debit=clearing,
                credit=cost,
                amount=basis,
                asset_id=instrument.quote_asset_id,
                memo=f"release FIFO basis of native fee {fill.fill_id}",
            )
            realized = exact_decimal_sum(
                (
                    quantity * instrument.contract_multiplier * fill.price.amount,
                    basis.copy_negate(),
                )
            )
            if realized != 0:
                pnl_account = self._account(
                    AccountRole.TRADING_REALIZED_PNL if realized > 0 else AccountRole.TRADING_LOSS,
                    venue=instrument.venue,
                    subject=str(instrument.quote_asset_id),
                )
                # The asset pays the fee: use memo clearing, never invent quote cash.
                self._pair(
                    drafts,
                    debit=clearing if realized > 0 else pnl_account,
                    credit=pnl_account if realized > 0 else clearing,
                    amount=abs(realized),
                    asset_id=instrument.quote_asset_id,
                    memo=f"FIFO disposal PnL of native fee {fill.fill_id}",
                )
            return realized
        lot = self._new_lot(
            fill=fill, instrument=instrument, side=LotSide.LONG, quantity=quantity, ordinal=1
        )
        self._lots.setdefault(instrument.instrument_id, []).append(lot)
        changes.append(
            LotChange(
                action=LotAction.OPEN,
                lot_after=lot,
                affected_quantity=quantity,
                realized_pnl=Money(amount=Decimal("0"), asset_id=instrument.quote_asset_id),
            )
        )
        self._pair(
            drafts,
            debit=cost,
            credit=clearing,
            amount=quantity * instrument.contract_multiplier * fill.price.amount,
            asset_id=instrument.quote_asset_id,
            memo=f"basis of native fee rebate {fill.fill_id}",
        )
        return Decimal("0")

    def _realized_postings(
        self,
        drafts: list[_PostingDraft],
        *,
        venue: str,
        pnl: Money,
        memo: str,
    ) -> None:
        if pnl.amount == 0:
            return
        cash = self._account(AccountRole.CASH, venue=venue, subject=str(pnl.asset_id))
        if pnl.amount > 0:
            income = self._account(
                AccountRole.TRADING_REALIZED_PNL,
                venue=venue,
                subject=str(pnl.asset_id),
            )
            self._pair(
                drafts,
                debit=cash,
                credit=income,
                amount=pnl.amount,
                asset_id=pnl.asset_id,
                memo=memo,
            )
        else:
            loss = self._account(AccountRole.TRADING_LOSS, venue=venue, subject=str(pnl.asset_id))
            self._pair(
                drafts,
                debit=loss,
                credit=cash,
                amount=-pnl.amount,
                asset_id=pnl.asset_id,
                memo=memo,
            )

    def _new_lot(
        self,
        *,
        fill: Fill,
        instrument: AccountingInstrument,
        side: LotSide,
        quantity: Decimal,
        ordinal: int,
    ) -> PositionLotState:
        lot_id = PositionLotId(canonical_sha256({"fill_id": str(fill.fill_id), "ordinal": ordinal}))
        position_account = self._account(
            AccountRole.POSITION_COST,
            venue=instrument.venue,
            subject=str(instrument.instrument_id),
        )
        return PositionLotState(
            position_lot_id=lot_id,
            account_id=position_account.account_id,
            instrument_id=instrument.instrument_id,
            side=side,
            quantity_unit=(
                QuantityUnit.BASE_ASSET
                if instrument.instrument_type is InstrumentType.SPOT
                else QuantityUnit.CONTRACT
            ),
            quantity_asset_id=instrument.quantity_asset_id,
            opened_quantity=quantity,
            remaining_quantity=quantity,
            entry_price=fill.price.amount,
            contract_form=instrument.contract_form,
            contract_multiplier=instrument.contract_multiplier,
            settlement_asset_id=instrument.settlement_asset_id,
            opening_fee=Money(
                amount=canonical_result(fill.fee.amount * quantity / fill.quantity.amount),
                asset_id=fill.fee.asset_id,
            ),
            source_fill_id=fill.fill_id,
            opened_at=fill.event_time,
        )

    @staticmethod
    def _updated_lot(
        lot: PositionLotState, *, remaining: Decimal, closed_at: datetime | None
    ) -> PositionLotState:
        return PositionLotState(
            position_lot_id=lot.position_lot_id,
            account_id=lot.account_id,
            instrument_id=lot.instrument_id,
            side=lot.side,
            quantity_unit=lot.quantity_unit,
            quantity_asset_id=lot.quantity_asset_id,
            opened_quantity=lot.opened_quantity,
            remaining_quantity=canonical_result(remaining),
            entry_price=lot.entry_price,
            contract_form=lot.contract_form,
            contract_multiplier=lot.contract_multiplier,
            settlement_asset_id=lot.settlement_asset_id,
            opening_fee=lot.opening_fee,
            source_fill_id=lot.source_fill_id,
            opened_at=lot.opened_at,
            closed_at=closed_at,
        )

    def _consume_fifo(
        self,
        *,
        fill: Fill,
        instrument: AccountingInstrument,
        incoming_side: LotSide,
        quantity: Decimal,
        drafts: list[_PostingDraft],
    ) -> tuple[Decimal, Decimal, list[LotChange]]:
        lots = self._lots.setdefault(instrument.instrument_id, [])
        remaining = quantity
        realized = Decimal("0")
        changes: list[LotChange] = []
        index = 0
        while remaining > 0 and index < len(lots):
            lot = lots[index]
            if lot.side is incoming_side:
                index += 1
                continue
            closed_quantity = min(remaining, lot.remaining_quantity)
            pnl = calculate_contract_pnl(
                side=lot.side,
                quantity=closed_quantity,
                entry_price=lot.entry_price,
                exit_price=fill.price.amount,
                instrument=instrument,
            )
            realized += pnl.amount
            if instrument.instrument_type is not InstrumentType.SPOT:
                basis = _position_basis(
                    quantity=closed_quantity,
                    price=lot.entry_price,
                    instrument=instrument,
                )
                clearing = self._account(
                    AccountRole.POSITION_CLEARING,
                    venue=instrument.venue,
                    subject=str(instrument.instrument_id),
                )
                cost = self._account(
                    AccountRole.POSITION_COST,
                    venue=instrument.venue,
                    subject=str(instrument.instrument_id),
                )
                self._pair(
                    drafts,
                    debit=clearing,
                    credit=cost,
                    amount=basis,
                    asset_id=instrument.settlement_asset_id,
                    memo=f"release FIFO lot {lot.position_lot_id}",
                )
            after_quantity = lot.remaining_quantity - closed_quantity
            after = (
                None
                if after_quantity == 0
                else self._updated_lot(lot, remaining=after_quantity, closed_at=None)
            )
            changes.append(
                LotChange(
                    action=LotAction.CLOSE if after is None else LotAction.REDUCE,
                    lot_before=lot,
                    lot_after=after,
                    affected_quantity=closed_quantity,
                    realized_pnl=pnl,
                )
            )
            if after is None:
                lots.pop(index)
            else:
                lots[index] = after
                index += 1
            remaining -= closed_quantity
        return canonical_result(remaining), canonical_result(realized), changes

    def _spot_fill(
        self, fill: Fill, instrument: AccountingInstrument
    ) -> tuple[list[_PostingDraft], list[LotChange], Money]:
        lots = self._lots.get(instrument.instrument_id, ())
        available = sum(
            (lot.remaining_quantity for lot in lots if lot.side is LotSide.LONG), Decimal("0")
        )
        if any(lot.side is LotSide.SHORT for lot in lots) or (
            fill.side.value == "SELL" and fill.quantity.amount > available
        ):
            return self._borrowed_spot_fill(fill, instrument)
        drafts: list[_PostingDraft] = []
        changes: list[LotChange] = []
        quantity = fill.quantity.amount
        venue = instrument.venue
        cash_base = self._account(
            AccountRole.CASH, venue=venue, subject=str(instrument.base_asset_id)
        )
        cash_quote = self._account(
            AccountRole.CASH, venue=venue, subject=str(instrument.quote_asset_id)
        )
        inventory = self._account(
            AccountRole.INVENTORY_CLEARING,
            venue=venue,
            subject=str(instrument.instrument_id),
        )
        cost_account = self._account(
            AccountRole.POSITION_COST,
            venue=venue,
            subject=str(instrument.instrument_id),
        )
        notional = quantity * instrument.contract_multiplier * fill.price.amount
        if fill.side.value == "BUY":
            self._pair(
                drafts,
                debit=cash_base,
                credit=inventory,
                amount=quantity * instrument.contract_multiplier,
                asset_id=instrument.base_asset_id,
                memo=f"spot asset received for {fill.fill_id}",
            )
            self._pair(
                drafts,
                debit=cost_account,
                credit=cash_quote,
                amount=notional,
                asset_id=instrument.quote_asset_id,
                memo=f"spot FIFO basis for {fill.fill_id}",
            )
            lot = self._new_lot(
                fill=fill,
                instrument=instrument,
                side=LotSide.LONG,
                quantity=quantity,
                ordinal=0,
            )
            self._lots.setdefault(instrument.instrument_id, []).append(lot)
            changes.append(
                LotChange(
                    action=LotAction.OPEN,
                    lot_after=lot,
                    affected_quantity=quantity,
                    realized_pnl=Money(
                        amount=Decimal("0"), asset_id=instrument.settlement_asset_id
                    ),
                )
            )
            realized = Money(amount=Decimal("0"), asset_id=instrument.settlement_asset_id)
        else:
            available = sum(
                (
                    lot.remaining_quantity
                    for lot in self._lots.get(instrument.instrument_id, ())
                    if lot.side is LotSide.LONG
                ),
                Decimal("0"),
            )
            if available < quantity:
                raise ValueError("AQ-LEDGER-SPOT-SHORT-REQUIRES-BORROWED-INVENTORY")
            residual, realized_amount, consumed = self._consume_fifo(
                fill=fill,
                instrument=instrument,
                incoming_side=LotSide.SHORT,
                quantity=quantity,
                drafts=drafts,
            )
            if residual != 0:
                raise RuntimeError("prechecked spot inventory changed during FIFO consumption")
            changes.extend(consumed)
            cost_basis = sum(
                (
                    item.affected_quantity
                    * instrument.contract_multiplier
                    * item.lot_before.entry_price
                    for item in consumed
                    if item.lot_before is not None
                ),
                Decimal("0"),
            )
            proceeds = notional
            # Posted proceeds and FIFO basis are the accounting amounts. Recomputing
            # quantity * (exit - entry) can differ in the last Decimal place.
            realized_amount = exact_decimal_sum((proceeds, cost_basis.copy_negate()))
            self._pair(
                drafts,
                debit=inventory,
                credit=cash_base,
                amount=quantity * instrument.contract_multiplier,
                asset_id=instrument.base_asset_id,
                memo=f"spot asset delivered for {fill.fill_id}",
            )
            if realized_amount >= 0:
                drafts.append(
                    _PostingDraft(
                        cash_quote,
                        PostingSide.DEBIT,
                        proceeds,
                        instrument.quote_asset_id,
                        f"spot proceeds for {fill.fill_id}",
                    )
                )
                drafts.append(
                    _PostingDraft(
                        cost_account,
                        PostingSide.CREDIT,
                        cost_basis,
                        instrument.quote_asset_id,
                        f"release spot basis for {fill.fill_id}",
                    )
                )
                if realized_amount > 0:
                    income = self._account(
                        AccountRole.TRADING_REALIZED_PNL,
                        venue=venue,
                        subject=str(instrument.quote_asset_id),
                    )
                    drafts.append(
                        _PostingDraft(
                            income,
                            PostingSide.CREDIT,
                            realized_amount,
                            instrument.quote_asset_id,
                            f"spot realized PnL for {fill.fill_id}",
                        )
                    )
            else:
                loss = self._account(
                    AccountRole.TRADING_LOSS,
                    venue=venue,
                    subject=str(instrument.quote_asset_id),
                )
                drafts.extend(
                    (
                        _PostingDraft(
                            cash_quote,
                            PostingSide.DEBIT,
                            proceeds,
                            instrument.quote_asset_id,
                            f"spot proceeds for {fill.fill_id}",
                        ),
                        _PostingDraft(
                            loss,
                            PostingSide.DEBIT,
                            realized_amount.copy_negate(),
                            instrument.quote_asset_id,
                            f"spot realized loss for {fill.fill_id}",
                        ),
                        _PostingDraft(
                            cost_account,
                            PostingSide.CREDIT,
                            cost_basis,
                            instrument.quote_asset_id,
                            f"release spot basis for {fill.fill_id}",
                        ),
                    )
                )
            realized = Money(amount=realized_amount, asset_id=instrument.settlement_asset_id)
        self._fee_postings(drafts, fill, venue)
        return drafts, changes, realized

    def _borrowed_spot_fill(
        self, fill: Fill, instrument: AccountingInstrument
    ) -> tuple[list[_PostingDraft], list[LotChange], Money]:
        """FIFO short lots backed by an actual native-asset borrow journal entry."""
        drafts: list[_PostingDraft] = []
        venue = instrument.venue
        base = self._account(AccountRole.CASH, venue=venue, subject=str(instrument.base_asset_id))
        quote = self._account(AccountRole.CASH, venue=venue, subject=str(instrument.quote_asset_id))
        inventory = self._account(
            AccountRole.INVENTORY_CLEARING, venue=venue, subject=str(instrument.instrument_id)
        )
        cost = self._account(
            AccountRole.POSITION_COST, venue=venue, subject=str(instrument.instrument_id)
        )
        buys = fill.side.value == "BUY"
        base_quantity = fill.quantity.amount * instrument.contract_multiplier
        if (
            not buys
            and self._balances.get((base.account_id, instrument.base_asset_id), Decimal("0"))
            < base_quantity
        ):
            raise ValueError("AQ-LEDGER-SPOT-SHORT-REQUIRES-BORROWED-INVENTORY")
        incoming = LotSide.LONG if buys else LotSide.SHORT
        residual, realized_amount, changes = self._consume_fifo(
            fill=fill,
            instrument=instrument,
            incoming_side=incoming,
            quantity=fill.quantity.amount,
            drafts=drafts,
        )
        if residual > 0:
            lot = self._new_lot(
                fill=fill,
                instrument=instrument,
                side=incoming,
                quantity=residual,
                ordinal=len(changes),
            )
            self._lots.setdefault(instrument.instrument_id, []).append(lot)
            changes.append(
                LotChange(
                    action=LotAction.OPEN,
                    lot_after=lot,
                    affected_quantity=residual,
                    realized_pnl=Money(
                        amount=Decimal("0"), asset_id=instrument.settlement_asset_id
                    ),
                )
            )
        self._pair(
            drafts,
            debit=base if buys else inventory,
            credit=inventory if buys else base,
            amount=base_quantity,
            asset_id=instrument.base_asset_id,
            memo=f"borrow-backed spot delivery for {fill.fill_id}",
        )
        self._pair(
            drafts,
            debit=cost if buys else quote,
            credit=quote if buys else cost,
            amount=base_quantity * fill.price.amount,
            asset_id=instrument.quote_asset_id,
            memo=f"borrow-backed spot consideration for {fill.fill_id}",
        )
        if realized_amount != 0:
            pnl = self._account(
                AccountRole.TRADING_REALIZED_PNL
                if realized_amount > 0
                else AccountRole.TRADING_LOSS,
                venue=venue,
                subject=str(instrument.quote_asset_id),
            )
            self._pair(
                drafts,
                debit=cost if realized_amount > 0 else pnl,
                credit=pnl if realized_amount > 0 else cost,
                amount=abs(realized_amount),
                asset_id=instrument.quote_asset_id,
                memo=f"borrow-backed spot FIFO PnL {fill.fill_id}",
            )
        self._fee_postings(drafts, fill, venue)
        return (
            drafts,
            changes,
            Money(amount=realized_amount, asset_id=instrument.settlement_asset_id),
        )

    def _derivative_fill(
        self, fill: Fill, instrument: AccountingInstrument
    ) -> tuple[list[_PostingDraft], list[LotChange], Money]:
        drafts: list[_PostingDraft] = []
        incoming_side = LotSide.LONG if fill.side.value == "BUY" else LotSide.SHORT
        residual, realized_amount, changes = self._consume_fifo(
            fill=fill,
            instrument=instrument,
            incoming_side=incoming_side,
            quantity=fill.quantity.amount,
            drafts=drafts,
        )
        if residual > 0:
            lot = self._new_lot(
                fill=fill,
                instrument=instrument,
                side=incoming_side,
                quantity=residual,
                ordinal=len(changes),
            )
            self._lots.setdefault(instrument.instrument_id, []).append(lot)
            basis = _position_basis(
                quantity=residual, price=fill.price.amount, instrument=instrument
            )
            cost = self._account(
                AccountRole.POSITION_COST,
                venue=instrument.venue,
                subject=str(instrument.instrument_id),
            )
            clearing = self._account(
                AccountRole.POSITION_CLEARING,
                venue=instrument.venue,
                subject=str(instrument.instrument_id),
            )
            self._pair(
                drafts,
                debit=cost,
                credit=clearing,
                amount=basis,
                asset_id=instrument.settlement_asset_id,
                memo=f"open derivative FIFO lot {lot.position_lot_id}",
            )
            changes.append(
                LotChange(
                    action=LotAction.OPEN,
                    lot_after=lot,
                    affected_quantity=residual,
                    realized_pnl=Money(
                        amount=Decimal("0"), asset_id=instrument.settlement_asset_id
                    ),
                )
            )
        realized = Money(amount=realized_amount, asset_id=instrument.settlement_asset_id)
        self._realized_postings(
            drafts,
            venue=instrument.venue,
            pnl=realized,
            memo=f"derivative realized PnL for {fill.fill_id}",
        )
        self._fee_postings(drafts, fill, instrument.venue)
        return drafts, changes, realized

    def _posting_models(
        self, *, entry_id: LedgerEntryId, drafts: Iterable[_PostingDraft]
    ) -> tuple[LedgerPosting, ...]:
        return tuple(
            LedgerPosting(
                posting_id=PostingId(
                    canonical_sha256({"entry_id": str(entry_id), "sequence": sequence})
                ),
                account_id=draft.account.account_id,
                side=draft.side,
                amount=Money(amount=draft.amount, asset_id=draft.asset_id),
                memo=draft.memo,
            )
            for sequence, draft in enumerate(drafts)
        )

    def _build_record(
        self,
        *,
        event_type: str,
        command_hash: str,
        idempotency_key: IdempotencyKey,
        event_time: datetime,
        recorded_at: datetime,
        description: str,
        drafts: list[_PostingDraft],
        lot_changes: list[LotChange],
        source_fill: Fill | None = None,
        supersedes_entry_id: LedgerEntryId | None = None,
    ) -> LedgerRecord:
        template = self.templates[event_type]
        present_roles = {draft.account.role for draft in drafts}
        missing_roles = set(template.required_roles) - present_roles
        if missing_roles:
            missing = ",".join(sorted(role.value for role in missing_roles))
            raise RuntimeError(f"entry template {event_type} missing roles: {missing}")
        entry_id = LedgerEntryId(command_hash)
        journal = JournalEntry(
            journal_entry_id=entry_id,
            event_time=event_time,
            recorded_at=recorded_at,
            description=description,
            postings=self._posting_models(entry_id=entry_id, drafts=drafts),
            reconciliation_adjustment=event_type == "RECONCILIATION_ADJUSTMENT",
            supersedes_entry_id=supersedes_entry_id,
        )
        previous_hash = self._records[-1].event_hash if self._records else ZERO_HASH
        identity = {
            "journal_entry": journal.model_dump(mode="json"),
            "policy_version": self.policy.policy_version,
            "chart_version": self.policy.chart_version,
            "entry_template_id": str(template.entry_template_id),
            "template_version": template.version,
            "source_fill_id": str(source_fill.fill_id) if source_fill else None,
            "source_order_intent_id": (str(source_fill.order_intent_id) if source_fill else None),
            "idempotency_key": str(idempotency_key),
            "command_hash": command_hash,
            "previous_hash": previous_hash,
            "lot_changes": [item.model_dump(mode="json") for item in lot_changes],
        }
        return LedgerRecord(
            journal_entry=journal,
            policy_version=self.policy.policy_version,
            chart_version=self.policy.chart_version,
            entry_template_id=template.entry_template_id,
            template_version=template.version,
            source_fill_id=source_fill.fill_id if source_fill else None,
            source_order_intent_id=source_fill.order_intent_id if source_fill else None,
            idempotency_key=idempotency_key,
            command_hash=command_hash,
            previous_hash=previous_hash,
            event_hash=canonical_sha256(identity),
            lot_changes=tuple(lot_changes),
        )

    def _append_record(self, record: LedgerRecord) -> None:
        for posting in record.journal_entry.postings:
            key = (posting.account_id, posting.amount.asset_id)
            signed = (
                posting.amount.amount
                if posting.side is PostingSide.DEBIT
                else -posting.amount.amount
            )
            self._balances[key] = canonical_result(self._balances.get(key, Decimal("0")) + signed)
        self._records.append(record)
        self._record_by_key[record.idempotency_key] = record
        self._command_hash_by_key[record.idempotency_key] = record.command_hash

    def process_fill(
        self, fill: Fill, instrument: AccountingInstrument, *, _replay: bool = False
    ) -> FillApplyOutcome:
        if fill.instrument_id != instrument.instrument_id:
            raise ValueError("fill instrument does not match accounting instrument")
        existing_instrument = self._instrument_by_id.get(instrument.instrument_id)
        if existing_instrument is not None and existing_instrument != instrument:
            raise ValueError("AQ-LEDGER-INSTRUMENT-CONTRACT-CONFLICT")
        if fill.quantity.asset_id != instrument.quantity_asset_id:
            raise ValueError("fill quantity unit does not match accounting instrument")
        if (
            fill.price.base_asset_id != instrument.base_asset_id
            or fill.price.quote_asset_id != instrument.quote_asset_id
        ):
            raise ValueError("fill price units do not match accounting instrument")
        command_hash = canonical_sha256(
            {
                "fill": fill.model_dump(mode="json"),
                "instrument": instrument.model_dump(mode="json"),
                "policy_version": self.policy.policy_version,
                **(
                    {"spot_fee_policy": self.policy.spot_fee_policy}
                    if self.policy.spot_fee_policy is not None
                    else {}
                ),
            }
        )
        fill_key = str(fill.fill_id)
        existing = self._fill_by_id.get(fill_key)
        known_hashes = {
            value
            for value in (
                self._command_hash_by_fill.get(fill_key),
                self._command_hash_by_key.get(fill.idempotency_key),
            )
            if value is not None
        }
        if known_hashes:
            if known_hashes != {command_hash} or existing is None:
                raise ValueError("AQ-LEDGER-IDEMPOTENCY-CONFLICT")
            return FillApplyOutcome(applied_fill=existing, inserted=False)
        if instrument.instrument_type is InstrumentType.SPOT:
            if self.policy.spot_fee_policy is not None:
                self._validate_native_spot_fee(fill, instrument)
            drafts, changes, realized = self._spot_fill(fill, instrument)
            if self.policy.spot_fee_policy is not None:
                fee_realized = self._native_spot_fee_lots(fill, instrument, drafts, changes)
                realized = Money(
                    amount=canonical_result(realized.amount + fee_realized),
                    asset_id=realized.asset_id,
                )
            event_type = "SPOT_FILL"
        else:
            drafts, changes, realized = self._derivative_fill(fill, instrument)
            event_type = "DERIVATIVE_FILL"
        record = self._build_record(
            event_type=event_type,
            command_hash=command_hash,
            idempotency_key=fill.idempotency_key,
            event_time=fill.event_time,
            recorded_at=fill.ingest_time,
            description=f"account fill {fill.fill_id}",
            drafts=drafts,
            lot_changes=changes,
            source_fill=fill,
        )
        self._append_record(record)
        applied = AppliedFill(
            fill=fill, instrument=instrument, record=record, realized_pnl=realized
        )
        self._fill_by_id[fill_key] = applied
        self._command_hash_by_fill[fill_key] = command_hash
        self._instrument_by_id[instrument.instrument_id] = instrument
        if not _replay:
            self._commands.append(FillCommand(fill=fill, instrument=instrument))
        return FillApplyOutcome(applied_fill=applied, inserted=True)

    def process_cashflow(self, event: CashflowEvent, *, _replay: bool = False) -> ApplyOutcome:
        command_hash = canonical_sha256(
            {
                "cashflow": event.model_dump(mode="json"),
                "policy_version": self.policy.policy_version,
            }
        )
        existing = self._record_by_key.get(event.idempotency_key)
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ValueError("AQ-LEDGER-IDEMPOTENCY-CONFLICT")
            return ApplyOutcome(record=existing, inserted=False)
        asset = event.amount.asset_id
        cash = self._account(AccountRole.CASH, venue=event.venue, subject=str(asset))
        drafts: list[_PostingDraft] = []
        template_type = event.cashflow_type.value
        if event.cashflow_type is CashflowType.FUNDING:
            if event.direction is CashflowDirection.INFLOW:
                template_type = "FUNDING_INCOME"
                counter = self._account(
                    AccountRole.FUNDING_INCOME, venue=event.venue, subject=str(asset)
                )
                debit, credit = cash, counter
            else:
                template_type = "FUNDING_EXPENSE"
                counter = self._account(
                    AccountRole.FUNDING_EXPENSE, venue=event.venue, subject=str(asset)
                )
                debit, credit = counter, cash
        elif event.cashflow_type is CashflowType.BORROW:
            counter = self._account(
                AccountRole.BORROWED_ASSET, venue=event.venue, subject=str(asset)
            )
            debit, credit = cash, counter
        elif event.cashflow_type is CashflowType.REPAY:
            counter = self._account(
                AccountRole.BORROWED_ASSET, venue=event.venue, subject=str(asset)
            )
            debit, credit = counter, cash
        elif event.cashflow_type is CashflowType.BORROW_INTEREST:
            counter = self._account(
                AccountRole.BORROW_INTEREST, venue=event.venue, subject=str(asset)
            )
            debit, credit = counter, cash
        elif event.cashflow_type in {
            CashflowType.EXTERNAL_TRANSFER_IN,
            CashflowType.EXTERNAL_TRANSFER_OUT,
        }:
            template_type = "EXTERNAL_TRANSFER"
            counter = self._account(
                AccountRole.OWNER_CAPITAL, venue=event.venue, subject=str(asset)
            )
            debit, credit = (
                (cash, counter) if event.direction is CashflowDirection.INFLOW else (counter, cash)
            )
        elif event.cashflow_type is CashflowType.TRANSFER_FEE:
            counter = self._account(AccountRole.TRANSFER_FEE, venue=event.venue, subject=str(asset))
            debit, credit = counter, cash
        else:
            counter = self._account(
                AccountRole.RECONCILIATION_RESERVE,
                venue=event.venue,
                subject=str(asset),
            )
            debit, credit = (
                (cash, counter) if event.direction is CashflowDirection.INFLOW else (counter, cash)
            )
        self._pair(
            drafts,
            debit=debit,
            credit=credit,
            amount=event.amount.amount,
            asset_id=asset,
            memo=event.reference,
        )
        supersedes = (
            LedgerEntryId(event.supersedes_entry_id)
            if event.supersedes_entry_id is not None
            else None
        )
        record = self._build_record(
            event_type=template_type,
            command_hash=command_hash,
            idempotency_key=event.idempotency_key,
            event_time=event.event_time,
            recorded_at=event.recorded_at,
            description=event.reference,
            drafts=drafts,
            lot_changes=[],
            supersedes_entry_id=supersedes,
        )
        self._append_record(record)
        if not _replay:
            self._commands.append(event)
        return ApplyOutcome(record=record, inserted=True)

    def process_settlement(self, event: SettlementEvent, *, _replay: bool = False) -> ApplyOutcome:
        command_hash = canonical_sha256(
            {
                "settlement": event.model_dump(mode="json"),
                "policy_version": self.policy.policy_version,
            }
        )
        existing = self._record_by_key.get(event.idempotency_key)
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ValueError("AQ-LEDGER-IDEMPOTENCY-CONFLICT")
            return ApplyOutcome(record=existing, inserted=False)
        instrument = event.instrument
        existing_instrument = self._instrument_by_id.get(instrument.instrument_id)
        if existing_instrument is None or existing_instrument != instrument:
            raise ValueError("AQ-LEDGER-INSTRUMENT-CONTRACT-CONFLICT")
        lots = tuple(self._lots.get(instrument.instrument_id, ()))
        if not lots:
            raise ValueError("cannot settle a future without open lots")
        drafts: list[_PostingDraft] = []
        changes: list[LotChange] = []
        realized_amount = Decimal("0")
        for lot in lots:
            pnl = calculate_contract_pnl(
                side=lot.side,
                quantity=lot.remaining_quantity,
                entry_price=lot.entry_price,
                exit_price=event.settlement_price,
                instrument=instrument,
            )
            realized_amount += pnl.amount
            basis = _position_basis(
                quantity=lot.remaining_quantity,
                price=lot.entry_price,
                instrument=instrument,
            )
            clearing = self._account(
                AccountRole.POSITION_CLEARING,
                venue=instrument.venue,
                subject=str(instrument.instrument_id),
            )
            cost = self._account(
                AccountRole.POSITION_COST,
                venue=instrument.venue,
                subject=str(instrument.instrument_id),
            )
            self._pair(
                drafts,
                debit=clearing,
                credit=cost,
                amount=basis,
                asset_id=instrument.settlement_asset_id,
                memo=f"settle FIFO lot {lot.position_lot_id}",
            )
            changes.append(
                LotChange(
                    action=LotAction.CLOSE,
                    lot_before=lot,
                    affected_quantity=lot.remaining_quantity,
                    realized_pnl=pnl,
                )
            )
        realized = Money(
            amount=canonical_result(realized_amount),
            asset_id=instrument.settlement_asset_id,
        )
        self._realized_postings(
            drafts,
            venue=instrument.venue,
            pnl=realized,
            memo=event.reference,
        )
        record = self._build_record(
            event_type="CONTRACT_SETTLEMENT",
            command_hash=command_hash,
            idempotency_key=event.idempotency_key,
            event_time=event.event_time,
            recorded_at=event.recorded_at,
            description=event.reference,
            drafts=drafts,
            lot_changes=changes,
        )
        self._append_record(record)
        self._lots[instrument.instrument_id] = []
        if not _replay:
            self._commands.append(event)
        return ApplyOutcome(record=record, inserted=True)

    def native_balances(self) -> tuple[AccountBalance, ...]:
        balances: list[AccountBalance] = []
        for (account_id, asset_id), raw in self._balances.items():
            definition = self.chart.definition(account_id)
            amount = raw if definition.normal_balance is NormalBalance.DEBIT else -raw
            if amount != 0:
                balances.append(
                    AccountBalance(
                        account_id=account_id,
                        asset_id=asset_id,
                        amount=canonical_result(amount),
                    )
                )
        return tuple(sorted(balances, key=lambda item: (str(item.account_id), str(item.asset_id))))

    def state_digest(self) -> LedgerStateDigest:
        balances = self.native_balances()
        positions = self.open_lots()
        last_hash = self._records[-1].event_hash if self._records else ZERO_HASH
        state_hash = canonical_sha256(
            {
                "entry_count": len(self._records),
                "last_event_hash": last_hash,
                "balances": [item.model_dump(mode="json") for item in balances],
                "positions": [item.model_dump(mode="json") for item in positions],
            }
        )
        return LedgerStateDigest(
            ledger_snapshot_id=LedgerSnapshotId(state_hash),
            entry_count=len(self._records),
            last_event_hash=last_hash,
            state_hash=state_hash,
            balances=balances,
            positions=positions,
        )

    def rebuild(self) -> Self:
        rebuilt = type(self)(policy=self.policy, effective_from=self.chart.effective_from)
        for command in self._commands:
            if isinstance(command, FillCommand):
                rebuilt.process_fill(command.fill, command.instrument, _replay=False)
            elif isinstance(command, CashflowEvent):
                rebuilt.process_cashflow(command, _replay=False)
            else:
                rebuilt.process_settlement(command, _replay=False)
        return rebuilt

    def valuation_snapshot(
        self, quotes: Mapping[InstrumentId, ValuationQuote]
    ) -> ValuationSnapshot:
        values: list[LotValuation] = []
        latest_as_of: UtcDateTime | None = None
        latest_available: UtcDateTime | None = None
        for lot in self.open_lots():
            try:
                quote = quotes[lot.instrument_id]
            except KeyError as error:
                raise ValueError(f"missing valuation quote for {lot.instrument_id}") from error
            source, price = quote.selected()
            spec = self._instrument_by_id.get(lot.instrument_id)
            if spec is None:
                raise RuntimeError("open lot has no replayable instrument contract")
            pnl = calculate_contract_pnl(
                side=lot.side,
                quantity=lot.remaining_quantity,
                entry_price=lot.entry_price,
                exit_price=price,
                instrument=spec,
            )
            values.append(
                LotValuation(
                    position_lot_id=lot.position_lot_id,
                    instrument_id=lot.instrument_id,
                    source=source,
                    price=price,
                    as_of_time=quote.as_of_time,
                    available_time=quote.available_time,
                    policy_version=quote.policy_version,
                    unrealized_pnl=pnl,
                )
            )
            latest_as_of = (
                quote.as_of_time if latest_as_of is None else max(latest_as_of, quote.as_of_time)
            )
            latest_available = (
                quote.available_time
                if latest_available is None
                else max(latest_available, quote.available_time)
            )
        if latest_as_of is None or latest_available is None:
            raise ValueError("valuation snapshot requires at least one open lot")
        payload = {
            "as_of_time": latest_as_of.isoformat(),
            "available_time": latest_available.isoformat(),
            "policy_version": self.policy.policy_version,
            "lots": [item.model_dump(mode="json") for item in values],
        }
        content_hash = canonical_sha256(payload)
        return ValuationSnapshot(
            valuation_snapshot_id=ValuationSnapshotId(content_hash),
            as_of_time=latest_as_of,
            available_time=latest_available,
            policy_version=self.policy.policy_version,
            lots=tuple(values),
            content_hash=content_hash,
        )

    @staticmethod
    def _fx_rate(
        *, asset_id: AssetId, reporting_asset_id: AssetId, rates: Mapping[AssetId, FxRate]
    ) -> Decimal:
        if asset_id == reporting_asset_id:
            return Decimal("1")
        try:
            rate = rates[asset_id]
        except KeyError as error:
            raise ValueError(f"missing FX rate for {asset_id}") from error
        if rate.reporting_asset_id != reporting_asset_id:
            raise ValueError("FX rate reporting asset mismatch")
        return rate.rate

    def equity_snapshot(
        self,
        *,
        valuation: ValuationSnapshot,
        reporting_asset_id: AssetId,
        fx_rates: Mapping[AssetId, FxRate],
    ) -> EquitySnapshot:
        balances = self.native_balances()
        balance_value = Decimal("0")
        for balance in balances:
            definition = self.chart.definition(balance.account_id)
            if not definition.economic_balance:
                continue
            rate = self._fx_rate(
                asset_id=balance.asset_id,
                reporting_asset_id=reporting_asset_id,
                rates=fx_rates,
            )
            sign = (
                Decimal("-1") if definition.account_type is AccountType.LIABILITY else Decimal("1")
            )
            balance_value += sign * balance.amount * rate
        unrealized_value = Decimal("0")
        for item in valuation.lots:
            rate = self._fx_rate(
                asset_id=item.unrealized_pnl.asset_id,
                reporting_asset_id=reporting_asset_id,
                rates=fx_rates,
            )
            unrealized_value += item.unrealized_pnl.amount * rate
        balance_value = canonical_result(balance_value)
        unrealized_value = canonical_result(unrealized_value)
        identity = {
            "state_hash": self.state_digest().state_hash,
            "valuation_snapshot_id": str(valuation.valuation_snapshot_id),
            "reporting_asset_id": str(reporting_asset_id),
            "balance_value": str(balance_value),
            "unrealized_pnl_value": str(unrealized_value),
        }
        return EquitySnapshot(
            account_snapshot_id=AccountSnapshotId(canonical_sha256(identity)),
            as_of_time=valuation.as_of_time,
            reporting_asset_id=reporting_asset_id,
            native_balances=balances,
            balance_value=balance_value,
            unrealized_pnl_value=unrealized_value,
            equity=canonical_result(balance_value + unrealized_value),
            valuation_snapshot_id=valuation.valuation_snapshot_id,
            policy_version=self.policy.policy_version,
        )

    def _role_value(
        self,
        role: AccountRole,
        *,
        reporting_asset_id: AssetId,
        fx_rates: Mapping[AssetId, FxRate],
    ) -> Decimal:
        total = Decimal("0")
        for balance in self.native_balances():
            definition = self.chart.definition(balance.account_id)
            if definition.role is role:
                total += balance.amount * self._fx_rate(
                    asset_id=balance.asset_id,
                    reporting_asset_id=reporting_asset_id,
                    rates=fx_rates,
                )
        return canonical_result(total)

    def pnl_breakdown(
        self,
        *,
        starting_equity: Decimal,
        ending_equity: Decimal,
        starting_unrealized: Decimal,
        ending_unrealized: Decimal,
        reporting_asset_id: AssetId,
        fx_rates: Mapping[AssetId, FxRate],
    ) -> PnLBreakdown:
        realized = self._role_value(
            AccountRole.TRADING_REALIZED_PNL,
            reporting_asset_id=reporting_asset_id,
            fx_rates=fx_rates,
        ) - self._role_value(
            AccountRole.TRADING_LOSS,
            reporting_asset_id=reporting_asset_id,
            fx_rates=fx_rates,
        )
        funding = self._role_value(
            AccountRole.FUNDING_INCOME,
            reporting_asset_id=reporting_asset_id,
            fx_rates=fx_rates,
        ) - self._role_value(
            AccountRole.FUNDING_EXPENSE,
            reporting_asset_id=reporting_asset_id,
            fx_rates=fx_rates,
        )
        fees = self._role_value(
            AccountRole.TRADING_FEE,
            reporting_asset_id=reporting_asset_id,
            fx_rates=fx_rates,
        ) - self._role_value(
            AccountRole.TRADING_FEE_REBATE,
            reporting_asset_id=reporting_asset_id,
            fx_rates=fx_rates,
        )
        return PnLBreakdown(
            reporting_asset_id=reporting_asset_id,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            net_external_transfers=self._role_value(
                AccountRole.OWNER_CAPITAL,
                reporting_asset_id=reporting_asset_id,
                fx_rates=fx_rates,
            ),
            realized_trading_pnl=realized,
            unrealized_pnl_change=ending_unrealized - starting_unrealized,
            funding_income_expense=funding,
            borrow_interest=self._role_value(
                AccountRole.BORROW_INTEREST,
                reporting_asset_id=reporting_asset_id,
                fx_rates=fx_rates,
            ),
            trading_fees=fees,
            transfer_fees=self._role_value(
                AccountRole.TRANSFER_FEE,
                reporting_asset_id=reporting_asset_id,
                fx_rates=fx_rates,
            ),
            reconciliation_adjustments=self._role_value(
                AccountRole.RECONCILIATION_RESERVE,
                reporting_asset_id=reporting_asset_id,
                fx_rates=fx_rates,
            ),
        )
