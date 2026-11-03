"""brixx_sync_runs and brixx_sync_table_state: bookkeeping for the BRIXX data mirror

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-02 10:00:00

Ordinary `public` tables (the mirrored BRIXX data itself lives in the separate `brixx` schema).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "brixx_sync_runs"
STATE = "brixx_sync_table_state"


def upgrade() -> None:
    op.create_table(
        RUNS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_brixx_sync_runs_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brixx_sync_runs")),
    )
    op.create_check_constraint(op.f("ck_brixx_sync_runs_kind"), RUNS, "kind IN ('incremental', 'reconcile')")
    op.create_check_constraint(
        op.f("ck_brixx_sync_runs_status"), RUNS, "status IN ('running', 'succeeded', 'failed')"
    )
    op.create_index("ix_brixx_sync_runs_company_started", RUNS, ["company_id", "started_at"], unique=False)
    op.create_table(
        STATE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("last_success_upd", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_page", sa.Integer(), server_default="0", nullable=False),
        sa.Column("row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("drifted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_brixx_sync_table_state_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            [f"{RUNS}.id"],
            name=op.f("fk_brixx_sync_table_state_last_run_id_brixx_sync_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brixx_sync_table_state")),
        sa.UniqueConstraint("company_id", "table_name", name=op.f("uq_brixx_sync_table_state_company_id_table_name")),
    )


def downgrade() -> None:
    op.drop_table(STATE)
    op.drop_index("ix_brixx_sync_runs_company_started", table_name=RUNS)
    op.drop_table(RUNS)
