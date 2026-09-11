"""Immutable Paper ledger/read-model daily reconciliation."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from aegisquant.data.hashing import canonical_sha256, ensure_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.identifiers import AssetId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import NonNegativeDecimal


class ReconciliationStatus(StrEnum):
    CLEAR = "CLEAR"
    HALTED = "HALTED"


class PaperRuntimeSnapshot(DomainModel):
    snapshot_id: str = Field(min_length=1, max_length=255)
    business_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    captured_at: UtcDateTime
    quote_asset_id: AssetId
    order_ids: tuple[str, ...]
    fill_ids: tuple[str, ...]
    ledger_fill_ids: tuple[str, ...]
    read_model_fill_ids: tuple[str, ...]
    expected_notional: NonNegativeDecimal
    ledger_notional: NonNegativeDecimal
    expected_fees: NonNegativeDecimal
    ledger_fees: NonNegativeDecimal
    source_sha256: str

    @model_validator(mode="after")
    def validate_snapshot(self) -> PaperRuntimeSnapshot:
        ensure_sha256(self.source_sha256, field_name="source_sha256")
        for values in (
            self.order_ids,
            self.fill_ids,
            self.ledger_fill_ids,
            self.read_model_fill_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("runtime reconciliation identities must be unique")
        return self


class DailyReconciliationResult(DomainModel):
    snapshot_id: str
    status: ReconciliationStatus
    missing_ledger_fill_ids: tuple[str, ...]
    unknown_ledger_fill_ids: tuple[str, ...]
    missing_read_model_fill_ids: tuple[str, ...]
    unknown_read_model_fill_ids: tuple[str, ...]
    notional_difference: Decimal
    fee_difference: Decimal
    new_risk_allowed: bool
    authoritative_state_sha256: str
    authoritative_state_unchanged: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result(self) -> DailyReconciliationResult:
        ensure_sha256(self.authoritative_state_sha256, field_name="authoritative_state_sha256")
        has_difference = any(
            (
                self.missing_ledger_fill_ids,
                self.unknown_ledger_fill_ids,
                self.missing_read_model_fill_ids,
                self.unknown_read_model_fill_ids,
                self.notional_difference != 0,
                self.fee_difference != 0,
            )
        )
        if has_difference != (self.status is ReconciliationStatus.HALTED):
            raise ValueError("reconciliation status must reflect every difference")
        if self.new_risk_allowed != (self.status is ReconciliationStatus.CLEAR):
            raise ValueError("new risk must stop on reconciliation differences")
        if not self.authoritative_state_unchanged:
            raise ValueError("reconciliation cannot mutate authoritative facts")
        return self


def reconcile_paper_day(snapshot: PaperRuntimeSnapshot) -> DailyReconciliationResult:
    """Compare projections without repairing or rewriting any authoritative fact."""
    before = canonical_sha256(snapshot.model_dump(mode="json"))
    fills = set(snapshot.fill_ids)
    ledger = set(snapshot.ledger_fill_ids)
    read_model = set(snapshot.read_model_fill_ids)
    missing_ledger = tuple(sorted(fills - ledger))
    unknown_ledger = tuple(sorted(ledger - fills))
    missing_read = tuple(sorted(fills - read_model))
    unknown_read = tuple(sorted(read_model - fills))
    notional_difference = snapshot.ledger_notional - snapshot.expected_notional
    fee_difference = snapshot.ledger_fees - snapshot.expected_fees
    has_difference = any(
        (
            missing_ledger,
            unknown_ledger,
            missing_read,
            unknown_read,
            notional_difference != 0,
            fee_difference != 0,
        )
    )
    after = canonical_sha256(snapshot.model_dump(mode="json"))
    status = ReconciliationStatus.HALTED if has_difference else ReconciliationStatus.CLEAR
    return DailyReconciliationResult(
        snapshot_id=snapshot.snapshot_id,
        status=status,
        missing_ledger_fill_ids=missing_ledger,
        unknown_ledger_fill_ids=unknown_ledger,
        missing_read_model_fill_ids=missing_read,
        unknown_read_model_fill_ids=unknown_read,
        notional_difference=notional_difference,
        fee_difference=fee_difference,
        new_risk_allowed=not has_difference,
        authoritative_state_sha256=before,
        authoritative_state_unchanged=before == after,
        reason_codes=(
            "AQ-RUNTIME-RECONCILIATION-DIFFERENCE"
            if has_difference
            else "AQ-RUNTIME-RECONCILIATION-CLEAR",
        ),
    )
