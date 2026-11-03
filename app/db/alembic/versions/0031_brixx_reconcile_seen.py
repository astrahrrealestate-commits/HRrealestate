"""brixx_reconcile_seen: primary keys staged by a BRIXX reconcile run

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-03 10:00:00

Each keyset page of a reconcile scan stages its keys here (unique per run/table/key, so a replayed step is a no-op);
the apply step soft-deletes mirror rows that were not seen and then deletes the staged keys.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "brixx_reconcile_seen"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("pk", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_brixx_reconcile_seen_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["brixx_sync_runs.id"], name=op.f("fk_brixx_reconcile_seen_run_id_brixx_sync_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brixx_reconcile_seen")),
        sa.UniqueConstraint(
            "company_id", "run_id", "table_name", "pk", name=op.f("uq_brixx_reconcile_seen_company_id_run_id_table_name_pk")
        ),
    )
    op.create_index(op.f("ix_brixx_reconcile_seen_run_id"), TABLE, ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_brixx_reconcile_seen_run_id"), table_name=TABLE)
    op.drop_table(TABLE)
