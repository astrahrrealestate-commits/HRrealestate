"""conversation summary and focus trail

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-23 17:00:00

Adds T2 conversation memory to agent_conversations (rolling summary, summary_through, summary_version)
and T1 focus_trail to agent_page_state (spec: 2026-10-23-agent-memory-context-design §6.2, Task C9).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "agent_conversations",
        sa.Column("summary_through", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_agent_conversations_summary_through_agent_turns"),
        "agent_conversations",
        "agent_turns",
        ["summary_through"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "agent_conversations",
        sa.Column("summary_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_page_state",
        sa.Column("focus_trail", JSONB(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agent_page_state", "focus_trail")
    op.drop_constraint(
        op.f("fk_agent_conversations_summary_through_agent_turns"),
        "agent_conversations",
        type_="foreignkey",
    )
    op.drop_column("agent_conversations", "summary_version")
    op.drop_column("agent_conversations", "summary_through")
    op.drop_column("agent_conversations", "summary")
