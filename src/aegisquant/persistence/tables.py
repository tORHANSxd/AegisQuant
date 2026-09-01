"""SQLAlchemy Core metadata for the P01 PostgreSQL baseline."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

provider_registry = Table(
    "provider_registry",
    metadata,
    Column("provider_id", String(255), primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("status IN ('ACTIVE', 'RESTRICTED', 'DISABLED')", name="valid_status"),
)

source_document_registry = Table(
    "source_document_registry",
    metadata,
    Column("source_document_id", String(255), primary_key=True),
    Column(
        "provider_id",
        String(255),
        ForeignKey("provider_registry.provider_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("provider_native_id", String(255), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("available_time", DateTime(timezone=True), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    UniqueConstraint("provider_id", "provider_native_id", "revision"),
    CheckConstraint("revision >= 1", name="positive_revision"),
)

instrument_registry = Table(
    "instrument_registry",
    metadata,
    Column("instrument_id", String(255), nullable=False),
    Column("version", Integer, nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_to", DateTime(timezone=True), nullable=True),
    Column("source_snapshot_id", String(255), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    UniqueConstraint("instrument_id", "version"),
    CheckConstraint("version >= 1", name="positive_version"),
    CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_interval"),
)

event_schema_registry = Table(
    "event_schema_registry",
    metadata,
    Column("schema_name", String(255), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("schema_sha256", String(64), nullable=False),
    Column("compatibility", String(32), nullable=False),
    Column(
        "registered_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    UniqueConstraint("schema_name", "schema_version"),
    CheckConstraint(
        "compatibility IN ('BACKWARD', 'FORWARD', 'FULL', 'NONE')",
        name="valid_compatibility",
    ),
)

domain_events = Table(
    "domain_events",
    metadata,
    Column("event_id", String(255), primary_key=True),
    Column("event_type", String(255), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("available_time", DateTime(timezone=True), nullable=False),
    Column("ingest_time", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("content_hash", String(64), nullable=False, unique=True),
    Column("idempotency_key", String(255), nullable=False, unique=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("ingest_time >= available_time", name="valid_time_order"),
)

outbox_messages = Table(
    "outbox_messages",
    metadata,
    Column("message_id", String(255), primary_key=True),
    Column(
        "event_id",
        String(255),
        ForeignKey("domain_events.event_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    Column("topic", String(255), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("idempotency_key", String(255), nullable=False, unique=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("publish_attempts", Integer, nullable=False, server_default=text("0")),
    CheckConstraint("publish_attempts >= 0", name="nonnegative_attempts"),
)

Index(
    "ix_outbox_messages_pending",
    outbox_messages.c.created_at,
    postgresql_where=outbox_messages.c.published_at.is_(None),
)

inbox_messages = Table(
    "inbox_messages",
    metadata,
    Column("consumer_name", String(255), primary_key=True),
    Column("message_id", String(255), primary_key=True),
    Column("idempotency_key", String(255), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column(
        "processed_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column("result_code", String(64), nullable=False),
    UniqueConstraint("consumer_name", "idempotency_key"),
)

accounting_accounts = Table(
    "accounting_accounts",
    metadata,
    Column("account_id", String(255), primary_key=True),
    Column("chart_version", String(64), primary_key=True),
    Column("role", String(64), nullable=False),
    Column("account_type", String(32), nullable=False),
    Column("normal_balance", String(16), nullable=False),
    Column("venue", String(64), nullable=False),
    Column("subject", String(255), nullable=False),
    Column("economic_balance", Boolean, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "account_type IN ('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE', 'MEMO')",
        name="valid_account_type",
    ),
    CheckConstraint("normal_balance IN ('DEBIT', 'CREDIT')", name="valid_normal_balance"),
)

accounting_entry_templates = Table(
    "accounting_entry_templates",
    metadata,
    Column("entry_template_id", String(255), primary_key=True),
    Column("template_version", String(64), primary_key=True),
    Column("event_type", String(64), nullable=False),
    Column("effective_from", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
)

accounting_ledger_entries = Table(
    "accounting_ledger_entries",
    metadata,
    Column("journal_entry_id", String(255), primary_key=True),
    Column("ledger_sequence", BigInteger, Identity(), nullable=False, unique=True),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("policy_version", String(64), nullable=False),
    Column("chart_version", String(64), nullable=False),
    Column("entry_template_id", String(255), nullable=False),
    Column("template_version", String(64), nullable=False),
    Column("source_fill_id", String(255), nullable=True, unique=True),
    Column("source_order_intent_id", String(255), nullable=True),
    Column("idempotency_key", String(255), nullable=False, unique=True),
    Column("command_hash", String(64), nullable=False, unique=True),
    Column("previous_hash", String(64), nullable=False),
    Column("event_hash", String(64), nullable=False, unique=True),
    Column("payload", JSONB, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    ForeignKeyConstraint(
        ["entry_template_id", "template_version"],
        [
            "accounting_entry_templates.entry_template_id",
            "accounting_entry_templates.template_version",
        ],
        ondelete="RESTRICT",
    ),
    CheckConstraint("recorded_at >= event_time", name="valid_time_order"),
)

accounting_ledger_postings = Table(
    "accounting_ledger_postings",
    metadata,
    Column("posting_id", String(255), primary_key=True),
    Column(
        "journal_entry_id",
        String(255),
        ForeignKey("accounting_ledger_entries.journal_entry_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("posting_sequence", Integer, nullable=False),
    Column("account_id", String(255), nullable=False),
    Column("chart_version", String(64), nullable=False),
    Column("side", String(16), nullable=False),
    Column("asset_id", String(255), nullable=False),
    Column("amount", Numeric(), nullable=False),
    Column("memo", Text, nullable=False),
    ForeignKeyConstraint(
        ["account_id", "chart_version"],
        ["accounting_accounts.account_id", "accounting_accounts.chart_version"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("journal_entry_id", "posting_sequence"),
    CheckConstraint("side IN ('DEBIT', 'CREDIT')", name="valid_side"),
    CheckConstraint("amount > 0", name="positive_amount"),
)

accounting_position_lots = Table(
    "accounting_position_lots",
    metadata,
    Column("position_lot_id", String(255), primary_key=True),
    Column("account_id", String(255), nullable=False),
    Column("instrument_id", String(255), nullable=False),
    Column("side", String(16), nullable=False),
    Column("remaining_quantity", Numeric(), nullable=False),
    Column("status", String(16), nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True), nullable=True),
    Column("source_fill_id", String(255), nullable=False),
    Column("last_journal_entry_id", String(255), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("content_hash", String(64), nullable=False),
    CheckConstraint("side IN ('LONG', 'SHORT')", name="valid_side"),
    CheckConstraint("status IN ('OPEN', 'CLOSED')", name="valid_status"),
    CheckConstraint("remaining_quantity >= 0", name="nonnegative_remaining"),
    CheckConstraint(
        "(status = 'OPEN' AND remaining_quantity > 0 AND closed_at IS NULL) OR "
        "(status = 'CLOSED' AND remaining_quantity = 0 AND closed_at IS NOT NULL)",
        name="valid_lifecycle",
    ),
)

Index(
    "ix_accounting_position_lots_instrument_open",
    accounting_position_lots.c.instrument_id,
    postgresql_where=accounting_position_lots.c.status == "OPEN",
)

account_reconciliation_cases = Table(
    "account_reconciliation_cases",
    metadata,
    Column("reconciliation_case_id", String(255), primary_key=True),
    Column("mode", String(16), nullable=False),
    Column("status", String(32), nullable=False),
    Column("new_orders_allowed", Boolean, nullable=False),
    Column("local_snapshot_id", String(255), nullable=False),
    Column("venue_snapshot_id", String(255), nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("mode IN ('STARTUP', 'CONTINUOUS', 'RECONNECT')", name="valid_mode"),
    CheckConstraint("status IN ('CLEAR', 'REVIEW_REQUIRED', 'HALTED')", name="valid_status"),
    CheckConstraint("new_orders_allowed = (status = 'CLEAR')", name="valid_order_gate"),
)

Index(
    "ix_account_reconciliation_cases_status",
    account_reconciliation_cases.c.status,
    account_reconciliation_cases.c.opened_at,
)

daily_ledger_snapshots = Table(
    "daily_ledger_snapshots",
    metadata,
    Column("ledger_snapshot_id", String(255), primary_key=True),
    Column("snapshot_date", Date, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("policy_version", String(64), nullable=False),
    Column("ledger_entry_count", BigInteger, nullable=False),
    Column("last_event_hash", String(64), nullable=False),
    Column("ledger_state_hash", String(64), nullable=False),
    Column("previous_snapshot_hash", String(64), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("public_key_base64", Text, nullable=False),
    Column("signature_base64", Text, nullable=False),
    Column("signature_algorithm", String(16), nullable=False),
    Column("payload", JSONB, nullable=False),
    UniqueConstraint("snapshot_date", "policy_version"),
    CheckConstraint("ledger_entry_count >= 0", name="nonnegative_entry_count"),
    CheckConstraint("signature_algorithm = 'Ed25519'", name="valid_signature_algorithm"),
)

read_model_records = Table(
    "read_model_records",
    metadata,
    Column("projection", String(64), primary_key=True),
    Column("entity_id", String(255), primary_key=True),
    Column("schema_version", String(32), nullable=False),
    Column("source_sequence", BigInteger, nullable=False),
    Column("as_of_time", DateTime(timezone=True), nullable=False),
    Column("projected_at", DateTime(timezone=True), nullable=False),
    Column("source_watermark", String(96), nullable=False),
    Column("quality_state", String(32), nullable=False),
    Column("authoritative", Boolean, nullable=False),
    Column("estimated", Boolean, nullable=False),
    Column("source_artifact", Text, nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("content_sha256", String(64), nullable=False),
    CheckConstraint("source_sequence >= 1", name="positive_source_sequence"),
    CheckConstraint("projected_at >= as_of_time", name="valid_time_order"),
    CheckConstraint("NOT (authoritative AND estimated)", name="valid_authority_state"),
    CheckConstraint(
        "quality_state IN ('LIVE', 'STALE', 'DEGRADED', 'DISCONNECTED', 'ERROR', 'ESTIMATED')",
        name="valid_quality_state",
    ),
)

Index(
    "ix_read_model_records_projection_as_of",
    read_model_records.c.projection,
    read_model_records.c.as_of_time,
)

read_model_projection_checkpoints = Table(
    "read_model_projection_checkpoints",
    metadata,
    Column("projection", String(64), primary_key=True),
    Column("last_sequence", BigInteger, nullable=False),
    Column("source_watermark", String(96), nullable=False),
    Column("projected_at", DateTime(timezone=True), nullable=False),
    Column("record_count", Integer, nullable=False),
    Column("state_sha256", String(64), nullable=False),
    CheckConstraint("last_sequence >= 1", name="positive_last_sequence"),
    CheckConstraint("record_count >= 0", name="nonnegative_record_count"),
)

read_model_snapshot_state = Table(
    "read_model_snapshot_state",
    metadata,
    Column("singleton_id", Integer, primary_key=True),
    Column("schema_version", String(32), nullable=False),
    Column("rebuild_id", String(255), nullable=False),
    Column("rebuilt_at", DateTime(timezone=True), nullable=False),
    Column("source_event_count", BigInteger, nullable=False),
    Column("content_sha256", String(64), nullable=False),
    CheckConstraint("singleton_id = 1", name="singleton"),
    CheckConstraint("source_event_count >= 1", name="positive_source_event_count"),
)
