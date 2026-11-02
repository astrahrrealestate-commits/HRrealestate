"""agent_conversations: drop the single-column company_id index

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-02 13:00:00

0025 added (company_id, owner_id, last_turn_at), which leads with company_id, so the single-column index from 0009
is redundant (tests/unit/db/test_models_metadata.py keeps exactly one company_id-leading access path).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_agent_conversations_company_id"


def upgrade() -> None:
    op.drop_index(INDEX, table_name="agent_conversations")


def downgrade() -> None:
    op.create_index(INDEX, "agent_conversations", ["company_id"], unique=False)
