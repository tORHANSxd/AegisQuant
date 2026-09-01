"""Create isolated P14 Read Model records and projection checkpoints.

Revision ID: 20260902_0003
Revises: 20260901_0002
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260902_0003"
down_revision: str | None = "20260901_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "read_model_records",
        sa.Column("projection", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("source_sequence", sa.BigInteger(), nullable=False),
        sa.Column("as_of_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_watermark", sa.String(length=96), nullable=False),
        sa.Column("quality_state", sa.String(length=32), nullable=False),
        sa.Column("authoritative", sa.Boolean(), nullable=False),
        sa.Column("estimated", sa.Boolean(), nullable=False),
        sa.Column("source_artifact", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "NOT (authoritative AND estimated)",
            name=op.f("ck_read_model_records_valid_authority_state"),
        ),
        sa.CheckConstraint(
            "source_sequence >= 1",
            name=op.f("ck_read_model_records_positive_source_sequence"),
        ),
        sa.CheckConstraint(
            "projected_at >= as_of_time",
            name=op.f("ck_read_model_records_valid_time_order"),
        ),
        sa.CheckConstraint(
            "quality_state IN ('LIVE', 'STALE', 'DEGRADED', 'DISCONNECTED', 'ERROR', 'ESTIMATED')",
            name=op.f("ck_read_model_records_valid_quality_state"),
        ),
        sa.PrimaryKeyConstraint("projection", "entity_id", name=op.f("pk_read_model_records")),
    )
    op.create_index(
        "ix_read_model_records_projection_as_of",
        "read_model_records",
        ["projection", "as_of_time"],
        unique=False,
    )
    op.create_table(
        "read_model_projection_checkpoints",
        sa.Column("projection", sa.String(length=64), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("source_watermark", sa.String(length=96), nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("state_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "last_sequence >= 1",
            name=op.f("ck_read_model_projection_checkpoints_positive_last_sequence"),
        ),
        sa.CheckConstraint(
            "record_count >= 0",
            name=op.f("ck_read_model_projection_checkpoints_nonnegative_record_count"),
        ),
        sa.PrimaryKeyConstraint("projection", name=op.f("pk_read_model_projection_checkpoints")),
    )
    op.create_table(
        "read_model_snapshot_state",
        sa.Column("singleton_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("rebuild_id", sa.String(length=255), nullable=False),
        sa.Column("rebuilt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event_count", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("singleton_id = 1", name=op.f("ck_read_model_snapshot_state_singleton")),
        sa.CheckConstraint(
            "source_event_count >= 1",
            name=op.f("ck_read_model_snapshot_state_positive_source_event_count"),
        ),
        sa.PrimaryKeyConstraint("singleton_id", name=op.f("pk_read_model_snapshot_state")),
    )


def downgrade() -> None:
    op.drop_table("read_model_snapshot_state")
    op.drop_table("read_model_projection_checkpoints")
    op.drop_index("ix_read_model_records_projection_as_of", table_name="read_model_records")
    op.drop_table("read_model_records")
