"""Initial Fin schema.

Revision ID: 20260725_0001
Revises:
Create Date: 2026-07-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260725_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("object_type", sa.String(length=60), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_events_object_id", "audit_events", ["object_id"])

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("locale", sa.String(length=5), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("locale IN ('de', 'en')", name="ck_user_locale"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("iban", sa.String(length=34), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("visibility", sa.String(length=10), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(visibility = 'shared' AND owner_id IS NULL) OR "
            "(visibility = 'private' AND owner_id IS NOT NULL)",
            name="ck_account_owner",
        ),
        sa.CheckConstraint("account_type = 'girokonto'", name="ck_account_type"),
        sa.CheckConstraint(
            "visibility IN ('shared', 'private')", name="ck_account_visibility"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_iban", "accounts", ["iban"], unique=True)
    op.create_index("ix_accounts_owner_id", "accounts", ["owner_id"])
    op.create_index("ix_accounts_visibility", "accounts", ["visibility"])

    op.create_table(
        "agent_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("account_ids", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("locale", sa.String(length=5), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_agent_tokens_prefix", "agent_tokens", ["prefix"], unique=True)
    op.create_index("ix_agent_tokens_user_id", "agent_tokens", ["user_id"])

    op.create_table(
        "categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("label_de", sa.String(length=160), nullable=False),
        sa.Column("label_en", sa.String(length=160), nullable=True),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.Column("assignable", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["categories.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_categories_key", "categories", ["key"], unique=True)
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])

    op.create_table(
        "web_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("csrf_token", sa.String(length=96), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_web_sessions_expires_at", "web_sessions", ["expires_at"])
    op.create_index("ix_web_sessions_user_id", "web_sessions", ["user_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_token_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_token_id"], ["agent_tokens.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_token_id",
            "action",
            "idempotency_key",
            name="uq_idempotency",
        ),
    )

    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("uploader_id", sa.String(length=36), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("export_from", sa.Date(), nullable=False),
        sa.Column("export_to", sa.Date(), nullable=False),
        sa.Column("reported_balance_cents", sa.Integer(), nullable=False),
        sa.Column("reported_balance_date", sa.Date(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_account_id", "import_batches", ["account_id"])
    op.create_index(
        "ix_import_batches_file_sha256", "import_batches", ["file_sha256"]
    )

    op.create_table(
        "monthly_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author_type", sa.String(length=20), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "month", "revision", name="uq_review_revision"
        ),
    )
    op.create_index(
        "ix_monthly_reviews_account_id", "monthly_reviews", ["account_id"]
    )
    op.create_index("ix_monthly_reviews_month", "monthly_reviews", ["month"])

    op.create_table(
        "recurring_series",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_counterparty", sa.Text(), nullable=False),
        sa.Column("cadence", sa.String(length=20), nullable=False),
        sa.Column("typical_amount_cents", sa.Integer(), nullable=False),
        sa.Column("expected_next_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("manually_overridden", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cadence IN ('weekly', 'monthly', 'quarterly', 'yearly')",
            name="ck_recurring_cadence",
        ),
        sa.CheckConstraint(
            "status IN ('detected', 'confirmed', 'rejected')",
            name="ck_recurring_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "normalized_counterparty",
            "cadence",
            name="uq_recurring_identity",
        ),
    )
    op.create_index(
        "ix_recurring_series_account_id", "recurring_series", ["account_id"]
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("normalized_name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "normalized_name", name="uq_tag_account_name"
        ),
    )
    op.create_index("ix_tags_account_id", "tags", ["account_id"])

    op.create_table(
        "balance_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("import_batch_id", sa.String(length=36), nullable=False),
        sa.Column("balance_cents", sa.Integer(), nullable=False),
        sa.Column("balance_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["import_batches.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_batch_id", name="uq_snapshot_batch"),
    )
    op.create_index(
        "ix_balance_snapshots_account_id", "balance_snapshots", ["account_id"]
    )
    op.create_index(
        "ix_balance_snapshots_balance_date", "balance_snapshots", ["balance_date"]
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("import_batch_id", sa.String(length=36), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payer", sa.Text(), nullable=False),
        sa.Column("payee", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("counterparty_iban", sa.String(length=34), nullable=False),
        sa.Column("creditor_id", sa.Text(), nullable=False),
        sa.Column("mandate_reference", sa.Text(), nullable=False),
        sa.Column("customer_reference", sa.Text(), nullable=False),
        sa.Column("display_counterparty", sa.Text(), nullable=False),
        sa.Column("raw_fields", sa.JSON(), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("occurrence_index", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("category_actor_type", sa.String(length=20), nullable=True),
        sa.Column("category_actor_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency = 'EUR'", name="ck_transaction_currency"),
        sa.CheckConstraint(
            "direction IN ('incoming', 'outgoing', 'zero')",
            name="ck_transaction_direction",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["import_batches.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "signature", "occurrence_index", name="uq_tx_occurrence"
        ),
    )
    op.create_index("ix_transactions_account_id", "transactions", ["account_id"])
    op.create_index(
        "ix_transactions_booking_date", "transactions", ["booking_date"]
    )
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
    op.create_index(
        "ix_transactions_counterparty_iban", "transactions", ["counterparty_iban"]
    )
    op.create_index("ix_transactions_direction", "transactions", ["direction"])
    op.create_index(
        "ix_transactions_import_batch_id", "transactions", ["import_batch_id"]
    )
    op.create_index("ix_transactions_value_date", "transactions", ["value_date"])
    op.create_index(
        "ix_tx_account_booking_id",
        "transactions",
        ["account_id", "booking_date", "id"],
    )

    op.create_table(
        "category_assignment_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("previous_category_id", sa.String(length=36), nullable=True),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["previous_category_id"], ["categories.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_category_assignment_events_transaction_id",
        "category_assignment_events",
        ["transaction_id"],
    )

    op.create_table(
        "transaction_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("author_type", sa.String(length=20), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transaction_notes_transaction_id",
        "transaction_notes",
        ["transaction_id"],
    )

    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.Column("author_type", sa.String(length=20), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint(
            "transaction_id", "tag_id", "author_type", "author_id"
        ),
    )

    op.create_table(
        "transfer_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_a_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_b_id", sa.String(length=36), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_a_id"], ["transactions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_b_id"], ["transactions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_a_id"),
        sa.UniqueConstraint("transaction_b_id"),
    )


def downgrade() -> None:
    op.drop_table("transfer_links")
    op.drop_table("transaction_tags")
    op.drop_table("transaction_notes")
    op.drop_table("category_assignment_events")
    op.drop_table("transactions")
    op.drop_table("balance_snapshots")
    op.drop_table("tags")
    op.drop_table("recurring_series")
    op.drop_table("monthly_reviews")
    op.drop_table("import_batches")
    op.drop_table("idempotency_records")
    op.drop_table("web_sessions")
    op.drop_table("categories")
    op.drop_table("agent_tokens")
    op.drop_table("accounts")
    op.drop_table("users")
    op.drop_table("audit_events")
