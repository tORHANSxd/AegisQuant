"""Atomic PostgreSQL persistence for P05 ledger and reconciliation facts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import Connection, or_, select
from sqlalchemy.dialects.postgresql import insert

from aegisquant.accounting.models import (
    ChartOfAccounts,
    DailyLedgerSnapshot,
    EntryTemplate,
    LedgerRecord,
    LotAction,
    PositionLotState,
    ReconciliationCase,
)
from aegisquant.data.hashing import canonical_json_bytes, canonical_sha256
from aegisquant.persistence.tables import (
    account_reconciliation_cases,
    accounting_accounts,
    accounting_entry_templates,
    accounting_ledger_entries,
    accounting_ledger_postings,
    accounting_position_lots,
    daily_ledger_snapshots,
)


def persist_accounting_configuration(
    connection: Connection,
    *,
    chart: ChartOfAccounts,
    templates: tuple[EntryTemplate, ...],
) -> None:
    """Persist immutable chart and template versions, rejecting version collisions."""
    for definition in chart.definitions:
        payload = definition.model_dump(mode="json")
        content_hash = canonical_sha256(payload)
        statement = (
            insert(accounting_accounts)
            .values(
                account_id=str(definition.account_id),
                chart_version=chart.version,
                role=definition.role.value,
                account_type=definition.account_type.value,
                normal_balance=definition.normal_balance.value,
                venue=definition.venue,
                subject=definition.subject,
                economic_balance=definition.economic_balance,
                content_hash=content_hash,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    accounting_accounts.c.account_id,
                    accounting_accounts.c.chart_version,
                ]
            )
            .returning(accounting_accounts.c.account_id)
        )
        if connection.execute(statement).scalar_one_or_none() is None:
            existing_hash = connection.scalar(
                select(accounting_accounts.c.content_hash).where(
                    accounting_accounts.c.account_id == str(definition.account_id),
                    accounting_accounts.c.chart_version == chart.version,
                )
            )
            if existing_hash != content_hash:
                raise ValueError("AQ-LEDGER-CHART-VERSION-CONFLICT")
    for template in templates:
        payload = template.model_dump(mode="json")
        content_hash = canonical_sha256(payload)
        statement = (
            insert(accounting_entry_templates)
            .values(
                entry_template_id=str(template.entry_template_id),
                template_version=template.version,
                event_type=template.event_type,
                effective_from=template.effective_from,
                payload=payload,
                content_hash=content_hash,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    accounting_entry_templates.c.entry_template_id,
                    accounting_entry_templates.c.template_version,
                ]
            )
            .returning(accounting_entry_templates.c.entry_template_id)
        )
        if connection.execute(statement).scalar_one_or_none() is None:
            existing_hash = connection.scalar(
                select(accounting_entry_templates.c.content_hash).where(
                    accounting_entry_templates.c.entry_template_id
                    == str(template.entry_template_id),
                    accounting_entry_templates.c.template_version == template.version,
                )
            )
            if existing_hash != content_hash:
                raise ValueError("AQ-LEDGER-TEMPLATE-VERSION-CONFLICT")


def _closed_lot_payload(
    state: PositionLotState, *, closed_at: datetime
) -> tuple[dict[str, object], Decimal, datetime]:
    payload = cast(dict[str, object], state.model_dump(mode="json"))
    payload["remaining_quantity"] = "0"
    payload["closed_at"] = closed_at.isoformat()
    return payload, Decimal("0"), closed_at


def _upsert_lot_projection(connection: Connection, *, record: LedgerRecord) -> None:
    for change in record.lot_changes:
        if change.action is LotAction.CLOSE:
            if change.lot_before is None:
                raise RuntimeError("validated close change lost its prior lot")
            state = change.lot_before
            payload, remaining, closed_at = _closed_lot_payload(
                state, closed_at=record.journal_entry.event_time
            )
            status = "CLOSED"
        else:
            if change.lot_after is None:
                raise RuntimeError("validated open/reduce change lost its current lot")
            state = change.lot_after
            payload = cast(dict[str, object], state.model_dump(mode="json"))
            remaining = state.remaining_quantity
            closed_at = state.closed_at
            status = "OPEN"
        values = {
            "position_lot_id": str(state.position_lot_id),
            "account_id": str(state.account_id),
            "instrument_id": str(state.instrument_id),
            "side": state.side.value,
            "remaining_quantity": remaining,
            "status": status,
            "opened_at": state.opened_at,
            "closed_at": closed_at,
            "source_fill_id": str(state.source_fill_id),
            "last_journal_entry_id": str(record.journal_entry.journal_entry_id),
            "payload": payload,
            "content_hash": canonical_sha256(payload),
        }
        connection.execute(
            insert(accounting_position_lots)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[accounting_position_lots.c.position_lot_id],
                set_={key: value for key, value in values.items() if key != "position_lot_id"},
            )
        )


def append_ledger_record(connection: Connection, *, record: LedgerRecord) -> bool:
    """Append a record and its postings/projection atomically in the caller transaction."""
    payload = record.model_dump(mode="json")
    journal = record.journal_entry
    statement = (
        insert(accounting_ledger_entries)
        .values(
            journal_entry_id=str(journal.journal_entry_id),
            event_time=journal.event_time,
            recorded_at=journal.recorded_at,
            policy_version=record.policy_version,
            chart_version=record.chart_version,
            entry_template_id=str(record.entry_template_id),
            template_version=record.template_version,
            source_fill_id=str(record.source_fill_id) if record.source_fill_id else None,
            source_order_intent_id=(
                str(record.source_order_intent_id) if record.source_order_intent_id else None
            ),
            idempotency_key=str(record.idempotency_key),
            command_hash=record.command_hash,
            previous_hash=record.previous_hash,
            event_hash=record.event_hash,
            payload=payload,
        )
        .on_conflict_do_nothing()
        .returning(accounting_ledger_entries.c.journal_entry_id)
    )
    if connection.execute(statement).scalar_one_or_none() is None:
        conflicts = [
            accounting_ledger_entries.c.journal_entry_id == str(journal.journal_entry_id),
            accounting_ledger_entries.c.idempotency_key == str(record.idempotency_key),
            accounting_ledger_entries.c.command_hash == record.command_hash,
            accounting_ledger_entries.c.event_hash == record.event_hash,
        ]
        if record.source_fill_id is not None:
            conflicts.append(
                accounting_ledger_entries.c.source_fill_id == str(record.source_fill_id)
            )
        existing_hashes = connection.execute(
            select(
                accounting_ledger_entries.c.command_hash,
                accounting_ledger_entries.c.event_hash,
            ).where(or_(*conflicts))
        ).all()
        if existing_hashes and all(
            row.command_hash == record.command_hash and row.event_hash == record.event_hash
            for row in existing_hashes
        ):
            return False
        raise ValueError("AQ-LEDGER-PERSISTENCE-IDEMPOTENCY-CONFLICT")
    connection.execute(
        accounting_ledger_postings.insert(),
        [
            {
                "posting_id": str(posting.posting_id),
                "journal_entry_id": str(journal.journal_entry_id),
                "posting_sequence": sequence,
                "account_id": str(posting.account_id),
                "chart_version": record.chart_version,
                "side": posting.side.value,
                "asset_id": str(posting.amount.asset_id),
                "amount": posting.amount.amount,
                "memo": posting.memo,
            }
            for sequence, posting in enumerate(journal.postings)
        ],
    )
    _upsert_lot_projection(connection, record=record)
    return True


def load_ledger_records(connection: Connection) -> tuple[LedgerRecord, ...]:
    payloads = connection.scalars(
        select(accounting_ledger_entries.c.payload).order_by(
            accounting_ledger_entries.c.ledger_sequence
        )
    ).all()
    return tuple(
        LedgerRecord.model_validate_json(canonical_json_bytes(cast(object, payload)))
        for payload in payloads
    )


def store_reconciliation_case(connection: Connection, *, case: ReconciliationCase) -> bool:
    payload = case.model_dump(mode="json")
    content_hash = canonical_sha256(payload)
    statement = (
        insert(account_reconciliation_cases)
        .values(
            reconciliation_case_id=str(case.reconciliation_case_id),
            mode=case.mode.value,
            status=case.status.value,
            new_orders_allowed=case.new_orders_allowed,
            local_snapshot_id=str(case.local_snapshot_id),
            venue_snapshot_id=str(case.venue_snapshot_id),
            opened_at=case.opened_at,
            payload=payload,
            content_hash=content_hash,
        )
        .on_conflict_do_nothing(
            index_elements=[account_reconciliation_cases.c.reconciliation_case_id]
        )
        .returning(account_reconciliation_cases.c.reconciliation_case_id)
    )
    if connection.execute(statement).scalar_one_or_none() is not None:
        return True
    existing_hash = connection.scalar(
        select(account_reconciliation_cases.c.content_hash).where(
            account_reconciliation_cases.c.reconciliation_case_id
            == str(case.reconciliation_case_id)
        )
    )
    if existing_hash != content_hash:
        raise ValueError("AQ-RECONCILIATION-PERSISTENCE-CONFLICT")
    return False


def store_daily_snapshot(connection: Connection, *, snapshot: DailyLedgerSnapshot) -> bool:
    payload = snapshot.model_dump(mode="json")
    statement = (
        insert(daily_ledger_snapshots)
        .values(
            ledger_snapshot_id=str(snapshot.ledger_snapshot_id),
            snapshot_date=snapshot.snapshot_date,
            created_at=snapshot.created_at,
            policy_version=snapshot.policy_version,
            ledger_entry_count=snapshot.ledger_entry_count,
            last_event_hash=snapshot.last_event_hash,
            ledger_state_hash=snapshot.ledger_state_hash,
            previous_snapshot_hash=snapshot.previous_snapshot_hash,
            payload_hash=snapshot.payload_hash,
            public_key_base64=snapshot.public_key_base64,
            signature_base64=snapshot.signature_base64,
            signature_algorithm=snapshot.signature_algorithm,
            payload=payload,
        )
        .on_conflict_do_nothing()
        .returning(daily_ledger_snapshots.c.ledger_snapshot_id)
    )
    if connection.execute(statement).scalar_one_or_none() is not None:
        return True
    existing = connection.execute(
        select(
            daily_ledger_snapshots.c.ledger_snapshot_id,
            daily_ledger_snapshots.c.payload_hash,
        ).where(
            or_(
                daily_ledger_snapshots.c.ledger_snapshot_id == str(snapshot.ledger_snapshot_id),
                (
                    (daily_ledger_snapshots.c.snapshot_date == snapshot.snapshot_date)
                    & (daily_ledger_snapshots.c.policy_version == snapshot.policy_version)
                ),
            )
        )
    ).one_or_none()
    if (
        existing is None
        or existing.ledger_snapshot_id != str(snapshot.ledger_snapshot_id)
        or existing.payload_hash != snapshot.payload_hash
    ):
        raise ValueError("AQ-LEDGER-DAILY-SNAPSHOT-CONFLICT")
    return False
