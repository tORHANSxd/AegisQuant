"""Point-in-time instrument rule selection and order legality."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from itertools import pairwise

from aegisquant.backtest.models import BacktestOrder, HistoricalInstrumentRule
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import InstrumentId, VenueId
from aegisquant.domain.time import UtcDateTime


class RuleDecision(DomainModel):
    rule: HistoricalInstrumentRule
    valid: bool
    rejection_code: str | None


class HistoricalRuleBook:
    """Immutable effective-time rule book that rejects gaps and overlaps explicitly."""

    def __init__(self, rules: Iterable[HistoricalInstrumentRule]) -> None:
        ordered = tuple(
            sorted(
                rules,
                key=lambda item: (
                    str(item.venue_id),
                    str(item.instrument_id),
                    item.effective_from,
                ),
            )
        )
        if not ordered:
            raise ValueError("historical rule book cannot be empty")
        by_key: dict[tuple[str, str], list[HistoricalInstrumentRule]] = {}
        for rule in ordered:
            by_key.setdefault((str(rule.venue_id), str(rule.instrument_id)), []).append(rule)
        for values in by_key.values():
            for earlier, later in pairwise(values):
                if earlier.effective_to is None or earlier.effective_to > later.effective_from:
                    raise ValueError("AQ-BACKTEST-RULE-OVERLAP")
                if earlier.effective_to < later.effective_from:
                    raise ValueError("AQ-BACKTEST-RULE-GAP")
        self._rules = ordered

    @property
    def rules(self) -> tuple[HistoricalInstrumentRule, ...]:
        return self._rules

    def at(
        self,
        *,
        venue_id: VenueId,
        instrument_id: InstrumentId,
        event_time: UtcDateTime,
    ) -> HistoricalInstrumentRule:
        candidates = tuple(
            rule
            for rule in self._rules
            if rule.venue_id == venue_id
            and rule.instrument_id == instrument_id
            and rule.effective_from <= event_time
            and (rule.effective_to is None or event_time < rule.effective_to)
        )
        if len(candidates) != 1:
            raise ValueError("AQ-BACKTEST-HISTORICAL-RULE-MISSING")
        return candidates[0]

    def validate_order(self, order: BacktestOrder, *, reference_price: Decimal) -> RuleDecision:
        rule = self.at(
            venue_id=order.venue_id,
            instrument_id=order.instrument_id,
            event_time=order.submitted_at,
        )
        rejection: str | None = None
        quantity = order.quantity.amount
        price = order.limit_price.amount if order.limit_price is not None else reference_price
        if not rule.trading_enabled:
            rejection = "AQ-BACKTEST-RULE-TRADING-DISABLED"
        elif quantity < rule.minimum_quantity:
            rejection = "AQ-BACKTEST-RULE-MIN-QUANTITY"
        elif rule.maximum_quantity is not None and quantity > rule.maximum_quantity:
            rejection = "AQ-BACKTEST-RULE-MAX-QUANTITY"
        elif quantity % rule.step_size != 0:
            rejection = "AQ-BACKTEST-RULE-STEP-SIZE"
        elif order.limit_price is not None and price % rule.tick_size != 0:
            rejection = "AQ-BACKTEST-RULE-TICK-SIZE"
        elif quantity * price < rule.minimum_notional:
            rejection = "AQ-BACKTEST-RULE-MIN-NOTIONAL"
        return RuleDecision(rule=rule, valid=rejection is None, rejection_code=rejection)
