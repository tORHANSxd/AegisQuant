"""SQLAlchemy Core metadata for the P01 PostgreSQL baseline."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
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
