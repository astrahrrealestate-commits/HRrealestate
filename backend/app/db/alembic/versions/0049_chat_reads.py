"""chat_reads: when the owner last opened each WhatsApp-style chat

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-24 12:00:00

One row per (company, chat_key); an inbound message newer than `last_read_at` makes the chat unread.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_reads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("chat_key", sa.String(length=32), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_chat_reads_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_reads")),
        sa.UniqueConstraint("company_id", "chat_key", name=op.f("uq_chat_reads_company_id_chat_key")),
    )


def downgrade() -> None:
    op.drop_table("chat_reads")
