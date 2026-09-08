"""Deterministic Spot and USD-M snapshot-plus-delta local order books."""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.data.providers.binance.contracts import Product
from aegisquant.data.providers.binance.models import DepthDeltaRecord
from aegisquant.domain.base import DomainModel


class ApplyDisposition(StrEnum):
    BUFFERED = "BUFFERED"
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    LATE = "LATE"
    GAP = "GAP"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class OrderBookSnapshot(DomainModel):
    product: Product
    symbol: str
    last_update_id: int = Field(ge=0)
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> OrderBookSnapshot:
        if any(price <= 0 or quantity < 0 for price, quantity in self.bids + self.asks):
            raise ValueError("snapshot prices must be positive and quantities non-negative")
        active_bids = [price for price, quantity in self.bids if quantity > 0]
        active_asks = [price for price, quantity in self.asks if quantity > 0]
        if active_bids and active_asks and max(active_bids) > min(active_asks):
            raise ValueError("snapshot is crossed")
        return self


class ApplyResult(DomainModel):
    disposition: ApplyDisposition
    watermark: int | None
    recovery_required: bool
    reason_code: str


class LocalOrderBook:
    """Mutable reconstruction state whose inputs and results remain strict contracts."""

    def __init__(self, *, product: Product, symbol: str, maximum_buffered_events: int = 50_000):
        if maximum_buffered_events < 1:
            raise ValueError("maximum_buffered_events must be positive")
        self.product = product
        self.symbol = symbol
        self.maximum_buffered_events = maximum_buffered_events
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.last_update_id: int | None = None
        self._first_event_after_snapshot = True
        self._recovery_required = False
        self._buffer: deque[DepthDeltaRecord] = deque()
        self._seen_order: deque[tuple[int, int]] = deque()
        self._seen: set[tuple[int, int]] = set()

    @property
    def recovery_required(self) -> bool:
        return self._recovery_required

    def buffer_or_apply(self, event: DepthDeltaRecord) -> ApplyResult:
        self._require_matching_event(event)
        if self.last_update_id is None:
            if len(self._buffer) >= self.maximum_buffered_events:
                self._recovery_required = True
                return ApplyResult(
                    disposition=ApplyDisposition.GAP,
                    watermark=None,
                    recovery_required=True,
                    reason_code="AQ-DATA-ORDERBOOK-BUFFER-OVERFLOW",
                )
            self._buffer.append(event)
            return ApplyResult(
                disposition=ApplyDisposition.BUFFERED,
                watermark=None,
                recovery_required=False,
                reason_code="AQ-DATA-ORDERBOOK-AWAITING-SNAPSHOT",
            )
        return self.apply(event)

    def load_snapshot(self, snapshot: OrderBookSnapshot) -> tuple[ApplyResult, ...]:
        if snapshot.product is not self.product or snapshot.symbol != self.symbol:
            raise ValueError("snapshot does not match the local order book")
        self.bids = {price: quantity for price, quantity in snapshot.bids if quantity > 0}
        self.asks = {price: quantity for price, quantity in snapshot.asks if quantity > 0}
        self.last_update_id = snapshot.last_update_id
        self._first_event_after_snapshot = True
        self._recovery_required = False
        self._seen.clear()
        self._seen_order.clear()
        pending = tuple(self._buffer)
        self._buffer.clear()
        results: list[ApplyResult] = []
        for event in pending:
            if event.final_update_id <= snapshot.last_update_id:
                continue
            result = self.apply(event)
            results.append(result)
            if result.recovery_required:
                break
        return tuple(results)

    def apply(self, event: DepthDeltaRecord) -> ApplyResult:
        self._require_matching_event(event)
        watermark = self.last_update_id
        if watermark is None:
            return self.buffer_or_apply(event)
        if self._recovery_required:
            return ApplyResult(
                disposition=ApplyDisposition.RECOVERY_REQUIRED,
                watermark=watermark,
                recovery_required=True,
                reason_code="AQ-DATA-ORDERBOOK-RESNAPSHOT-REQUIRED",
            )
        identity = (event.first_update_id, event.final_update_id)
        if identity in self._seen:
            return ApplyResult(
                disposition=ApplyDisposition.DUPLICATE,
                watermark=watermark,
                recovery_required=False,
                reason_code="AQ-DATA-ORDERBOOK-DUPLICATE",
            )
        if event.final_update_id <= watermark:
            self._remember(identity)
            return ApplyResult(
                disposition=ApplyDisposition.LATE,
                watermark=watermark,
                recovery_required=False,
                reason_code="AQ-DATA-ORDERBOOK-LATE",
            )
        if self.product is Product.SPOT:
            sequence_ok = event.first_update_id <= watermark + 1 <= event.final_update_id
            reason = "AQ-DATA-ORDERBOOK-SPOT-SEQUENCE-GAP"
        elif self._first_event_after_snapshot:
            sequence_ok = event.first_update_id <= watermark <= event.final_update_id
            reason = "AQ-DATA-ORDERBOOK-USDM-FIRST-SEQUENCE-GAP"
        else:
            sequence_ok = event.previous_final_update_id == watermark
            reason = "AQ-DATA-ORDERBOOK-USDM-PREVIOUS-SEQUENCE-GAP"
        if not sequence_ok:
            self._recovery_required = True
            return ApplyResult(
                disposition=ApplyDisposition.GAP,
                watermark=watermark,
                recovery_required=True,
                reason_code=reason,
            )
        previous_bids = self._apply_levels(self.bids, event.bids)
        previous_asks = self._apply_levels(self.asks, event.asks)
        if self.bids and self.asks and max(self.bids) > min(self.asks):
            self._restore_levels(self.bids, previous_bids)
            self._restore_levels(self.asks, previous_asks)
            self._recovery_required = True
            return ApplyResult(
                disposition=ApplyDisposition.GAP,
                watermark=watermark,
                recovery_required=True,
                reason_code="AQ-DATA-ORDERBOOK-CROSSED",
            )
        self.last_update_id = event.final_update_id
        self._first_event_after_snapshot = False
        self._remember(identity)
        return ApplyResult(
            disposition=ApplyDisposition.APPLIED,
            watermark=event.final_update_id,
            recovery_required=False,
            reason_code="AQ-DATA-ORDERBOOK-APPLIED",
        )

    def force_resnapshot(self) -> None:
        """Invalidate the current watermark after a transport loss or explicit recovery signal."""
        self.last_update_id = None
        self._first_event_after_snapshot = True
        self._recovery_required = False
        self.bids.clear()
        self.asks.clear()
        self._seen.clear()
        self._seen_order.clear()

    def best_bid_ask(self) -> tuple[tuple[Decimal, Decimal], tuple[Decimal, Decimal]]:
        if not self.bids or not self.asks:
            raise ValueError("order book has no two-sided quote")
        bid_price = max(self.bids)
        ask_price = min(self.asks)
        return (bid_price, self.bids[bid_price]), (ask_price, self.asks[ask_price])

    def _require_matching_event(self, event: DepthDeltaRecord) -> None:
        if event.product is not self.product or event.symbol != self.symbol:
            raise ValueError("depth event does not match the local order book")

    @staticmethod
    def _apply_levels(
        side: dict[Decimal, Decimal], levels: tuple[tuple[Decimal, Decimal], ...]
    ) -> dict[Decimal, Decimal | None]:
        previous: dict[Decimal, Decimal | None] = {}
        for price, quantity in levels:
            previous.setdefault(price, side.get(price))
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity
        return previous

    @staticmethod
    def _restore_levels(
        side: dict[Decimal, Decimal], previous: dict[Decimal, Decimal | None]
    ) -> None:
        for price, quantity in previous.items():
            if quantity is None:
                side.pop(price, None)
            else:
                side[price] = quantity

    def _remember(self, identity: tuple[int, int]) -> None:
        self._seen.add(identity)
        self._seen_order.append(identity)
        while len(self._seen_order) > 4096:
            self._seen.discard(self._seen_order.popleft())
