"""message_index_state: company-scoped status index

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-02 12:00:00

Every domain query filters by company_id (invariant 4); the backfill and retry sweeps read by status per company.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_message_index_state_company_status", "message_index_state", ["company_id", "status", "updated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_message_index_state_company_status", table_name="message_index_state")
