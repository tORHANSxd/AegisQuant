"""Liquidity/history eligibility on the existing point-in-time membership snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from aegisquant.backtest.models import HistoricalInstrumentRule
from aegisquant.backtest.rules import HistoricalRuleBook
from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal, exact_decimal_sum
from aegisquant.research.datasets.universe import PointInTimeUniverse, UniverseSnapshot


class ClosedLiquidityBar(DomainModel):
    """Evidence for an exclusive UTC four-hour close, without a price/replay interface."""

    close_time: UtcDateTime
    available_time: UtcDateTime
    quote_turnover: NonNegativeDecimal
    source_sha256: str

    @model_validator(mode="after")
    def validate_bar(self) -> ClosedLiquidityBar:
        ensure_sha256(self.source_sha256, field_name="closed liquidity bar source")
        if (
            self.close_time.hour % 4
            or self.close_time.minute
            or self.close_time.second
            or self.close_time.microsecond
        ):
            raise ValueError("PIT bars require aligned exclusive four-hour UTC closes")
        if self.available_time < self.close_time:
            raise ValueError("unclosed liquidity evidence is not decision-known")
        return self


class LiquidityEvidence(DomainModel):
    quote_method: Literal[
        "EXCHANGE_QUOTE_TURNOVER",
        "TRADE_QUOTE_SUM",
        "BASE_VOLUME_TIMES_CLOSE_PROXY",
        "UNKNOWN",
        "SYNTHETIC",
    ]
    bars: tuple[ClosedLiquidityBar, ...]
    detail_sha256: str

    @model_validator(mode="after")
    def validate_details(self) -> LiquidityEvidence:
        ensure_sha256(self.detail_sha256, field_name="liquidity detail hash")
        ordered = sorted(self.bars, key=lambda bar: bar.close_time)
        if len({bar.close_time for bar in ordered}) != len(ordered):
            raise ValueError("AQ-PIT-DUPLICATE-LIQUIDITY-BAR")
        if canonical_sha256([bar.model_dump(mode="json") for bar in ordered]) != self.detail_sha256:
            raise ValueError("AQ-PIT-LIQUIDITY-DETAIL-HASH")
        return self


class LiquidityObservation(DomainModel):
    instrument_id: str
    window_start: UtcDateTime
    window_end: UtcDateTime
    available_time: UtcDateTime
    complete_history_4h_bars: int = Field(ge=0)
    trailing_quote_volume: NonNegativeDecimal
    source_sha256: str
    revision: int = Field(default=1, ge=1)
    revision_time: UtcDateTime | None = None
    evidence: LiquidityEvidence | None = None

    @model_validator(mode="after")
    def valid_window(self) -> LiquidityObservation:
        ensure_sha256(self.source_sha256, field_name="liquidity source hash")
        if self.window_end - self.window_start != timedelta(days=30):
            raise ValueError("liquidity requires an explicit trailing 30-day window")
        if self.available_time < self.window_end:
            raise ValueError("liquidity cannot be available before its window ends")
        if self.revision_time is not None and self.revision_time < self.available_time:
            raise ValueError("liquidity revision predates original availability")
        if self.evidence is not None:
            known = self.revision_time or self.available_time
            if any(
                bar.available_time > known or bar.close_time > self.window_end
                for bar in self.evidence.bars
            ):
                raise ValueError("AQ-PIT-LIQUIDITY-DETAIL-LOOKAHEAD")
            total = exact_decimal_sum(
                bar.quote_turnover
                for bar in self.evidence.bars
                if self.window_start < bar.close_time <= self.window_end
            )
            if total != self.trailing_quote_volume:
                raise ValueError("AQ-PIT-QUOTE-TURNOVER-RECONCILIATION")
        return self


class RuleProvenance(DomainModel):
    """Decision-known provenance around the existing effective-time rule model."""

    record_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    available_time: UtcDateTime
    revision_time: UtcDateTime | None = None
    account_scope: Literal["PUBLIC_SPOT_RULES"] = "PUBLIC_SPOT_RULES"
    verified_kind: Literal["ARCHIVED_EXCHANGE_RULE", "PROXY", "UNKNOWN", "SYNTHETIC"]
    rule: HistoricalInstrumentRule
    source_sha256: str
    filter_payload_json: str | None = None
    payload_sha256: str

    @model_validator(mode="after")
    def validate_provenance(self) -> RuleProvenance:
        ensure_sha256(self.source_sha256, field_name="historical rule source")
        ensure_sha256(self.payload_sha256, field_name="historical rule payload")
        if self.revision_time is not None and self.revision_time < self.available_time:
            raise ValueError("rule revision predates original availability")
        filters = (
            json.loads(self.filter_payload_json) if self.filter_payload_json is not None else None
        )
        if (
            canonical_sha256({"rule": self.rule.model_dump(mode="json"), "filters": filters})
            != self.payload_sha256
        ):
            raise ValueError("AQ-PIT-RULE-PAYLOAD-HASH")
        if self.verified_kind in {"ARCHIVED_EXCHANGE_RULE", "SYNTHETIC"}:
            required = {
                "PRICE_FILTER",
                "LOT_SIZE",
                "MARKET_LOT_SIZE",
                "NOTIONAL",
                "ORDER_PERMISSIONS",
            }
            if (
                not isinstance(filters, dict)
                or not required <= filters.keys()
                or any(not filters[key] for key in required)
            ):
                raise ValueError("AQ-PIT-INCOMPLETE-RULE-PROVENANCE")
            if self.rule.approximation is not None:
                raise ValueError("proxy rules cannot be declared verified")
        return self


class UniverseDecision(DomainModel):
    instrument_uid: str
    membership_id: str | None
    disposition: Literal["ELIGIBLE", "EXCLUDED", "UNKNOWN"]
    reason_codes: tuple[str, ...]
    liquidity_source_sha256: str | None = None
    liquidity_detail_sha256: str | None = None
    trailing_quote_volume: NonNegativeDecimal | None = None
    contiguous_4h_bars: int | None = None
    tradable_history_4h_bars: int | None = None
    required_history_bars: int
    liquidity_window_bars: int | None = None
    liquidity_gap_count: int | None = None
    rule_payload_sha256: str | None = None


class PITUniverseSnapshot(DomainModel):
    snapshot_sha256: str
    membership_snapshot: UniverseSnapshot
    eligible_instrument_ids: tuple[str, ...]
    decisions: tuple[UniverseDecision, ...]
    known_future_event_ids: tuple[str, ...]
    held_instrument_ids: tuple[str, ...]
    policy_sha256: str
    scope: Literal["NEW_RISK_ONLY_NO_POSITION_MUTATION"] = "NEW_RISK_ONLY_NO_POSITION_MUTATION"


def _latest_liquidity(
    observations: Iterable[LiquidityObservation], decision_time: UtcDateTime
) -> dict[str, LiquidityObservation]:
    revisions: dict[tuple[str, UtcDateTime, int], LiquidityObservation] = {}
    for row in observations:
        if (
            max(row.available_time, row.revision_time or row.available_time, row.window_end)
            > decision_time
        ):
            continue
        key = row.instrument_id, row.window_end, row.revision
        if key in revisions and revisions[key] != row:
            raise ValueError("AQ-PIT-CONFLICTING-LIQUIDITY-REVISION")
        revisions[key] = row
    latest: dict[str, LiquidityObservation] = {}
    for row in revisions.values():
        previous = latest.get(row.instrument_id)
        if previous is None or (row.window_end, row.revision) > (
            previous.window_end,
            previous.revision,
        ):
            latest[row.instrument_id] = row
    return latest


def _known_rules(
    rules: Iterable[RuleProvenance], decision_time: UtcDateTime
) -> dict[str, list[RuleProvenance]]:
    revisions: dict[tuple[str, str, str, int], RuleProvenance] = {}
    for row in rules:
        if max(row.available_time, row.revision_time or row.available_time) > decision_time:
            continue
        key = str(row.rule.venue_id), str(row.rule.instrument_id), row.record_id, row.revision
        if key in revisions and revisions[key] != row:
            raise ValueError("AQ-PIT-CONFLICTING-RULE-REVISION")
        revisions[key] = row
    latest: dict[tuple[str, str, str], RuleProvenance] = {}
    for key, row in revisions.items():
        if key[:3] not in latest or row.revision > latest[key[:3]].revision:
            latest[key[:3]] = row
    active: dict[str, list[RuleProvenance]] = {}
    for row in latest.values():
        if row.rule.effective_from <= decision_time and (
            row.rule.effective_to is None or decision_time < row.rule.effective_to
        ):
            active.setdefault(str(row.rule.instrument_id), []).append(row)
    return active


def audit_universe_at(
    universe: PointInTimeUniverse,
    observations: Iterable[LiquidityObservation],
    *,
    rules: Iterable[RuleProvenance],
    decision_time: UtcDateTime,
    minimum_quote_volume: Decimal,
    warmup_requirements: Mapping[str, int],
    minimum_history_bars: int = 240,
    maximum_age: timedelta = timedelta(hours=4),
    held_instrument_ids: Iterable[str] = (),
    allow_synthetic: bool = False,
) -> PITUniverseSnapshot:
    """Strict B2 decision view; no market loader, account mutation, order or PnL interface."""
    if (
        not minimum_quote_volume.is_finite()
        or minimum_quote_volume <= 0
        or minimum_history_bars < 1
        or maximum_age <= timedelta(0)
        or not warmup_requirements
        or any(type(value) is not int or value < 1 for value in warmup_requirements.values())
    ):
        raise ValueError("AQ-PIT-UNREGISTERED-ELIGIBILITY-LIMITS")
    required = max(minimum_history_bars, *warmup_requirements.values())
    known = universe.known_events(as_of_time=decision_time)
    current = {
        row.instrument_id: row for row in universe.current_memberships(as_of_time=decision_time)
    }
    identities: set[tuple[str, str]] = set()
    for member in current.values():
        if (
            member.eligible
            and member.evidence is not None
            and (member.effective_to is None or decision_time < member.effective_to)
        ):
            identity = member.evidence.venue, member.evidence.symbol
            if identity in identities:
                raise ValueError("AQ-PIT-OVERLAPPING-SYMBOL-INCARNATIONS")
            identities.add(identity)
    liquidity = _latest_liquidity(observations, decision_time)
    rule_view = _known_rules(rules, decision_time)
    held = tuple(sorted(set(held_instrument_ids)))
    decisions: list[UniverseDecision] = []
    for instrument in sorted({row.instrument_id for row in known} | set(held)):
        member = current.get(instrument)
        base = UniverseDecision(
            instrument_uid=instrument,
            membership_id=member.membership_id if member else None,
            disposition="UNKNOWN",
            reason_codes=(),
            required_history_bars=required,
        )
        if member is None:
            reason = (
                "NOT_YET_EFFECTIVE"
                if any(row.instrument_id == instrument for row in known)
                else "MEMBERSHIP_NOT_KNOWN"
            )
            decisions.append(
                base.model_copy(
                    update={
                        "disposition": "EXCLUDED" if reason == "NOT_YET_EFFECTIVE" else "UNKNOWN",
                        "reason_codes": (reason,),
                    }
                )
            )
            continue
        if not member.eligible or (
            member.effective_to is not None and decision_time >= member.effective_to
        ):
            decisions.append(
                base.model_copy(
                    update={"disposition": "EXCLUDED", "reason_codes": ("MEMBERSHIP_NOT_TRADABLE",)}
                )
            )
            continue
        reasons: list[str] = []
        unknown = False
        proof = member.evidence
        if (
            proof is None
            or proof.availability_evidence_kind == "UNKNOWN"
            or (proof.availability_evidence_kind == "SYNTHETIC" and not allow_synthetic)
        ):
            reasons.append("MEMBERSHIP_EVIDENCE_UNVERIFIED")
            unknown = True
        row = liquidity.get(instrument)
        if row is None:
            reasons.append("LIQUIDITY_NOT_KNOWN")
            unknown = True
        else:
            base = base.model_copy(
                update={
                    "liquidity_source_sha256": row.source_sha256,
                    "trailing_quote_volume": row.trailing_quote_volume,
                }
            )
            if decision_time - row.window_end > maximum_age:
                reasons.append("LIQUIDITY_STALE")
            if row.trailing_quote_volume <= 0 or row.trailing_quote_volume < minimum_quote_volume:
                reasons.append("LIQUIDITY_BELOW_THRESHOLD")
            detail = row.evidence
            if detail is None:
                reasons.append("LIQUIDITY_DETAIL_NOT_RECEIVED")
                unknown = True
            else:
                if detail.quote_method not in {
                    "EXCHANGE_QUOTE_TURNOVER",
                    "TRADE_QUOTE_SUM",
                } and not (allow_synthetic and detail.quote_method == "SYNTHETIC"):
                    reasons.append("QUOTE_TURNOVER_NOT_EXACT")
                    unknown = True
                ordered = sorted(detail.bars, key=lambda bar: bar.close_time)
                consecutive = int(bool(ordered) and ordered[-1].close_time == row.window_end)
                for newer, older in pairwise(reversed(ordered)):
                    if not consecutive or newer.close_time - older.close_time != timedelta(hours=4):
                        break
                    consecutive += 1
                window_count = sum(
                    row.window_start < bar.close_time <= row.window_end for bar in ordered
                )
                lifecycle_bars = (
                    sum(bar.close_time > member.effective_from for bar in ordered[-consecutive:])
                    if consecutive
                    else 0
                )
                base = base.model_copy(
                    update={
                        "liquidity_detail_sha256": detail.detail_sha256,
                        "contiguous_4h_bars": consecutive,
                        "liquidity_window_bars": window_count,
                        "tradable_history_4h_bars": lifecycle_bars,
                        "liquidity_gap_count": 180 - window_count,
                    }
                )
                if row.complete_history_4h_bars != consecutive:
                    raise ValueError("AQ-PIT-CONTIGUOUS-HISTORY-COUNT-MISMATCH")
                if window_count != 180:
                    reasons.append("LIQUIDITY_WINDOW_GAP")
                    unknown = True
                if min(consecutive, lifecycle_bars) < required:
                    reasons.append("CONTIGUOUS_WARMUP_INCOMPLETE")
        active_rules = rule_view.get(instrument, [])
        if len(active_rules) > 1:
            raise ValueError("AQ-PIT-AMBIGUOUS-ACTIVE-RULE")
        if not active_rules:
            reasons.append("RULES_NOT_KNOWN")
            unknown = True
        else:
            rule = active_rules[0]
            base = base.model_copy(update={"rule_payload_sha256": rule.payload_sha256})
            selected = HistoricalRuleBook((rule.rule,)).at(
                venue_id=rule.rule.venue_id,
                instrument_id=rule.rule.instrument_id,
                event_time=decision_time,
            )
            if proof is not None and str(selected.venue_id) != proof.venue:
                raise ValueError("AQ-PIT-RULE-VENUE-IDENTITY")
            if rule.verified_kind != "ARCHIVED_EXCHANGE_RULE" and not (
                allow_synthetic and rule.verified_kind == "SYNTHETIC"
            ):
                reasons.append("RULES_UNVERIFIED")
                unknown = True
            if not selected.trading_enabled:
                reasons.append("RULES_TRADING_DISABLED")
        decisions.append(
            base.model_copy(
                update={
                    "reason_codes": tuple(reasons),
                    "disposition": "UNKNOWN" if unknown else "EXCLUDED" if reasons else "ELIGIBLE",
                }
            )
        )
    membership_snapshot = universe.snapshot(as_of_time=decision_time)
    policy_hash = canonical_sha256(
        {
            "minimum_quote_volume": str(minimum_quote_volume),
            "warmup_requirements": dict(warmup_requirements),
            "minimum_history_bars": minimum_history_bars,
            "maximum_age_seconds": str(maximum_age.total_seconds()),
            "allow_synthetic": allow_synthetic,
        }
    )
    provisional = PITUniverseSnapshot(
        snapshot_sha256="",
        membership_snapshot=membership_snapshot,
        eligible_instrument_ids=tuple(
            row.instrument_uid for row in decisions if row.disposition == "ELIGIBLE"
        ),
        decisions=tuple(decisions),
        known_future_event_ids=tuple(
            sorted(row.membership_id for row in known if row.effective_from > decision_time)
        ),
        held_instrument_ids=held,
        policy_sha256=policy_hash,
    )
    digest = canonical_sha256(provisional.model_dump(mode="json", exclude={"snapshot_sha256"}))
    return provisional.model_copy(update={"snapshot_sha256": digest})


def eligible_universe_at(
    universe: PointInTimeUniverse,
    observations: Iterable[LiquidityObservation],
    *,
    decision_time: UtcDateTime,
    minimum_quote_volume: Decimal,
    minimum_history_bars: int = 240,
    maximum_age: timedelta = timedelta(hours=4),
    strict_evidence: bool = False,
    rules: Iterable[RuleProvenance] = (),
    warmup_requirements: Mapping[str, int] | None = None,
) -> tuple[UniverseSnapshot, tuple[str, ...]]:
    """Absent/stale liquidity fails closed; future delisting revisions stay invisible."""
    if strict_evidence:
        result = audit_universe_at(
            universe,
            observations,
            rules=rules,
            decision_time=decision_time,
            minimum_quote_volume=minimum_quote_volume,
            warmup_requirements=warmup_requirements or {},
            minimum_history_bars=minimum_history_bars,
            maximum_age=maximum_age,
        )
        return result.membership_snapshot, result.eligible_instrument_ids
    if (
        not minimum_quote_volume.is_finite()
        or minimum_quote_volume < 0
        or minimum_history_bars < 1
        or maximum_age <= timedelta(0)
    ):
        raise ValueError("invalid preregistered universe eligibility limits")
    snapshot = universe.snapshot(as_of_time=decision_time)
    latest: dict[str, LiquidityObservation] = {}
    for row in observations:
        if row.available_time > decision_time or row.window_end > decision_time:
            continue
        previous = latest.get(row.instrument_id)
        if (
            previous is not None
            and (row.window_end, row.available_time)
            == (previous.window_end, previous.available_time)
            and row != previous
        ):
            raise ValueError("conflicting point-in-time liquidity observations")
        if previous is None or (row.window_end, row.available_time) > (
            previous.window_end,
            previous.available_time,
        ):
            latest[row.instrument_id] = row
    eligible = tuple(
        instrument
        for instrument in snapshot.instrument_ids
        if (row := latest.get(instrument)) is not None
        and decision_time - row.window_end <= maximum_age
        and row.complete_history_4h_bars >= minimum_history_bars
        and row.trailing_quote_volume >= minimum_quote_volume
    )
    return snapshot, eligible
