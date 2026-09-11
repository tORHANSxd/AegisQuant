"""P05 accounting contracts with strict Decimal and explicit unit semantics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from aegisquant.data.market import ContractForm, InstrumentType, UnifiedInstrument
from aegisquant.domain.accounting import JournalEntry, LotSide
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import Fill
from aegisquant.domain.identifiers import (
    AccountId,
    AccountSnapshotId,
    ArtifactId,
    AssetId,
    EntryTemplateId,
    FillId,
    IdempotencyKey,
    InstrumentId,
    LedgerSnapshotId,
    OrderIntentId,
    PositionLotId,
    ReconciliationCaseId,
    ValuationSnapshotId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal, Money, NonNegativeDecimal, PositiveDecimal


class AccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    MEMO = "MEMO"


class AccountRole(StrEnum):
    CASH = "CASH"
    MARGIN_COLLATERAL = "MARGIN_COLLATERAL"
    POSITION_COST = "POSITION_COST"
    POSITION_CLEARING = "POSITION_CLEARING"
    INVENTORY_CLEARING = "INVENTORY_CLEARING"
    BORROWED_ASSET = "BORROWED_ASSET"
    ACCRUED_INTEREST = "ACCRUED_INTEREST"
    OWNER_CAPITAL = "OWNER_CAPITAL"
    TRADING_REALIZED_PNL = "TRADING_REALIZED_PNL"
    TRADING_LOSS = "TRADING_LOSS"
    FUNDING_INCOME = "FUNDING_INCOME"
    FUNDING_EXPENSE = "FUNDING_EXPENSE"
    TRADING_FEE = "TRADING_FEE"
    TRADING_FEE_REBATE = "TRADING_FEE_REBATE"
    BORROW_INTEREST = "BORROW_INTEREST"
    TRANSFER_FEE = "TRANSFER_FEE"
    RECONCILIATION_RESERVE = "RECONCILIATION_RESERVE"


class NormalBalance(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountDefinition(DomainModel):
    account_id: AccountId
    role: AccountRole
    account_type: AccountType
    normal_balance: NormalBalance
    venue: str
    subject: str
    economic_balance: bool
    version: str


class ChartOfAccounts(DomainModel):
    version: str
    effective_from: UtcDateTime
    definitions: tuple[AccountDefinition, ...]

    @model_validator(mode="after")
    def unique_accounts(self) -> ChartOfAccounts:
        ids = {item.account_id for item in self.definitions}
        if len(ids) != len(self.definitions):
            raise ValueError("chart of accounts contains duplicate account ids")
        return self


class EntryTemplate(DomainModel):
    entry_template_id: EntryTemplateId
    version: str
    event_type: str
    required_roles: tuple[AccountRole, ...]
    effective_from: UtcDateTime


class AccountingInstrument(DomainModel):
    instrument_id: InstrumentId
    venue: str
    base_asset_id: AssetId
    quote_asset_id: AssetId
    settlement_asset_id: AssetId
    quantity_asset_id: AssetId
    instrument_type: InstrumentType
    contract_form: ContractForm
    contract_multiplier: PositiveDecimal

    @classmethod
    def from_unified(cls, instrument: UnifiedInstrument) -> AccountingInstrument:
        quantity_asset = (
            AssetId(instrument.base_asset.asset_id)
            if instrument.exposure.instrument_type is InstrumentType.SPOT
            else AssetId(f"CONTRACT:{instrument.instrument_id}")
        )
        return cls(
            instrument_id=instrument.instrument_id,
            venue=instrument.venue.value,
            base_asset_id=AssetId(instrument.base_asset.asset_id),
            quote_asset_id=AssetId(instrument.quote_asset.asset_id),
            settlement_asset_id=AssetId(instrument.settlement_asset.asset_id),
            quantity_asset_id=quantity_asset,
            instrument_type=instrument.exposure.instrument_type,
            contract_form=instrument.exposure.contract_form,
            contract_multiplier=instrument.contract_multiplier,
        )

    @model_validator(mode="after")
    def dimensions_are_consistent(self) -> AccountingInstrument:
        if self.instrument_type is InstrumentType.SPOT:
            if self.contract_form is not ContractForm.SPOT:
                raise ValueError("spot accounting instrument requires SPOT form")
            if self.quantity_asset_id != self.base_asset_id:
                raise ValueError("spot fill quantity must use the base asset")
        elif self.contract_form is ContractForm.SPOT:
            raise ValueError("derivative accounting instrument cannot use SPOT form")
        return self


class QuantityUnit(StrEnum):
    BASE_ASSET = "BASE_ASSET"
    CONTRACT = "CONTRACT"


class PositionLotState(DomainModel):
    position_lot_id: PositionLotId
    account_id: AccountId
    instrument_id: InstrumentId
    side: LotSide
    quantity_unit: QuantityUnit
    quantity_asset_id: AssetId
    opened_quantity: PositiveDecimal
    remaining_quantity: NonNegativeDecimal
    entry_price: PositiveDecimal
    contract_form: ContractForm
    contract_multiplier: PositiveDecimal
    settlement_asset_id: AssetId
    opening_fee: Money
    source_fill_id: FillId
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def valid_lot_state(self) -> PositionLotState:
        if self.remaining_quantity > self.opened_quantity:
            raise ValueError("lot remaining quantity cannot exceed opened quantity")
        is_closed = self.remaining_quantity == 0
        if is_closed != (self.closed_at is not None):
            raise ValueError("closed lot requires zero remaining quantity and closed_at")
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("lot close cannot precede open")
        return self


class LotAction(StrEnum):
    OPEN = "OPEN"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"


class LotChange(DomainModel):
    action: LotAction
    lot_before: PositionLotState | None = None
    lot_after: PositionLotState | None = None
    affected_quantity: PositiveDecimal
    realized_pnl: Money

    @model_validator(mode="after")
    def valid_transition(self) -> LotChange:
        if self.action is LotAction.OPEN and (
            self.lot_before is not None or self.lot_after is None
        ):
            raise ValueError("open lot change requires only lot_after")
        if self.action in {LotAction.REDUCE, LotAction.CLOSE} and self.lot_before is None:
            raise ValueError("lot reduction requires lot_before")
        if self.action is LotAction.REDUCE and self.lot_after is None:
            raise ValueError("lot reduction requires lot_after")
        if self.action is LotAction.CLOSE and self.lot_after is not None:
            raise ValueError("closed lot change cannot retain lot_after")
        return self


class LedgerRecord(DomainModel):
    journal_entry: JournalEntry
    policy_version: str
    chart_version: str
    entry_template_id: EntryTemplateId
    template_version: str
    source_fill_id: FillId | None = None
    source_order_intent_id: OrderIntentId | None = None
    idempotency_key: IdempotencyKey
    command_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lot_changes: tuple[LotChange, ...] = ()


class AppliedFill(DomainModel):
    fill: Fill
    instrument: AccountingInstrument
    record: LedgerRecord
    realized_pnl: Money


class CashflowType(StrEnum):
    FUNDING = "FUNDING"
    BORROW = "BORROW"
    REPAY = "REPAY"
    BORROW_INTEREST = "BORROW_INTEREST"
    EXTERNAL_TRANSFER_IN = "EXTERNAL_TRANSFER_IN"
    EXTERNAL_TRANSFER_OUT = "EXTERNAL_TRANSFER_OUT"
    TRANSFER_FEE = "TRANSFER_FEE"
    RECONCILIATION_ADJUSTMENT = "RECONCILIATION_ADJUSTMENT"


class CashflowDirection(StrEnum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class CashflowEvent(DomainModel):
    event_id: ArtifactId
    venue: str
    cashflow_type: CashflowType
    direction: CashflowDirection
    amount: Money
    event_time: UtcDateTime
    recorded_at: UtcDateTime
    idempotency_key: IdempotencyKey
    reference: str
    supersedes_entry_id: str | None = None
    approval_reference: str | None = None
    evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_cashflow(self) -> CashflowEvent:
        if self.amount.amount <= 0:
            raise ValueError("cashflow amount must be positive; direction belongs to the type")
        if self.recorded_at < self.event_time:
            raise ValueError("cashflow cannot be recorded before its event")
        required_direction = {
            CashflowType.BORROW: CashflowDirection.INFLOW,
            CashflowType.REPAY: CashflowDirection.OUTFLOW,
            CashflowType.BORROW_INTEREST: CashflowDirection.OUTFLOW,
            CashflowType.EXTERNAL_TRANSFER_IN: CashflowDirection.INFLOW,
            CashflowType.EXTERNAL_TRANSFER_OUT: CashflowDirection.OUTFLOW,
            CashflowType.TRANSFER_FEE: CashflowDirection.OUTFLOW,
        }.get(self.cashflow_type)
        if required_direction is not None and self.direction is not required_direction:
            raise ValueError("cashflow direction conflicts with its type")
        is_adjustment = self.cashflow_type is CashflowType.RECONCILIATION_ADJUSTMENT
        has_adjustment_evidence = bool(
            self.supersedes_entry_id and self.approval_reference and self.evidence
        )
        if is_adjustment != has_adjustment_evidence:
            raise ValueError(
                "reconciliation adjustment requires supersedes, approval, and evidence"
            )
        return self


class SettlementEvent(DomainModel):
    event_id: ArtifactId
    instrument: AccountingInstrument
    settlement_price: PositiveDecimal
    event_time: UtcDateTime
    available_time: UtcDateTime
    recorded_at: UtcDateTime
    idempotency_key: IdempotencyKey
    reference: str

    @model_validator(mode="after")
    def validate_settlement(self) -> SettlementEvent:
        if self.instrument.instrument_type is not InstrumentType.FUTURE:
            raise ValueError("contract settlement is supported only for dated futures")
        if not self.event_time <= self.available_time <= self.recorded_at:
            raise ValueError("settlement event/available/recorded times must be monotonic")
        return self


class ValuationSource(StrEnum):
    MARK = "MARK"
    MID = "MID"
    LAST = "LAST"
    INDEX = "INDEX"


VALUATION_PRIORITY = (
    ValuationSource.MARK,
    ValuationSource.MID,
    ValuationSource.LAST,
    ValuationSource.INDEX,
)


class ValuationQuote(DomainModel):
    instrument_id: InstrumentId
    as_of_time: UtcDateTime
    available_time: UtcDateTime
    mark: PositiveDecimal | None = None
    mid: PositiveDecimal | None = None
    last: PositiveDecimal | None = None
    index: PositiveDecimal | None = None
    policy_version: str = "valuation-v1"

    @model_validator(mode="after")
    def has_price(self) -> ValuationQuote:
        if self.as_of_time > self.available_time:
            raise ValueError("valuation cannot be available before its as-of time")
        if all(getattr(self, item.value.lower()) is None for item in VALUATION_PRIORITY):
            raise ValueError("valuation requires at least one configured price")
        return self

    def selected(self) -> tuple[ValuationSource, Decimal]:
        for source in VALUATION_PRIORITY:
            value = getattr(self, source.value.lower())
            if value is not None:
                return source, value
        raise RuntimeError("validated valuation quote has no price")


class LotValuation(DomainModel):
    position_lot_id: PositionLotId
    instrument_id: InstrumentId
    source: ValuationSource
    price: PositiveDecimal
    as_of_time: UtcDateTime
    available_time: UtcDateTime
    policy_version: str
    unrealized_pnl: Money


class ValuationSnapshot(DomainModel):
    valuation_snapshot_id: ValuationSnapshotId
    as_of_time: UtcDateTime
    available_time: UtcDateTime
    policy_version: str
    lots: tuple[LotValuation, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AccountBalance(DomainModel):
    account_id: AccountId
    asset_id: AssetId
    amount: FiniteDecimal


class FxRate(DomainModel):
    asset_id: AssetId
    reporting_asset_id: AssetId
    rate: PositiveDecimal
    as_of_time: UtcDateTime
    policy_version: str


class EquitySnapshot(DomainModel):
    account_snapshot_id: AccountSnapshotId
    as_of_time: UtcDateTime
    reporting_asset_id: AssetId
    native_balances: tuple[AccountBalance, ...]
    balance_value: FiniteDecimal
    unrealized_pnl_value: FiniteDecimal
    equity: FiniteDecimal
    valuation_snapshot_id: ValuationSnapshotId
    policy_version: str

    @model_validator(mode="after")
    def equity_adds_up(self) -> EquitySnapshot:
        if self.equity != self.balance_value + self.unrealized_pnl_value:
            raise ValueError("equity must equal valued balances plus unrealized PnL")
        return self


class PnLBreakdown(DomainModel):
    reporting_asset_id: AssetId
    starting_equity: FiniteDecimal
    ending_equity: FiniteDecimal
    net_external_transfers: FiniteDecimal
    realized_trading_pnl: FiniteDecimal
    unrealized_pnl_change: FiniteDecimal
    funding_income_expense: FiniteDecimal
    borrow_interest: NonNegativeDecimal
    trading_fees: FiniteDecimal
    transfer_fees: NonNegativeDecimal
    reconciliation_adjustments: FiniteDecimal

    @model_validator(mode="after")
    def decomposition_conserves(self) -> PnLBreakdown:
        left = self.ending_equity - self.starting_equity - self.net_external_transfers
        right = (
            self.realized_trading_pnl
            + self.unrealized_pnl_change
            + self.funding_income_expense
            - self.borrow_interest
            - self.trading_fees
            - self.transfer_fees
            + self.reconciliation_adjustments
        )
        if left != right:
            raise ValueError("AQ-LEDGER-PNL-DECOMPOSITION-MISMATCH")
        return self


class LedgerStateDigest(DomainModel):
    ledger_snapshot_id: LedgerSnapshotId
    entry_count: int = Field(ge=0)
    last_event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    balances: tuple[AccountBalance, ...]
    positions: tuple[PositionLotState, ...]


class DailyLedgerSnapshot(DomainModel):
    ledger_snapshot_id: LedgerSnapshotId
    snapshot_date: date
    created_at: UtcDateTime
    policy_version: str
    ledger_entry_count: int = Field(ge=0)
    last_event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_key_base64: str = Field(min_length=1)
    signature_base64: str = Field(min_length=1)
    signature_algorithm: Literal["Ed25519"] = "Ed25519"

    @model_validator(mode="after")
    def date_matches_creation(self) -> DailyLedgerSnapshot:
        if self.created_at.date() != self.snapshot_date:
            raise ValueError("daily ledger snapshot date must match UTC creation date")
        return self


class LedgerSnapshotVerification(DomainModel):
    ledger_snapshot_id: LedgerSnapshotId
    verified_at: UtcDateTime
    signature_valid: bool
    rebuild_matches: bool


class ReconciliationMode(StrEnum):
    STARTUP = "STARTUP"
    CONTINUOUS = "CONTINUOUS"
    RECONNECT = "RECONNECT"


class ReconciliationDifferenceType(StrEnum):
    EXPECTED_TIMING = "EXPECTED_TIMING"
    MISSING_LOCAL_EVENT = "MISSING_LOCAL_EVENT"
    MISSING_VENUE_EVENT = "MISSING_VENUE_EVENT"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    ROUNDING = "ROUNDING"
    FEE_MISMATCH = "FEE_MISMATCH"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    BALANCE_MISMATCH = "BALANCE_MISMATCH"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    UNEXPLAINED = "UNEXPLAINED"


class ReconciliationStatus(StrEnum):
    CLEAR = "CLEAR"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HALTED = "HALTED"


class SnapshotAmount(DomainModel):
    key: str
    amount: FiniteDecimal


class VenueAccountSnapshot(DomainModel):
    account_snapshot_id: AccountSnapshotId
    venue: str
    as_of_time: UtcDateTime
    balances: tuple[SnapshotAmount, ...]
    positions: tuple[SnapshotAmount, ...]
    fees: tuple[SnapshotAmount, ...] = ()
    funding: tuple[SnapshotAmount, ...] = ()
    open_order_ids: tuple[str, ...] = ()
    recent_order_ids: tuple[str, ...] = ()
    fill_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def keys_are_unique(self) -> VenueAccountSnapshot:
        for values in (self.balances, self.positions, self.fees, self.funding):
            if len({item.key for item in values}) != len(values):
                raise ValueError("account snapshot contains duplicate amount keys")
        return self


class ReconciliationDifference(DomainModel):
    difference_type: ReconciliationDifferenceType
    dimension: str
    key: str
    local_value: str
    venue_value: str
    evidence: tuple[str, ...]


class ReconciliationCase(DomainModel):
    reconciliation_case_id: ReconciliationCaseId
    mode: ReconciliationMode
    local_snapshot_id: AccountSnapshotId
    venue_snapshot_id: AccountSnapshotId
    opened_at: UtcDateTime
    status: ReconciliationStatus
    new_orders_allowed: bool
    differences: tuple[ReconciliationDifference, ...]

    @model_validator(mode="after")
    def status_matches_differences(self) -> ReconciliationCase:
        if not self.differences and self.status is not ReconciliationStatus.CLEAR:
            raise ValueError("clear reconciliation must use CLEAR status")
        if self.differences and self.status is ReconciliationStatus.CLEAR:
            raise ValueError("reconciliation with differences cannot be CLEAR")
        if self.new_orders_allowed != (self.status is ReconciliationStatus.CLEAR):
            raise ValueError("new orders are allowed only after clear reconciliation")
        return self
