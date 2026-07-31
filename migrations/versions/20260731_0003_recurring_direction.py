"""Separate recurring series by transaction direction.

Revision ID: 20260731_0003
Revises: 20260726_0002
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op

revision = "20260731_0003"
down_revision = "20260726_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recurring_series", sa.Column("direction", sa.String(length=10)))
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE recurring_series SET direction = CASE "
            "WHEN typical_amount_cents > 0 THEN 'incoming' "
            "WHEN typical_amount_cents < 0 THEN 'outgoing' END"
        )
    )
    missing = bind.scalar(
        sa.text("SELECT count(*) FROM recurring_series WHERE direction IS NULL")
    )
    if missing:
        raise RuntimeError("cannot infer direction for zero-value recurring series")

    with op.batch_alter_table("recurring_series") as batch:
        batch.drop_constraint("uq_recurring_identity", type_="unique")
        batch.alter_column("direction", existing_type=sa.String(length=10), nullable=False)
        batch.create_unique_constraint(
            "uq_recurring_identity",
            ["account_id", "normalized_counterparty", "direction", "cadence"],
        )
        batch.create_check_constraint(
            "ck_recurring_direction", "direction IN ('incoming', 'outgoing')"
        )


def downgrade() -> None:
    bind = op.get_bind()
    collision = bind.scalar(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT account_id, normalized_counterparty, cadence "
            "FROM recurring_series "
            "GROUP BY account_id, normalized_counterparty, cadence "
            "HAVING count(*) > 1"
            ")"
        )
    )
    if collision:
        raise RuntimeError("cannot downgrade recurring series with direction collisions")

    with op.batch_alter_table("recurring_series") as batch:
        batch.drop_constraint("ck_recurring_direction", type_="check")
        batch.drop_constraint("uq_recurring_identity", type_="unique")
        batch.create_unique_constraint(
            "uq_recurring_identity",
            ["account_id", "normalized_counterparty", "cadence"],
        )
        batch.drop_column("direction")
