"""Repair import periods whose year disagrees with the balance snapshot.

Revision ID: 20260726_0002
Revises: 20260725_0001
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0002"
down_revision = "20260725_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    batches = sa.table(
        "import_batches",
        sa.column("id", sa.String),
        sa.column("export_from", sa.Date),
        sa.column("export_to", sa.Date),
        sa.column("reported_balance_date", sa.Date),
    )
    transactions = sa.table(
        "transactions",
        sa.column("import_batch_id", sa.String),
        sa.column("booking_date", sa.Date),
    )

    for batch in bind.execute(sa.select(batches)).mappings():
        export_from = batch["export_from"]
        export_to = batch["export_to"]
        balance_date = batch["reported_balance_date"]
        year_shift = balance_date.year - export_to.year
        if year_shift == 0:
            continue

        shifted_from = export_from.replace(year=export_from.year + year_shift)
        shifted_to = export_to.replace(year=export_to.year + year_shift)
        first_transaction, last_transaction = bind.execute(
            sa.select(
                sa.func.min(transactions.c.booking_date),
                sa.func.max(transactions.c.booking_date),
            ).where(transactions.c.import_batch_id == batch["id"])
        ).one()
        if (
            shifted_from > balance_date
            or balance_date > shifted_to
            or first_transaction is None
            or shifted_from > first_transaction
            or last_transaction > shifted_to
        ):
            raise RuntimeError("cannot safely repair import period year")

        bind.execute(
            sa.update(batches)
            .where(batches.c.id == batch["id"])
            .values(export_from=shifted_from, export_to=shifted_to)
        )


def downgrade() -> None:
    # The incorrect source year cannot be reconstructed safely.
    pass
