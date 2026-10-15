"""agent_turns (company_id, updated_at, id) index for the SSE turn cursor

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15 18:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_agent_turns_company_id_agent_turns_updated_at_agent_turns_id"),
        "agent_turns",
        ["company_id", "updated_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_turns_company_id_agent_turns_updated_at_agent_turns_id"), table_name="agent_turns")
