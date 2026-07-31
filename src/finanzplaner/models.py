from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    locale: Mapped[str] = mapped_column(String(5), default="de")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (CheckConstraint("locale IN ('de', 'en')", name="ck_user_locale"),)


class WebSession(Base):
    __tablename__ = "web_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(96))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    user: Mapped[User] = relationship()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(160))
    iban: Mapped[str] = mapped_column(String(34), unique=True, index=True)
    account_type: Mapped[str] = mapped_column(String(30), default="girokonto")
    visibility: Mapped[str] = mapped_column(String(10), index=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        CheckConstraint("account_type = 'girokonto'", name="ck_account_type"),
        CheckConstraint("visibility IN ('shared', 'private')", name="ck_account_visibility"),
        CheckConstraint(
            "(visibility = 'shared' AND owner_id IS NULL) OR "
            "(visibility = 'private' AND owner_id IS NOT NULL)",
            name="ck_account_owner",
        ),
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    label_de: Mapped[str] = mapped_column(String(160))
    label_en: Mapped[str | None] = mapped_column(String(160))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    assignable: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    parent: Mapped[Category | None] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[list[Category]] = relationship(back_populates="parent", order_by="Category.sort_order")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    export_from: Mapped[date] = mapped_column(Date)
    export_to: Mapped[date] = mapped_column(Date)
    reported_balance_cents: Mapped[int] = mapped_column(Integer)
    reported_balance_date: Mapped[date] = mapped_column(Date)
    row_count: Mapped[int] = mapped_column(Integer)
    inserted_count: Mapped[int] = mapped_column(Integer)
    duplicate_count: Mapped[int] = mapped_column(Integer)
    account: Mapped[Account] = relationship()


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"))
    balance_cents: Mapped[int] = mapped_column(Integer)
    balance_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (UniqueConstraint("import_batch_id", name="uq_snapshot_batch"),)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="RESTRICT"), index=True)
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    value_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(30))
    direction: Mapped[str] = mapped_column(String(10), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    payer: Mapped[str] = mapped_column(Text, default="")
    payee: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    transaction_type: Mapped[str] = mapped_column(Text, default="")
    counterparty_iban: Mapped[str] = mapped_column(String(34), default="", index=True)
    creditor_id: Mapped[str] = mapped_column(Text, default="")
    mandate_reference: Mapped[str] = mapped_column(Text, default="")
    customer_reference: Mapped[str] = mapped_column(Text, default="")
    display_counterparty: Mapped[str] = mapped_column(Text, default="")
    raw_fields: Mapped[dict[str, Any]] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(String(64))
    occurrence_index: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    category_actor_type: Mapped[str | None] = mapped_column(String(20))
    category_actor_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()
    notes: Mapped[list[TransactionNote]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", order_by="TransactionNote.created_at"
    )
    tag_links: Mapped[list[TransactionTag]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("account_id", "signature", "occurrence_index", name="uq_tx_occurrence"),
        CheckConstraint("currency = 'EUR'", name="ck_transaction_currency"),
        CheckConstraint("direction IN ('incoming', 'outgoing', 'zero')", name="ck_transaction_direction"),
        Index("ix_tx_account_booking_id", "account_id", "booking_date", "id"),
    )


class CategoryAssignmentEvent(Base):
    __tablename__ = "category_assignment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"), index=True)
    previous_category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TransactionNote(Base):
    __tablename__ = "transaction_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"), index=True)
    author_type: Mapped[str] = mapped_column(String(20))
    author_id: Mapped[str] = mapped_column(String(36))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    transaction: Mapped[Transaction] = relationship(back_populates="notes")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    normalized_name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (UniqueConstraint("account_id", "normalized_name", name="uq_tag_account_name"),)


class TransactionTag(Base):
    __tablename__ = "transaction_tags"

    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True)
    author_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    author_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    transaction: Mapped[Transaction] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship()


class TransferLink(Base):
    __tablename__ = "transfer_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    transaction_a_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), unique=True
    )
    transaction_b_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), unique=True
    )
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    transaction_a: Mapped[Transaction] = relationship(foreign_keys=[transaction_a_id])
    transaction_b: Mapped[Transaction] = relationship(foreign_keys=[transaction_b_id])


class RecurringSeries(Base):
    __tablename__ = "recurring_series"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    normalized_counterparty: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(10))
    cadence: Mapped[str] = mapped_column(String(20))
    typical_amount_cents: Mapped[int] = mapped_column(Integer)
    expected_next_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="detected")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    manually_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "normalized_counterparty",
            "direction",
            "cadence",
            name="uq_recurring_identity",
        ),
        CheckConstraint(
            "direction IN ('incoming', 'outgoing')", name="ck_recurring_direction"
        ),
        CheckConstraint(
            "cadence IN ('weekly', 'monthly', 'quarterly', 'yearly')", name="ck_recurring_cadence"
        ),
        CheckConstraint(
            "status IN ('detected', 'confirmed', 'rejected')", name="ck_recurring_status"
        ),
    )


class MonthlyReview(Base):
    __tablename__ = "monthly_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    month: Mapped[date] = mapped_column(Date, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    author_type: Mapped[str] = mapped_column(String(20))
    author_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (
        UniqueConstraint("account_id", "month", "revision", name="uq_review_revision"),
    )


class AgentToken(Base):
    __tablename__ = "agent_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    account_ids: Mapped[list[str]] = mapped_column(JSON)
    capabilities: Mapped[list[str]] = mapped_column(JSON)
    locale: Mapped[str] = mapped_column(String(5), default="de")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    user: Mapped[User] = relationship()


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_token_id: Mapped[str] = mapped_column(ForeignKey("agent_tokens.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (
        UniqueConstraint("agent_token_id", "action", "idempotency_key", name="uq_idempotency"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str] = mapped_column(String(60))
    object_id: Mapped[str | None] = mapped_column(String(36), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
