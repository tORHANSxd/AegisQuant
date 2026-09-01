"""Create P05 authoritative accounting and reconciliation storage.

Revision ID: 20260901_0002
Revises: 20260831_0001
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0002"
down_revision: str | None = "20260831_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounting_accounts",
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("chart_version", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("normal_balance", sa.String(length=16), nullable=False),
        sa.Column("venue", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("economic_balance", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "account_type IN ('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE', 'MEMO')",
            name=op.f("ck_accounting_accounts_valid_account_type"),
        ),
        sa.CheckConstraint(
            "normal_balance IN ('DEBIT', 'CREDIT')",
            name=op.f("ck_accounting_accounts_valid_normal_balance"),
        ),
        sa.PrimaryKeyConstraint("account_id", "chart_version", name=op.f("pk_accounting_accounts")),
    )
    op.create_table(
        "accounting_entry_templates",
        sa.Column("entry_template_id", sa.String(length=255), nullable=False),
        sa.Column("template_version", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "entry_template_id",
            "template_version",
            name=op.f("pk_accounting_entry_templates"),
        ),
    )
    op.create_table(
        "accounting_ledger_entries",
        sa.Column("journal_entry_id", sa.String(length=255), nullable=False),
        sa.Column("ledger_sequence", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("chart_version", sa.String(length=64), nullable=False),
        sa.Column("entry_template_id", sa.String(length=255), nullable=False),
        sa.Column("template_version", sa.String(length=64), nullable=False),
        sa.Column("source_fill_id", sa.String(length=255), nullable=True),
        sa.Column("source_order_intent_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "recorded_at >= event_time",
            name=op.f("ck_accounting_ledger_entries_valid_time_order"),
        ),
        sa.ForeignKeyConstraint(
            ["entry_template_id", "template_version"],
            [
                "accounting_entry_templates.entry_template_id",
                "accounting_entry_templates.template_version",
            ],
            name=op.f("fk_accounting_ledger_entries_entry_template_id_accounting_entry_templates"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("journal_entry_id", name=op.f("pk_accounting_ledger_entries")),
        sa.UniqueConstraint("command_hash", name=op.f("uq_accounting_ledger_entries_command_hash")),
        sa.UniqueConstraint("event_hash", name=op.f("uq_accounting_ledger_entries_event_hash")),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_accounting_ledger_entries_idempotency_key"),
        ),
        sa.UniqueConstraint(
            "ledger_sequence",
            name=op.f("uq_accounting_ledger_entries_ledger_sequence"),
        ),
        sa.UniqueConstraint(
            "source_fill_id", name=op.f("uq_accounting_ledger_entries_source_fill_id")
        ),
    )
    op.create_table(
        "accounting_ledger_postings",
        sa.Column("posting_id", sa.String(length=255), nullable=False),
        sa.Column("journal_entry_id", sa.String(length=255), nullable=False),
        sa.Column("posting_sequence", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("chart_version", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("asset_id", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "amount > 0", name=op.f("ck_accounting_ledger_postings_positive_amount")
        ),
        sa.CheckConstraint(
            "side IN ('DEBIT', 'CREDIT')",
            name=op.f("ck_accounting_ledger_postings_valid_side"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "chart_version"],
            ["accounting_accounts.account_id", "accounting_accounts.chart_version"],
            name=op.f("fk_accounting_ledger_postings_account_id_accounting_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["accounting_ledger_entries.journal_entry_id"],
            name=op.f("fk_accounting_ledger_postings_journal_entry_id_accounting_ledger_entries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("posting_id", name=op.f("pk_accounting_ledger_postings")),
        sa.UniqueConstraint(
            "journal_entry_id",
            "posting_sequence",
            name=op.f("uq_accounting_ledger_postings_journal_entry_id"),
        ),
    )
    op.create_table(
        "accounting_position_lots",
        sa.Column("position_lot_id", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("instrument_id", sa.String(length=255), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_fill_id", sa.String(length=255), nullable=False),
        sa.Column("last_journal_entry_id", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "remaining_quantity >= 0",
            name=op.f("ck_accounting_position_lots_nonnegative_remaining"),
        ),
        sa.CheckConstraint(
            "(status = 'OPEN' AND remaining_quantity > 0 AND closed_at IS NULL) OR "
            "(status = 'CLOSED' AND remaining_quantity = 0 AND closed_at IS NOT NULL)",
            name=op.f("ck_accounting_position_lots_valid_lifecycle"),
        ),
        sa.CheckConstraint(
            "side IN ('LONG', 'SHORT')",
            name=op.f("ck_accounting_position_lots_valid_side"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name=op.f("ck_accounting_position_lots_valid_status"),
        ),
        sa.PrimaryKeyConstraint("position_lot_id", name=op.f("pk_accounting_position_lots")),
    )
    op.create_index(
        "ix_accounting_position_lots_instrument_open",
        "accounting_position_lots",
        ["instrument_id"],
        unique=False,
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.create_table(
        "account_reconciliation_cases",
        sa.Column("reconciliation_case_id", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("new_orders_allowed", sa.Boolean(), nullable=False),
        sa.Column("local_snapshot_id", sa.String(length=255), nullable=False),
        sa.Column("venue_snapshot_id", sa.String(length=255), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('STARTUP', 'CONTINUOUS', 'RECONNECT')",
            name=op.f("ck_account_reconciliation_cases_valid_mode"),
        ),
        sa.CheckConstraint(
            "new_orders_allowed = (status = 'CLEAR')",
            name=op.f("ck_account_reconciliation_cases_valid_order_gate"),
        ),
        sa.CheckConstraint(
            "status IN ('CLEAR', 'REVIEW_REQUIRED', 'HALTED')",
            name=op.f("ck_account_reconciliation_cases_valid_status"),
        ),
        sa.PrimaryKeyConstraint(
            "reconciliation_case_id", name=op.f("pk_account_reconciliation_cases")
        ),
    )
    op.create_index(
        "ix_account_reconciliation_cases_status",
        "account_reconciliation_cases",
        ["status", "opened_at"],
        unique=False,
    )
    op.create_table(
        "daily_ledger_snapshots",
        sa.Column("ledger_snapshot_id", sa.String(length=255), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("ledger_entry_count", sa.BigInteger(), nullable=False),
        sa.Column("last_event_hash", sa.String(length=64), nullable=False),
        sa.Column("ledger_state_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("public_key_base64", sa.Text(), nullable=False),
        sa.Column("signature_base64", sa.Text(), nullable=False),
        sa.Column("signature_algorithm", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "ledger_entry_count >= 0",
            name=op.f("ck_daily_ledger_snapshots_nonnegative_entry_count"),
        ),
        sa.CheckConstraint(
            "signature_algorithm = 'Ed25519'",
            name=op.f("ck_daily_ledger_snapshots_valid_signature_algorithm"),
        ),
        sa.PrimaryKeyConstraint("ledger_snapshot_id", name=op.f("pk_daily_ledger_snapshots")),
        sa.UniqueConstraint(
            "snapshot_date",
            "policy_version",
            name=op.f("uq_daily_ledger_snapshots_snapshot_date"),
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_ledger_snapshots")
    op.drop_index(
        "ix_account_reconciliation_cases_status",
        table_name="account_reconciliation_cases",
    )
    op.drop_table("account_reconciliation_cases")
    op.drop_index(
        "ix_accounting_position_lots_instrument_open",
        table_name="accounting_position_lots",
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.drop_table("accounting_position_lots")
    op.drop_table("accounting_ledger_postings")
    op.drop_table("accounting_ledger_entries")
    op.drop_table("accounting_entry_templates")
    op.drop_table("accounting_accounts")
