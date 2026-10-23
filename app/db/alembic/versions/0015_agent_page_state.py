"""agent_page_state: the owner's latest pre-warmed page facts (one row per owner, PUT /agent/page)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-23 12:00:00

One row per owner (unique owner_id), overwritten by each pre-warm, so the table never grows. `resolved` holds the
resolved page facts (tenant text, untrusted data); the client snapshot is never stored. The 120 s TTL is applied when
a turn reads the row (`app.pipeline.page_state`), not by deleting rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agent_page_state"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("page_key", sa.Text(), nullable=False),
        sa.Column("resolved", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_agent_page_state_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owner_accounts.id"], name=op.f("fk_agent_page_state_owner_id_owner_accounts")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_page_state")),
        sa.UniqueConstraint("owner_id", name=op.f("uq_agent_page_state_owner_id")),
    )
    op.create_index(op.f("ix_agent_page_state_company_id"), TABLE, ["company_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_page_state_company_id"), table_name=TABLE)
    op.drop_table(TABLE)
