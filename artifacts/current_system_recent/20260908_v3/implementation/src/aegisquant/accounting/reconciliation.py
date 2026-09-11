"""Deterministic account reconciliation that never mutates authoritative balances."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Final

from aegisquant.accounting.models import (
    ReconciliationCase,
    ReconciliationDifference,
    ReconciliationDifferenceType,
    ReconciliationMode,
    ReconciliationStatus,
    SnapshotAmount,
    VenueAccountSnapshot,
)
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import ReconciliationCaseId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result, validate_decimal

ZERO_TOLERANCE: Final = Decimal("0")


def _amounts(values: tuple[SnapshotAmount, ...]) -> dict[str, Decimal]:
    return {item.key: item.amount for item in values}


def _amount_differences(
    *,
    dimension: str,
    local: tuple[SnapshotAmount, ...],
    venue: tuple[SnapshotAmount, ...],
    tolerance: Decimal,
) -> list[ReconciliationDifference]:
    local_by_key = _amounts(local)
    venue_by_key = _amounts(venue)
    differences: list[ReconciliationDifference] = []
    for key in sorted(local_by_key.keys() | venue_by_key.keys()):
        local_value = local_by_key.get(key)
        venue_value = venue_by_key.get(key)
        if local_value is None:
            difference_type = ReconciliationDifferenceType.MISSING_LOCAL_EVENT
        elif venue_value is None:
            difference_type = ReconciliationDifferenceType.MISSING_VENUE_EVENT
        elif local_value == venue_value:
            continue
        elif abs(local_value - venue_value) <= tolerance:
            difference_type = ReconciliationDifferenceType.ROUNDING
        elif dimension == "position":
            difference_type = ReconciliationDifferenceType.POSITION_MISMATCH
        elif dimension == "fee":
            difference_type = ReconciliationDifferenceType.FEE_MISMATCH
        elif dimension == "funding":
            difference_type = ReconciliationDifferenceType.UNEXPLAINED
        else:
            difference_type = ReconciliationDifferenceType.BALANCE_MISMATCH
        differences.append(
            ReconciliationDifference(
                difference_type=difference_type,
                dimension=dimension,
                key=key,
                local_value="MISSING" if local_value is None else str(local_value),
                venue_value="MISSING" if venue_value is None else str(venue_value),
                evidence=(
                    f"local:{dimension}:{key}:{local_value}",
                    f"venue:{dimension}:{key}:{venue_value}",
                ),
            )
        )
    return differences


def _identifier_differences(
    *,
    dimension: str,
    local: tuple[str, ...],
    venue: tuple[str, ...],
) -> list[ReconciliationDifference]:
    local_counts = Counter(local)
    venue_counts = Counter(venue)
    local_ids = set(local_counts)
    venue_ids = set(venue_counts)
    differences: list[ReconciliationDifference] = []
    for key in sorted(local_ids | venue_ids):
        local_count = local_counts[key]
        venue_count = venue_counts[key]
        if local_count > 1 or venue_count > 1:
            differences.append(
                ReconciliationDifference(
                    difference_type=ReconciliationDifferenceType.DUPLICATE_EVENT,
                    dimension=dimension,
                    key=key,
                    local_value=str(local_count),
                    venue_value=str(venue_count),
                    evidence=(
                        f"local:{dimension}:{key}:count={local_count}",
                        f"venue:{dimension}:{key}:count={venue_count}",
                    ),
                )
            )
    for key in sorted(local_ids ^ venue_ids):
        missing_locally = key not in local_ids
        if missing_locally and dimension == "open_order":
            difference_type = ReconciliationDifferenceType.UNKNOWN_ORDER
        elif missing_locally:
            difference_type = ReconciliationDifferenceType.MISSING_LOCAL_EVENT
        else:
            difference_type = ReconciliationDifferenceType.MISSING_VENUE_EVENT
        differences.append(
            ReconciliationDifference(
                difference_type=difference_type,
                dimension=dimension,
                key=key,
                local_value="MISSING" if missing_locally else "PRESENT",
                venue_value="PRESENT" if missing_locally else "MISSING",
                evidence=(
                    f"local:{dimension}:{key}:{key in local_ids}",
                    f"venue:{dimension}:{key}:{key in venue_ids}",
                ),
            )
        )
    return differences


def reconcile_account_snapshots(
    *,
    local: VenueAccountSnapshot,
    venue: VenueAccountSnapshot,
    mode: ReconciliationMode,
    opened_at: UtcDateTime,
    tolerance: Decimal = ZERO_TOLERANCE,
) -> ReconciliationCase:
    """Compare facts and return a blocking case; never alter either snapshot."""
    tolerance = validate_decimal(tolerance)
    if tolerance < 0:
        raise ValueError("reconciliation tolerance cannot be negative")
    if local.venue != venue.venue:
        raise ValueError("cannot reconcile snapshots from different venues")
    differences = _amount_differences(
        dimension="balance",
        local=local.balances,
        venue=venue.balances,
        tolerance=tolerance,
    )
    differences.extend(
        _amount_differences(
            dimension="position",
            local=local.positions,
            venue=venue.positions,
            tolerance=tolerance,
        )
    )
    differences.extend(
        _amount_differences(
            dimension="fee",
            local=local.fees,
            venue=venue.fees,
            tolerance=tolerance,
        )
    )
    differences.extend(
        _amount_differences(
            dimension="funding",
            local=local.funding,
            venue=venue.funding,
            tolerance=tolerance,
        )
    )
    differences.extend(
        _identifier_differences(
            dimension="recent_order",
            local=local.recent_order_ids,
            venue=venue.recent_order_ids,
        )
    )
    differences.extend(
        _identifier_differences(
            dimension="open_order",
            local=local.open_order_ids,
            venue=venue.open_order_ids,
        )
    )
    differences.extend(
        _identifier_differences(
            dimension="fill",
            local=local.fill_ids,
            venue=venue.fill_ids,
        )
    )
    ordered = tuple(
        sorted(
            differences,
            key=lambda item: (item.dimension, item.key, item.difference_type.value),
        )
    )
    if not ordered:
        status = ReconciliationStatus.CLEAR
    elif mode is ReconciliationMode.CONTINUOUS:
        status = ReconciliationStatus.REVIEW_REQUIRED
    else:
        status = ReconciliationStatus.HALTED
    identity = {
        "mode": mode.value,
        "local_snapshot_id": str(local.account_snapshot_id),
        "venue_snapshot_id": str(venue.account_snapshot_id),
        "tolerance": str(canonical_result(tolerance)),
        "differences": [item.model_dump(mode="json") for item in ordered],
    }
    return ReconciliationCase(
        reconciliation_case_id=ReconciliationCaseId(canonical_sha256(identity)),
        mode=mode,
        local_snapshot_id=local.account_snapshot_id,
        venue_snapshot_id=venue.account_snapshot_id,
        opened_at=opened_at,
        status=status,
        new_orders_allowed=status is ReconciliationStatus.CLEAR,
        differences=ordered,
    )


def require_reconciliation_clear(case: ReconciliationCase) -> None:
    """Enforce the no-new-orders gate at startup, continuously, and after reconnect."""
    if not case.new_orders_allowed:
        raise RuntimeError(f"AQ-RECONCILIATION-BLOCKED:{case.reconciliation_case_id}")
