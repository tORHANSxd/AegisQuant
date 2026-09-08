"""Atomic fill, ledger, domain-event, and Outbox persistence boundary."""

from __future__ import annotations

from pydantic import Field
from sqlalchemy import Engine

from aegisquant.accounting.ledger import LedgerEngine
from aegisquant.accounting.models import AccountingInstrument
from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import Fill
from aegisquant.persistence.accounting import (
    append_ledger_record,
    persist_accounting_configuration,
)
from aegisquant.persistence.messaging import StoredEvent, append_event_with_outbox


class AtomicFillOutcome(DomainModel):
    fill_id: str
    ledger_entry_id: str
    event_id: str
    outbox_message_id: str
    inserted: bool
    authoritative_ledger_entry_count: int = Field(ge=1)


def persist_fill_atomically(
    *,
    engine: Engine,
    ledger: LedgerEngine,
    fill: Fill,
    instrument: AccountingInstrument,
    topic: str = "execution.fills.v1",
) -> AtomicFillOutcome:
    """Commit all durable facts first; only then advance the in-memory ledger."""
    shadow = ledger.rebuild()
    candidate = shadow.process_fill(fill, instrument)
    record = candidate.applied_fill.record
    event_id = f"execution-fill-{fill.fill_id}"
    message_id = f"outbox-{canonical_sha256({'event_id': event_id})[:32]}"
    payload = {
        "fill": fill.model_dump(mode="json"),
        "ledger_entry_id": str(record.journal_entry.journal_entry_id),
        "ledger_event_hash": record.event_hash,
    }
    with engine.begin() as connection:
        persist_accounting_configuration(
            connection,
            chart=shadow.chart.snapshot(),
            templates=tuple(shadow.templates.values()),
        )
        ledger_inserted = append_ledger_record(connection, record=record)
        event_inserted = append_event_with_outbox(
            connection,
            event=StoredEvent(
                event_id=event_id,
                event_type="EXECUTION_FILL_ACCOUNTED",
                schema_version="1.0.0",
                available_time=fill.available_time,
                ingest_time=fill.ingest_time,
                payload=payload,
                idempotency_key=f"execution-fill-event-{fill.idempotency_key}",
            ),
            message_id=message_id,
            topic=topic,
            outbox_idempotency_key=f"execution-fill-outbox-{fill.idempotency_key}",
        )
        if ledger_inserted != event_inserted:
            raise RuntimeError("AQ-EXEC-FILL-ATOMICITY-CONFLICT")
    authoritative = ledger.process_fill(fill, instrument)
    if authoritative.inserted != candidate.inserted:
        raise RuntimeError("AQ-EXEC-AUTHORITATIVE-LEDGER-DIVERGED")
    return AtomicFillOutcome(
        fill_id=str(fill.fill_id),
        ledger_entry_id=str(record.journal_entry.journal_entry_id),
        event_id=event_id,
        outbox_message_id=message_id,
        inserted=ledger_inserted,
        authoritative_ledger_entry_count=len(ledger.records),
    )
