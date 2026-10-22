"""agent_turns.timings (per-turn stage ms) and the messages thread index (company_id, channel, thread key)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22 12:00:00

The expression index serves the thread page's conversation scan (`page_memory.thread_conversation`, `page_facts`):
`WHERE company_id = ? AND channel = ? AND coalesce(thread_ref, provider_msg_id) = ?`. A plain CREATE INDEX briefly
blocks writes to `messages`; at Phase 1 volume (one owner) that is a short moment during the deploy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

THREAD_INDEX = "ix_messages_company_channel_thread"


def upgrade() -> None:
    op.add_column("agent_turns", sa.Column("timings", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index(
        THREAD_INDEX,
        "messages",
        ["company_id", "channel", sa.text("coalesce(thread_ref, provider_msg_id)")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(THREAD_INDEX, table_name="messages")
    op.drop_column("agent_turns", "timings")
