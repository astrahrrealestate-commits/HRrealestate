"""ticket_edits: persist owner maintenance ticket edits

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-12 15:34:05.211039

One row per case holding the owner's display edits from PATCH /api/maintenance/tickets, so an edit survives a
restart and reaches every API instance (invariant 1); the audit trail entry is a case_events row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_edits",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], name=op.f("fk_ticket_edits_case_id_cases")),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_ticket_edits_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_edits")),
        sa.UniqueConstraint("company_id", "case_id", name=op.f("uq_ticket_edits_company_id_case_id")),
    )
    op.create_index(op.f("ix_ticket_edits_case_id"), "ticket_edits", ["case_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ticket_edits_case_id"), table_name="ticket_edits")
    op.drop_table("ticket_edits")
