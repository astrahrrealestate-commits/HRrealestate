"""agent_conversation threads, title, last_turn_at, hidden_at, pinned, focus_state

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-02 00:25:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("title", sa.String(length=255), server_default="New Chat", nullable=False),
    )
    op.add_column(
        "agent_conversations",
        sa.Column("last_turn_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "agent_conversations",
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_conversations",
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "agent_conversations",
        sa.Column("focus_state", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index(
        "ix_agent_conversations_company_owner_last_turn",
        "agent_conversations",
        ["company_id", "owner_id", "last_turn_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_conversations_company_owner_last_turn", table_name="agent_conversations")
    op.drop_column("agent_conversations", "focus_state")
    op.drop_column("agent_conversations", "pinned")
    op.drop_column("agent_conversations", "hidden_at")
    op.drop_column("agent_conversations", "last_turn_at")
    op.drop_column("agent_conversations", "title")

