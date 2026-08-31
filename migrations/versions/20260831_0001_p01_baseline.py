"""Create P01 event, messaging, and registry baseline.

Revision ID: 20260831_0001
Revises: None
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_registry",
        sa.Column("provider_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'RESTRICTED', 'DISABLED')",
            name=op.f("ck_provider_registry_valid_status"),
        ),
        sa.PrimaryKeyConstraint("provider_id", name=op.f("pk_provider_registry")),
    )
    op.create_table(
        "event_schema_registry",
        sa.Column("schema_name", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("compatibility", sa.String(length=32), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "compatibility IN ('BACKWARD', 'FORWARD', 'FULL', 'NONE')",
            name=op.f("ck_event_schema_registry_valid_compatibility"),
        ),
        sa.UniqueConstraint(
            "schema_name",
            "schema_version",
            name=op.f("uq_event_schema_registry_schema_name"),
        ),
    )
    op.create_table(
        "instrument_registry",
        sa.Column("instrument_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_snapshot_id", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_instrument_registry_positive_version")),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f("ck_instrument_registry_valid_interval"),
        ),
        sa.UniqueConstraint(
            "instrument_id", "version", name=op.f("uq_instrument_registry_instrument_id")
        ),
    )
    op.create_table(
        "source_document_registry",
        sa.Column("source_document_id", sa.String(length=255), nullable=False),
        sa.Column("provider_id", sa.String(length=255), nullable=False),
        sa.Column("provider_native_id", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_source_document_registry_positive_revision")
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider_registry.provider_id"],
            name=op.f("fk_source_document_registry_provider_id_provider_registry"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_document_id", name=op.f("pk_source_document_registry")),
        sa.UniqueConstraint(
            "provider_id",
            "provider_native_id",
            "revision",
            name=op.f("uq_source_document_registry_provider_id"),
        ),
    )
    op.create_table(
        "domain_events",
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingest_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ingest_time >= available_time", name=op.f("ck_domain_events_valid_time_order")
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_domain_events")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_domain_events_content_hash")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_domain_events_idempotency_key")),
    )
    op.create_table(
        "outbox_messages",
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "publish_attempts >= 0", name=op.f("ck_outbox_messages_nonnegative_attempts")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["domain_events.event_id"],
            name=op.f("fk_outbox_messages_event_id_domain_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_outbox_messages")),
        sa.UniqueConstraint("event_id", name=op.f("uq_outbox_messages_event_id")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_outbox_messages_idempotency_key")),
    )
    op.create_index(
        "ix_outbox_messages_pending",
        "outbox_messages",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_table(
        "inbox_messages",
        sa.Column("consumer_name", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("result_code", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("consumer_name", "message_id", name=op.f("pk_inbox_messages")),
        sa.UniqueConstraint(
            "consumer_name",
            "idempotency_key",
            name=op.f("uq_inbox_messages_consumer_name"),
        ),
    )


def downgrade() -> None:
    op.drop_table("inbox_messages")
    op.drop_index(
        "ix_outbox_messages_pending",
        table_name="outbox_messages",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_table("outbox_messages")
    op.drop_table("domain_events")
    op.drop_table("source_document_registry")
    op.drop_table("instrument_registry")
    op.drop_table("event_schema_registry")
    op.drop_table("provider_registry")
