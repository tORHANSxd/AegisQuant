"""Account stream sequencing and REST snapshot reconciliation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import VenueOrder
from aegisquant.domain.identifiers import AssetId, FillId, VenueId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import FiniteDecimal


class AccountEventType(StrEnum):
    BALANCE = "BALANCE"
    ORDER = "ORDER"
    FILL = "FILL"
    SNAPSHOT_BOUNDARY = "SNAPSHOT_BOUNDARY"


class AccountBalance(DomainModel):
    asset_id: AssetId
    total: FiniteDecimal
    available: FiniteDecimal

    @model_validator(mode="after")
    def validate_balance(self) -> AccountBalance:
        if self.total < 0 or self.available < 0 or self.available > self.total:
            raise ValueError("account balance is outside valid range")
        return self


class AccountStreamEvent(DomainModel):
    event_id: str = Field(min_length=1, max_length=255)
    venue_id: VenueId
    sequence: int = Field(ge=1)
    event_type: AccountEventType
    observed_at: UtcDateTime
    available_at: UtcDateTime
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_times(self) -> AccountStreamEvent:
        if self.available_at < self.observed_at:
            raise ValueError("account event availability cannot precede observation")
        return self


class VenueAccountSnapshot(DomainModel):
    snapshot_id: str = Field(min_length=1, max_length=255)
    venue_id: VenueId
    sequence: int = Field(ge=0)
    captured_at: UtcDateTime
    balances: tuple[AccountBalance, ...]
    open_orders: tuple[VenueOrder, ...]
    recent_fill_ids: tuple[FillId, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> VenueAccountSnapshot:
        if len({item.asset_id for item in self.balances}) != len(self.balances):
            raise ValueError("account snapshot balances must be asset-unique")
        if len({item.client_order_id for item in self.open_orders}) != len(self.open_orders):
            raise ValueError("account snapshot open orders must be client-order-unique")
        return self


class AccountSyncState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    SYNCHRONIZED = "SYNCHRONIZED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class AccountSyncResult(DomainModel):
    state: AccountSyncState
    applied: bool
    sequence_gap: bool
    last_sequence: int = Field(ge=0)
    unknown_local_order_ids: tuple[str, ...]
    unknown_venue_order_ids: tuple[str, ...]
    unknown_local_fill_ids: tuple[str, ...]
    unknown_venue_fill_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = Field(min_length=1)


class AccountSynchronizer:
    """Keep account facts monotonic and require a snapshot after every gap."""

    def __init__(self, *, venue_id: VenueId) -> None:
        self.venue_id = venue_id
        self.state = AccountSyncState.DISCONNECTED
        self.last_sequence = 0
        self._processed_event_ids: set[str] = set()

    def disconnected(self) -> None:
        self.state = AccountSyncState.DISCONNECTED

    def consume(self, event: AccountStreamEvent) -> AccountSyncResult:
        if event.venue_id != self.venue_id:
            raise ValueError("AQ-EXEC-ACCOUNT-EVENT-VENUE-MISMATCH")
        if event.event_id in self._processed_event_ids:
            return self._result(applied=False, gap=False, reason="AQ-EXEC-ACCOUNT-DUPLICATE")
        if event.sequence <= self.last_sequence:
            self._processed_event_ids.add(event.event_id)
            return self._result(applied=False, gap=False, reason="AQ-EXEC-ACCOUNT-LATE")
        gap = self.last_sequence > 0 and event.sequence != self.last_sequence + 1
        self.last_sequence = event.sequence
        self._processed_event_ids.add(event.event_id)
        if gap:
            self.state = AccountSyncState.RECONCILIATION_REQUIRED
            return self._result(applied=True, gap=True, reason="AQ-EXEC-ACCOUNT-SEQUENCE-GAP")
        if self.state is not AccountSyncState.RECONCILIATION_REQUIRED:
            self.state = AccountSyncState.SYNCHRONIZED
        return self._result(applied=True, gap=False, reason="AQ-EXEC-ACCOUNT-EVENT-APPLIED")

    def reconcile(
        self,
        snapshot: VenueAccountSnapshot,
        *,
        local_open_order_ids: tuple[str, ...],
        local_fill_ids: tuple[str, ...] = (),
    ) -> AccountSyncResult:
        if snapshot.venue_id != self.venue_id:
            raise ValueError("AQ-EXEC-ACCOUNT-SNAPSHOT-VENUE-MISMATCH")
        if snapshot.sequence < self.last_sequence:
            self.state = AccountSyncState.RECONCILIATION_REQUIRED
            return self._result(
                applied=False,
                gap=True,
                reason="AQ-EXEC-ACCOUNT-SNAPSHOT-STALE",
            )
        local = set(local_open_order_ids)
        venue = {str(item.client_order_id) for item in snapshot.open_orders}
        local_fills = set(local_fill_ids)
        venue_fills = {str(item) for item in snapshot.recent_fill_ids}
        unknown_local_orders = tuple(sorted(local - venue))
        unknown_venue_orders = tuple(sorted(venue - local))
        unknown_local_fills = tuple(sorted(local_fills - venue_fills))
        unknown_venue_fills = tuple(sorted(venue_fills - local_fills))
        self.last_sequence = snapshot.sequence
        has_difference = any(
            (
                unknown_local_orders,
                unknown_venue_orders,
                unknown_local_fills,
                unknown_venue_fills,
            )
        )
        self.state = (
            AccountSyncState.RECONCILIATION_REQUIRED
            if has_difference
            else AccountSyncState.SYNCHRONIZED
        )
        return AccountSyncResult(
            state=self.state,
            applied=True,
            sequence_gap=False,
            last_sequence=self.last_sequence,
            unknown_local_order_ids=unknown_local_orders,
            unknown_venue_order_ids=unknown_venue_orders,
            unknown_local_fill_ids=unknown_local_fills,
            unknown_venue_fill_ids=unknown_venue_fills,
            reason_codes=(
                "AQ-EXEC-ACCOUNT-SNAPSHOT-DIFFERENCE"
                if has_difference
                else "AQ-EXEC-ACCOUNT-SNAPSHOT-RECONCILED",
            ),
        )

    def _result(self, *, applied: bool, gap: bool, reason: str) -> AccountSyncResult:
        return AccountSyncResult(
            state=self.state,
            applied=applied,
            sequence_gap=gap,
            last_sequence=self.last_sequence,
            unknown_local_order_ids=(),
            unknown_venue_order_ids=(),
            unknown_local_fill_ids=(),
            unknown_venue_fill_ids=(),
            reason_codes=(reason,),
        )
